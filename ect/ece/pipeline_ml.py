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
    logger = get_logger(__name__)
except ImportError:
    import logging
    from pathlib import Path
    from logging.handlers import RotatingFileHandler
    
    # Configure module-specific logging
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True, parents=True)
    
    logger = logging.getLogger(__name__)
    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s — %(levelname)s — %(name)s — %(message)s")
        
        # File handler for this module
        fh = RotatingFileHandler(
            log_dir / f"{__name__}.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        
        # Console handler
        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO)
        sh.setFormatter(formatter)
        logger.addHandler(sh)
        
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

# ---------------------------------------------------------------------------
# Globals & regex
# ---------------------------------------------------------------------------
_DERIV_RE = re.compile(r"^(?P<base>.+)_(?P<agg>mean|std|max|min)_(?P<win>\d+)h$")
_AGG_FUN = {"mean": "mean", "std": "std", "max": "max", "min": "min"}

MODEL_DIR = Path("./models"); MODEL_DIR.mkdir(exist_ok=True, parents=True)
REPORT_DIR = Path("./model_reports"); REPORT_DIR.mkdir(exist_ok=True, parents=True)

# Hidden flag for detailed model comparison export (developer use only)
EXPORT_MODEL_COMPARISON = True
COMPARISON_DIR = Path("./model_reports/model_comparison"); COMPARISON_DIR.mkdir(exist_ok=True, parents=True)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _fetch_base_dataframe(feats: List[str], target: str, ses) -> pd.DataFrame:
    base_cols = {target, "time_end", "space_id"}
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

    # Training should use ALL available data where the target variable is NOT NULL
    # Do NOT filter by data_type - that field is for upload classification, not training
    target_col = getattr(Measurement, target)
    q = (
        ses.query(*measurement_cols, *weather_columns)
        .join(
            Weather,
            (Measurement.time_end == Weather.time_end) &
            (Measurement.space_id == Weather.space_id),
            isouter=True
        )
        .filter(target_col.isnot(None))  # Only rows with observed target values
    )

    df = pd.read_sql(q.statement, ses.bind, parse_dates=["time_end"])
    df = df.sort_values(["space_id", "time_end"])
    logger.info("Fetched %d rows for %s (all data with observed %s)", len(df), target, target)
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
              .groupby("space_id")[base]
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
    all_models_info = []  # Store all trained models for comparison export
    
    for name, model in _CANDIDATES:
        model.fit(X_tr, y_tr)
        metrics = _evaluate(model, X_val, y_val)
        logger.info("   · %s: r2=%.3f mae=%.3f", name, metrics["r2"], metrics["mae"])
        
        # Store model info for export
        all_models_info.append({
            "name": name,
            "model": model,
            "metrics": metrics
        })
        
        if metrics["r2"] > best_metrics["r2"] * 1.01:  # 1 % better
            best_name, best_model, best_metrics = name, model, metrics
    
    return best_name, best_model, best_metrics, all_models_info


def _safe_params(name: str):
    for n, m in _CANDIDATES:
        if n == name:
            return m.get_params()
    return {}


def _upsert_trained_model(ses, target: str, space_id: str, version: str, algo: str, model_path: Path, metrics: Dict):
    row = (
        ses.query(TrainedModel)
           .filter(
               TrainedModel.target == target, 
               TrainedModel.version == version,
               TrainedModel.space_id == space_id
           )
           .one_or_none()
    )
    now = datetime.utcnow()
    if row is None:
        row = TrainedModel(target=target, space_id=space_id, version=version, train_started=now)
        ses.add(row)
    row.algorithm = algo
    row.metrics = metrics
    row.model_path = str(model_path)
    row.train_finished = now
    row.hyperparams = _safe_params(algo)
    ses.commit()
    logger.info("   · DB upsert model_id=%s (space=%s)", row.model_id, space_id)


def _export_model_comparison(target: str, space_id: str, version: str, df_val: pd.DataFrame, feats: List[str], 
                             all_models_info: List[Dict], comparison_dir: Path) -> None:
    """Export detailed model comparison CSV with validation predictions only.
    
    Args:
        target: Target variable name
        space_id: Space identifier
        version: Training version string
        df_val: Validation DataFrame with time_end and all features
        feats: List of feature names
        all_models_info: List of dicts with 'name', 'model', 'metrics' keys
        comparison_dir: Directory to save comparison CSV
    """
    # Start with timestamp and input features
    export_df = df_val[["time_end"] + feats].copy()
    
    # Add observed output
    export_df[f"observed_{target}"] = df_val[target].values
    
    # Add predictions from each model (on validation set only)
    X_val = df_val[feats]
    for model_info in all_models_info:
        name = model_info["name"]
        model = model_info["model"]
        predictions = model.predict(X_val)
        export_df[f"pred_{name.lower()}"] = predictions
    
    # Save to CSV with space_id in filename
    csv_path = comparison_dir / f"{target}_{space_id}_{version}_comparison.csv"
    export_df.to_csv(csv_path, index=False)
    logger.info("   · Exported model comparison (validation set only) to %s (%d rows)", csv_path, len(export_df))

# ---------------------------------------------------------------------------
# Main entry‑point
# ---------------------------------------------------------------------------

def main_train_all_targets(*, model_dir: Path | str = MODEL_DIR, report_dir: Path | str = REPORT_DIR, version: str | None = None) -> None:
    version = version or datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    model_dir, report_dir = Path(model_dir), Path(report_dir)
    model_dir.mkdir(exist_ok=True, parents=True)
    report_dir.mkdir(exist_ok=True, parents=True)

    with SessionLocal() as ses:
        # Get all unique space_ids from the database
        from db.models import Space
        spaces = ses.query(Space.space_id).distinct().all()
        space_ids = [s[0] for s in spaces]
        
        logger.info("[ECT] Found %d spaces to train models for: %s", len(space_ids), ', '.join(space_ids))
        
        for target, feats in FEATURE_MAP.items():
            logger.info("\n[ECT] ====== Training target: %s (v=%s) ======", target, version)
            
            for space_id in space_ids:
                logger.info("\n  [Space: %s]", space_id)
                
                df_raw = _fetch_base_dataframe(feats, target, ses)
                if df_raw.empty:
                    logger.warning("    – skipped (no rows for any space)")
                    continue
                
                # Filter for this specific space
                df_space = df_raw[df_raw['space_id'] == space_id].copy()
                if df_space.empty:
                    logger.warning("    – skipped (no rows for space %s)", space_id)
                    continue
                
                # Log date range of training data
                min_date = df_space['time_end'].min()
                max_date = df_space['time_end'].max()
                logger.info("    – Training data range: %s to %s (%d rows)", 
                           min_date.strftime('%Y-%m-%d'), max_date.strftime('%Y-%m-%d'), len(df_space))
                
                df = _add_derived_features(df_space, feats).dropna(subset=feats + [target])
                if df.empty:
                    logger.warning("    – skipped (after NA drop)")
                    continue
                
                # Check minimum data requirement
                if len(df) < 50:
                    logger.warning("    – skipped (insufficient data: %d rows, need at least 50)", len(df))
                    continue
                
                logger.info("    – After feature engineering & NA drop: %d rows", len(df))
                
                tr, val = _split(df)
                logger.info("    – Split: train=%d (80%%), validation=%d (20%%)", len(tr), len(val))
                logger.info("    – Validation data range: %s to %s", 
                           val['time_end'].min().strftime('%Y-%m-%d'), 
                           val['time_end'].max().strftime('%Y-%m-%d'))
                
                algo, model, metrics, all_models_info = _best_candidate(tr[feats], tr[target], val[feats], val[target])
                fname = f"{target}_{space_id}_{algo}_{version}.joblib"
                model_path = model_dir / fname
                joblib.dump({"model": model, "features": feats, "targets": [target], "space_id": space_id}, model_path)
                _upsert_trained_model(ses, target, space_id, version, algo, model_path, metrics)
                logger.info("    – chosen %s r2=%.3f mae=%.3f", algo, metrics["r2"], metrics["mae"])
                
                # Export detailed model comparison if flag is enabled
                # Export VALIDATION dataset only (matches reported metrics)
                if EXPORT_MODEL_COMPARISON:
                    _export_model_comparison(target, space_id, version, val, feats, all_models_info, COMPARISON_DIR)
                
                # mini markdown report
                report_path = report_dir / f"{target}_{space_id}_{version}.md"
                report_path.write_text(
                    "# Target: {t}\n\n**Space**: {s}\n\n**Algorithm**: {a}\n\n| metric | value |\n|---|---|\n| R² | {r2:.3f} |\n| MAE | {mae:.3f} |\n".format(
                        t=target, s=space_id, a=algo, **metrics
                    )
                )

    logger.info("\n[ECT] ====== All targets and spaces processed ======")

    logger.info("[ECT] All targets processed.")


if __name__ == "__main__":
    main_train_all_targets()
