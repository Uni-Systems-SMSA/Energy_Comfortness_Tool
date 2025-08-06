#!/usr/bin/env python3

from db.session import SessionLocal
from db.models import Prediction, ComfortLevel

def check_db_state():
    """Check current database state"""
    ses = SessionLocal()
    
    try:
        p_count = ses.query(Prediction).count()
        c_count = ses.query(ComfortLevel).count()
        
        print(f"Predictions: {p_count}")
        print(f"ComfortLevels: {c_count}")
        
        if p_count > 0:
            # Check a sample prediction
            pred = ses.query(Prediction).first()
            print(f"Sample prediction ID: {pred.prediction_id}")
            print(f"Weather ID: {pred.weather_id}")
            print(f"Temperature: {pred.predicted_temperature_c}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ses.close()

if __name__ == "__main__":
    check_db_state()
