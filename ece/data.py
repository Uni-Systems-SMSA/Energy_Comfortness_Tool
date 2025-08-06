# ece/data.py
from pathlib import Path
import pandas as pd
from sqlalchemy.orm import Session
from db.session import SessionLocal
from db.models import RawMeasurement, FeatureVector, Prediction

DATA_DIR = Path(os.getenv("ECT_DATA_DIR", "./model_store"))
DATA_DIR.mkdir(exist_ok=True)

class DataRepository:
    def __init__(self):
        self.db: Session = SessionLocal()

    # ---------- Ingest ----------
    def ingest_csv(self, csv_bytes: bytes, dataset_id: int) -> pd.DataFrame:
        df = pd.read_csv(pd.compat.StringIO(csv_bytes.decode()))
        df["dataset_id"] = dataset_id
        # bulk insert as JSON rows
        self.db.bulk_save_objects([
            RawMeasurement(dataset_id=dataset_id,
                           ts=row["timestamp"],
                           data=row.to_dict())
            for _, row in df.iterrows()
        ])
        self.db.commit()
        return df

    # ---------- Feature vectors ----------
    def write_features(self, df_feat: pd.DataFrame, dataset_id: int):
        self.db.bulk_save_objects([
            FeatureVector(dataset_id=dataset_id,
                          ts=row["timestamp"],
                          features=row.drop("timestamp").to_dict())
            for _, row in df_feat.iterrows()
        ])
        self.db.commit()

    def load_features(self, dataset_id: int) -> pd.DataFrame:
        q = self.db.query(FeatureVector).filter_by(dataset_id=dataset_id)
        records = [{**fv.features, "timestamp": fv.ts} for fv in q]
        return pd.DataFrame(records)

    # ---------- Predictions ----------
    def write_predictions(self, model_id: int, df_pred: pd.DataFrame):
        self.db.bulk_save_objects([
            Prediction(model_id=model_id,
                       ts=row["timestamp"],
                       output=row["y_pred"],
                       comfort=row["comfort"])
            for _, row in df_pred.iterrows()
        ])
        self.db.commit()
