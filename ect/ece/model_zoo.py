from __future__ import annotations
from pathlib import Path
import joblib
from typing import Dict, List

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.multioutput import MultiOutputRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from ece.utils.logging import init_logger

logger = init_logger(__name__)

# ece/model_zoo.py

import pickle
from pathlib import Path

class BaseWrapper:
    """
    A minimal base class for all multi-output regressors.
    Subclasses must implement:
      - _build(self) -> returns a fitted/unfitted underlying model
    """
    def __init__(self, features: list[str], targets: list[str]):
        self.features = features
        self.targets  = targets
        self.model    = self._build()

    def _build(self):
        """Construct and return the underlying model. Override in subclass."""
        raise NotImplementedError

    def fit(self, df_train, df_val=None):
        """Fit the model. By default, assumes sklearn-style .fit(X, y)."""
        X = df_train[self.features]
        y = df_train[self.targets]
        self.model.fit(X, y)
        return self

    def predict(self, df):
        X = df[self.features]
        yhat = self.model.predict(X)
        # handle both 1D and 2D outputs
        import pandas as pd
        arr = yhat if yhat.ndim > 1 else yhat[:, None]
        return pd.DataFrame(arr, columns=self.targets, index=df.index)

    ## OLD ##
    # def save(self, tag: str, folder: Path | str = "models"):
    #     p = Path(folder) / f"{self.__class__.__name__}_{tag}.pkl"
    #     p.parent.mkdir(exist_ok=True, parents=True)
    #     with open(p, "wb") as f:
    #         pickle.dump(self.model, f)
    def save(self, tag: str, folder: Path | str = "models"):
        p = Path(folder) / f"{self.__class__.__name__}_{tag}.pkl"
        p.parent.mkdir(exist_ok=True, parents=True)
        joblib.dump(
            {
                "model": self.model,
                "features": self.features,
                "targets": self.targets,
                "params": {},
            },
            p,
        )

    def load(cls, path: str | Path):
        obj = joblib.load(path)
        try:
            wrapper = cls(obj["features"], obj["targets"], obj["params"], save_dir=Path(path).parent)
        except TypeError:
            try:
                wrapper = cls(obj["features"], obj["targets"], save_dir=Path(path).parent)
            except TypeError:
                wrapper = cls(obj["features"], obj["targets"])
        wrapper.model = obj["model"]
        return wrapper

class LightGBMMulti:
    """
    Multi-output LightGBM wrapper with a uniform .fit/.predict API.
    """

    def __init__(
        self,
        features: List[str],
        targets: List[str],
        lgb_params: Dict | None = None,
        save_dir: Path | str = Path("models"),
    ):
        self.features = features
        self.targets = targets
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(exist_ok=True, parents=True)

        default = dict(
            objective="regression",
            n_estimators=400,
            learning_rate=0.05,
            num_leaves=64,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
        )
        self.lgb_params = {**default, **(lgb_params or {})}

        self.model = MultiOutputRegressor(
            lgb.LGBMRegressor(**self.lgb_params), n_jobs=-1
        )

    # --- training / inference -------------------------------------------------
    def fit(self, df_train: pd.DataFrame, df_val: pd.DataFrame | None = None):
        X_train, y_train = df_train[self.features], df_train[self.targets]
        logger.info("Fitting on %s rows × %s features", *X_train.shape)

        self.model.fit(X_train, y_train)

        if df_val is not None:
            self._eval(df_val)

    def predict(self, df_future: pd.DataFrame) -> pd.DataFrame:
        preds = self.model.predict(df_future[self.features])
        return pd.DataFrame(preds, index=df_future.index, columns=self.targets)

    # --- persistence ----------------------------------------------------------
    def save(self, tag: str):
        path = self.save_dir / f"lgbm_{tag}.pkl"
        joblib.dump(
            dict(
                model=self.model,
                features=self.features,
                targets=self.targets,
                params=self.lgb_params,
            ),
            path,
        )
        logger.info("Model saved -> %s", path)

    @classmethod
    def load(cls, path: str | Path) -> "LightGBMMulti":
        obj = joblib.load(path)
        try:
            wrapper = cls(obj["features"], obj["targets"], obj["params"], save_dir=Path(path).parent)
        except TypeError:
            wrapper = cls(obj["features"], obj["targets"], save_dir=Path(path).parent)
        wrapper.model = obj["model"]
        return wrapper

    # --- helpers --------------------------------------------------------------
    def _eval(self, df_val: pd.DataFrame):
        X_val, y_val = df_val[self.features], df_val[self.targets]
        y_hat = self.model.predict(X_val)

        metrics = dict(
            MAE=mean_absolute_error(y_val, y_hat, multioutput="raw_values"),
            RMSE=np.sqrt(mean_squared_error(y_val, y_hat, multioutput="raw_values")),
            R2=r2_score(y_val, y_hat, multioutput="raw_values"),
        )
        msg = " | ".join(
            f"{t}: MAE={m[0]:.3f} RMSE={m[1]:.3f} R²={m[2]:.3f}"
            for t, m in zip(self.targets, zip(*metrics.values()))
        )
        logger.info("Validation -> %s", msg)

from sklearn.multioutput import MultiOutputRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
import xgboost as xgb
import catboost as cb
# ...

from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

class RidgeMulti(LightGBMMulti):
    def __init__(self, features, targets, save_dir=Path("models")):
        super().__init__(features, targets, lgb_params=None, save_dir=save_dir)
        ridge_pipe = make_pipeline(
            SimpleImputer(strategy="mean"),  # fill NaNs
            StandardScaler(),
            Ridge(alpha=1.0)
        )
        self.model = MultiOutputRegressor(ridge_pipe)


class RandomForestMulti(LightGBMMulti):
    def __init__(self, features, targets, save_dir=Path("models")):
        super().__init__(features, targets, lgb_params=None, save_dir=save_dir)
        self.model = MultiOutputRegressor(
            RandomForestRegressor(
                n_estimators=300,
                max_depth=None,
                n_jobs=-1,
                random_state=42,
            )
        )

class XGBMulti(LightGBMMulti):
    def __init__(self, features, targets, save_dir=Path("models")):
        super().__init__(features, targets, lgb_params=None, save_dir=save_dir)
        self.model = MultiOutputRegressor(
            xgb.XGBRegressor(
                objective="reg:squarederror",
                n_estimators=400,
                learning_rate=0.05,
                max_depth=6,
                subsample=0.8,
                colsample_bytree=0.8,
                n_jobs=-1,
                random_state=42,
            )
        )

class CatBoostMulti(LightGBMMulti):
    def __init__(self, features, targets, save_dir=Path("models")):
        super().__init__(features, targets, lgb_params=None, save_dir=save_dir)
        self.model = MultiOutputRegressor(
            cb.CatBoostRegressor(
                iterations=400,
                learning_rate=0.05,
                depth=6,
                loss_function="RMSE",
                verbose=False,
                random_state=42,
            )
        )

from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.multioutput import MultiOutputRegressor

class ExtraTreesMulti(BaseWrapper):
    def _build(self):
        return MultiOutputRegressor(
            ExtraTreesRegressor(
                n_estimators=300,
                max_depth=None,
                n_jobs=-1,
                random_state=42,
            )
        )

class HistGBMulti(BaseWrapper):
    def _build(self):
        return MultiOutputRegressor(
            HistGradientBoostingRegressor(
                learning_rate=0.05,
                max_depth=6,
                l2_regularization=0.1,
                random_state=42,
            )
        )

# --- add to ece/model_zoo.py ----------------------------------------
from prophet import Prophet            # pip install prophet
from joblib import dump, load
from pathlib import Path
import pandas as pd

class ProphetMulti(BaseWrapper):
    """Wraps fbprophet / prophet for regression with optional regressors."""
    def _build(self):
        # placeholder — we hold one Prophet per target in a dict
        return {}

    # ------------------------------------------------------------------ fit
    def fit(self, df_train: pd.DataFrame, df_val: pd.DataFrame | None = None):
        for tgt in self.targets:          # e.g. 'temperature_c_target'
            raw_tgt = tgt.replace("_target", "")
            # Prophet expects columns 'ds' (datetime) and 'y'
            df_p = pd.DataFrame({
                "ds": df_train["time_end"].dt.tz_convert(None),   # naive dt
                "y":  df_train[tgt],
            })
            for col in self.features:
                df_p[col] = df_train[col]
            m = Prophet(
                yearly_seasonality=False, weekly_seasonality=False,
                daily_seasonality=False
            )
            # declare regressors
            for col in self.features:
                m.add_regressor(col)
            m.fit(df_p)
            self.model[raw_tgt] = m
        return self

    # ---------------------------------------------------------------- predict
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        preds = {}
        for tgt in self.targets:
            raw_tgt = tgt.replace("_target", "")
            m = self.model[raw_tgt]
            df_p = pd.DataFrame({
                "ds": df["time_end"].dt.tz_convert(None)
            })
            for col in self.features:
                df_p[col] = df[col]
            fcst = m.predict(df_p)
            preds[tgt] = fcst["yhat"].values
        return pd.DataFrame(preds, index=df.index)

    # ---------------------------------------------------------------- save/load
    def save(self, tag: str, folder: Path | str = "models"):
        p = Path(folder) / f"prophet_{tag}.joblib"
        dump(self.model, p)

    def load(self, tag: str, folder: Path | str = "models"):
        p = Path(folder) / f"prophet_{tag}.joblib"
        self.model = load(p)

# ---- ElasticNetMulti --------------------------------------------------
from sklearn.linear_model import ElasticNet

class ElasticNetMulti(LightGBMMulti):
    """
    Multi-output Elastic-Net (linear regression with L1/L2 mix) wrapped in a
    pipeline:  imputes missing values -> standardises -> fits ElasticNet.

    Parameters are deliberately modest; tune if you wish.
    """
    def __init__(self,
                 features: List[str],
                 targets: List[str],
                 save_dir: Path | str = Path("models")
                 ):
        super().__init__(features, targets, lgb_params=None, save_dir=save_dir)

        enet_pipe = make_pipeline(
            SimpleImputer(strategy="mean"),
            StandardScaler(with_mean=True, with_std=True),
            ElasticNet(alpha=0.1,           # overall strength
                       l1_ratio=0.5,        # 0 = Ridge, 1 = Lasso
                       max_iter=10_000,
                       random_state=42)
        )
        self.model = MultiOutputRegressor(enet_pipe)