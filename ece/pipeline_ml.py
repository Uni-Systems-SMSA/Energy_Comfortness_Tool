# -*- coding: utf-8 -*-
"""ECT training pipeline – multi‑model, DB‑aware (trained_models).

* Derives rolling‑window + time‑harmonic features on the fly.
* Tries several regressors per target, picks the one with **best R²**.
* Logs progress via the project logger (no bare prints).
* Saves winning model artefacts and upserts the `trained_models` table.

Public API
~~~~~~~~~~
```python
main_train_all_targets(model_dir="./models", report_dir="./model_reports")
```
"""

from __future__ import annotations

import importlib.util
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

# ---------------------------------------------------------------------------
# Optional model libraries (XGBoost / CatBoost if installed)
# ---------------------------------------------------------------------------
_CANDIDATES = [
    ("LightGBM", LGBMRegressor(random_state=0)),
    ("RandomForest", RandomForestRegressor(random_state=0, n_estimators=200)),
]

if importlib.util.find_spec("xgboost"):
    from xgboost import XGBRegressor  # type: ignore

    _CANDIDATES.append(("XGBoost", XGBRegressor(random_state=0, n_estimators=500)))

if importlib.util.find_spec("catboost"):
    from catboost import CatBoostRegressor  # type: ignore

    _CANDIDATES.append(("CatBoost", CatBoostRegressor(verbose=False, random_seed=0)))

# ---------------------------------------------------------------------------
# Project imports & logger
# ---------------------------------------------------------------------------
sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

from db.session import SessionLocal  # noqa: E402
from db.models import Measurement, Weather, TrainedModel  # noqa: E402
from ece.feature_map import MAP as FEATURE_MAP, TIME_DRIVERS  # noqa: E402

try:
    from ece.utils.logging import get_logger  # type: ignore[attr-defined]
except Exception:
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s – %(message)s")

    def get_logger(name):  # type: ignore
        return logging.getLogger(name)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Globals & regex
# ---------------------------------------------------------------------------
_DERIV_RE = re.compile(r"^(?P<base>.+)_(?P<agg>mean|std|max|min)_(?P<win>\d+)h$")
_AGG_FUN = {"mean": "mean", "std": "std", "max": "max", "min": "min"}

MODEL_DIR = Path("./models"); MODEL_DIR.mkdir(exist_ok=True, parents=True)
REPORT_DIR = Path("./model_reports"); REPORT_DIR.mkdir(exist_ok=True, parents=True)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _fetch_base_dataframe(feats: List[str], target: str, ses) -> pd.DataFrame:
    base_cols = {target, "time_end", "sensor_id"}
    weather_cols = set()

    for f in feats:
        if f in TIME_DRIVERS:
            continue
        logger.info("Fetching feature %s for target %s", f, target)

        # Check if the feature is a derived one
        m = _DERIV_RE.match(f)
        base_feature = m.group("base") if m else f

        if hasattr(Measurement, base_feature):
            base_cols.add(base_feature)
        elif hasattr(Weather, base_feature):
            weather_cols.add(base_feature)
        else:
            logger.warning("Feature %s not found in Measurement or Weather", base_feature)

    measurement_cols = [getattr(Measurement, c) for c in base_cols if hasattr(Measurement, c)]
    weather_columns = [getattr(Weather, c) for c in weather_cols if hasattr(Weather, c)]

    q = (
        ses.query(*measurement_cols, *weather_columns)
        .join(
            Weather,
            (Measurement.time_end == Weather.time_end) &
            (Measurement.sensor_id == Weather.sensor_id),
            isouter=True
        )
        .filter(Measurement.data_type == "train")
    )

    df = pd.read_sql(q.statement, ses.bind, parse_dates=["time_end"])
    df = df.sort_values(["sensor_id", "time_end"])
    logger.debug("Fetched %d rows for %s", len(df), target)
    return df

def _add_derived_features(df: pd.DataFrame, feats: List[str]) -> pd.DataFrame:
    df = df.copy()
    # rolling‑window features
    for f in feats:
        if f in df.columns or f in TIME_DRIVERS:
            continue
        m = _DERIV_RE.match(f)
        if not m:
            logger.warning("Feature %s does not match derivation pattern", f)
            continue
        base, agg, win = m.group("base"), m.group("agg"), int(m.group("win"))
        rolled = (
            df.set_index("time_end")
              .groupby("sensor_id")[base]
              .rolling(f"{win}h", min_periods=1)
              .agg(_AGG_FUN[agg])
              .reset_index(level=0, drop=True)
        )
        df[f] = rolled.values
    # time‑harmonics
    if any(td in feats for td in TIME_DRIVERS):
        doy = df["time_end"].dt.dayofyear
        hod = df["time_end"].dt.hour + df["time_end"].dt.minute / 60
        if "doy_sin" in feats and "doy_sin" not in df.columns:
            df["doy_sin"] = np.sin(2 * math.pi * doy / 365)
        if "doy_cos" in feats and "doy_cos" not in df.columns:
            df["doy_cos"] = np.cos(2 * math.pi * doy / 365)
        if "hour_sin" in feats and "hour_sin" not in df.columns:
            df["hour_sin"] = np.sin(2 * math.pi * hod / 24)
        if "hour_cos" in feats and "hour_cos" not in df.columns:
            df["hour_cos"] = np.cos(2 * math.pi * hod / 24)
    return df


def _split(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    idx = int(0.8 * len(df))
    return df.iloc[:idx], df.iloc[idx:]


def _evaluate(model, X_val, y_val):
    pred = model.predict(X_val)
    return {"r2": float(r2_score(y_val, pred)), "mae": float(mean_absolute_error(y_val, pred))}


def _best_candidate(X_tr, y_tr, X_val, y_val):
    best_name, best_model, best_metrics = None, None, {"r2": -np.inf}
    for name, model in _CANDIDATES:
        model.fit(X_tr, y_tr)
        metrics = _evaluate(model, X_val, y_val)
        logger.info("   · %s: r2=%.3f mae=%.3f", name, metrics["r2"], metrics["mae"])
        if metrics["r2"] > best_metrics["r2"] * 1.01:  # 1 % better
            best_name, best_model, best_metrics = name, model, metrics
    return best_name, best_model, best_metrics


def _safe_params(name: str):
    for n, m in _CANDIDATES:
        if n == name:
            return m.get_params()
    return {}


def _upsert_trained_model(ses, target: str, version: str, algo: str, model_path: Path, metrics: Dict):
    row = (
        ses.query(TrainedModel)
           .filter(TrainedModel.target == target, TrainedModel.version == version)
           .one_or_none()
    )
    now = datetime.utcnow()
    if row is None:
        row = TrainedModel(target=target, version=version, train_started=now)
        ses.add(row)
    row.algorithm = algo
    row.metrics = metrics
    row.model_path = str(model_path)
    row.train_finished = now
    row.hyperparams = _safe_params(algo)
    ses.commit()
    logger.info("   · DB upsert model_id=%s", row.model_id)

# ---------------------------------------------------------------------------
# Main entry‑point
# ---------------------------------------------------------------------------

def main_train_all_targets(*, model_dir: Path | str = MODEL_DIR, report_dir: Path | str = REPORT_DIR, version: str | None = None) -> None:
    version = version or datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    model_dir, report_dir = Path(model_dir), Path(report_dir)
    model_dir.mkdir(exist_ok=True, parents=True)
    report_dir.mkdir(exist_ok=True, parents=True)

    with SessionLocal() as ses:
        for target, feats in FEATURE_MAP.items():
            logger.info("[ECT] Training %s (v=%s)…", target, version)
            df_raw = _fetch_base_dataframe(feats, target, ses)
            if df_raw.empty:
                logger.warning("  – skipped (no rows)")
                continue
            df = _add_derived_features(df_raw, feats).dropna(subset=feats + [target])
            if df.empty:
                logger.warning("  – skipped (after NA drop)")
                continue
            tr, val = _split(df)
            algo, model, metrics = _best_candidate(tr[feats], tr[target], val[feats], val[target])
            fname = f"{target}_{algo}_{version}.joblib"
            model_path = model_dir / fname
            joblib.dump({"model": model, "features": feats, "targets": [target]}, model_path)
            _upsert_trained_model(ses, target, version, algo, model_path, metrics)
            logger.info("  – chosen %s r2=%.3f mae=%.3f", algo, metrics["r2"], metrics["mae"])
            # mini markdown report
            (report_dir / f"{target}_{version}.md").write_text(
                "# Target: {t}\n\n**Algorithm**: {a}\n\n| metric | value |\n|---|---|\n| R² | {r2:.3f} |\n| MAE | {mae:.3f} |\n".format(t=target, a=algo, **metrics)
            )

    logger.info("[ECT] All targets processed.")


if __name__ == "__main__":
    main_train_all_targets()
