#!/usr/bin/env python3

from dashboard.app import _calculate_comfort_for_profile
from db.session import SessionLocal
from db.models import ComfortLevel, Prediction
from datetime import datetime
import pandas as pd

def test_comfort_creation():
    """Test creating ComfortLevel records"""
    
    ses = SessionLocal()
    
    try:
        # Get one prediction record to test with
        prediction = ses.query(Prediction).first()
        if not prediction:
            print("No prediction records found")
            return
            
        print(f"Testing with prediction ID: {prediction.prediction_id}")
        
        # Test data for comfort calculation
        base_data = {
            'temperature_c': prediction.predicted_temperature_c,
            'rh_percent': prediction.predicted_rh_percent,
            'luminance_lux': prediction.predicted_luminance_lux,
            'average_noise_db': prediction.predicted_average_noise_db,
            'co2_ppm': prediction.predicted_co2_ppm,
            'co_ppm': prediction.predicted_co_ppm,
            'tvoc_ppb': prediction.predicted_tvoc_ppb,
            'pm2_5_ugm3': prediction.predicted_pm2_5_ugm3,
            'pm10_ugm3': prediction.predicted_pm10_ugm3,
        }
        
        profile = {"name": "test", "age": 35, "description": "Test profile"}
        
        # Test comfort calculation
        comfort_data = _calculate_comfort_for_profile(base_data, profile)
        print("Comfort calculation successful!")
        print(f"Sample comfort data keys: {list(comfort_data.keys())}")
        
        # Try to create a ComfortLevel record
        comfort_level_data = comfort_data.copy()
        comfort_level_data.update({
            'prediction_id': prediction.prediction_id,
            'occupant_profile': profile["name"],
            'estimated_at': datetime.now()
        })
        
        print(f"Creating ComfortLevel with data: {comfort_level_data}")
        
        comfort_record = ComfortLevel(**comfort_level_data)
        ses.add(comfort_record)
        ses.commit()
        
        print("ComfortLevel record created successfully!")
        
        # Check count
        comfort_count = ses.query(ComfortLevel).count()
        print(f"Total ComfortLevel records: {comfort_count}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        ses.rollback()
    finally:
        ses.close()

if __name__ == "__main__":
    test_comfort_creation()
