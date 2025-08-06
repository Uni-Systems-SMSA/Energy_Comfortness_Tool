#!/usr/bin/env python3
"""Quick database state check."""

from db.session import SessionLocal
from db.models import Prediction, ComfortLevel, Weather

def check_db_state():
    """Check the current state of the database."""
    with SessionLocal() as ses:
        weather_count = ses.query(Weather).count()
        pred_count = ses.query(Prediction).count()
        comfort_count = ses.query(ComfortLevel).count()
        
        print(f"Database State:")
        print(f"  Weather records: {weather_count}")
        print(f"  Predictions: {pred_count}")
        print(f"  ComfortLevels: {comfort_count}")
        
        if pred_count > 0:
            sample_pred = ses.query(Prediction).first()
            print(f"\nSample Prediction:")
            print(f"  prediction_id: {sample_pred.prediction_id}")
            print(f"  weather_id: {sample_pred.weather_id}")
            print(f"  predicted_temperature_c: {sample_pred.predicted_temperature_c}")
            print(f"  predicted_at: {sample_pred.predicted_at}")
            
        if comfort_count > 0:
            sample_comfort = ses.query(ComfortLevel).first()
            print(f"\nSample ComfortLevel:")
            print(f"  comfort_id: {sample_comfort.comfort_id}")
            print(f"  prediction_id: {sample_comfort.prediction_id}")
            print(f"  occupant_profile: {sample_comfort.occupant_profile}")
            print(f"  pmv: {sample_comfort.pmv}")
            print(f"  thermal_comfort_class: {sample_comfort.thermal_comfort_class}")
            
        return weather_count, pred_count, comfort_count

if __name__ == "__main__":
    check_db_state()
