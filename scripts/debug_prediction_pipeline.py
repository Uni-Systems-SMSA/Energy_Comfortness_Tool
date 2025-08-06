#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dashboard.app import *
import pandas as pd
from datetime import datetime
from db.session import SessionLocal
from db.models import Prediction, ComfortLevel

def debug_prediction_pipeline():
    """Debug the prediction pipeline to see why ComfortLevel records aren't created"""
    
    print("=== DEBUGGING PREDICTION PIPELINE ===")
    
    # Check current state
    ses = SessionLocal()
    p_count = ses.query(Prediction).count()
    c_count = ses.query(ComfortLevel).count()
    print(f"Before test - Predictions: {p_count}, ComfortLevels: {c_count}")
    ses.close()
    
    # Create minimal test data
    test_data = pd.DataFrame({
        'weather_id': [1, 2],
        'datetime': [datetime.now(), datetime.now()],
        'temp_c': [22.0, 23.0],
        'humidity_percent': [50.0, 55.0],
        'wind_speed_ms': [2.0, 2.5],
        'wind_direction_deg': [180.0, 190.0],
        'pressure_hpa': [1013.0, 1015.0],
        'cloud_cover_percent': [30.0, 35.0],
        'visibility_km': [10.0, 12.0],
        'uv_index': [5.0, 6.0],
        'solar_radiation_wm2': [500.0, 550.0],
        'dew_point_c': [10.0, 11.0]
    })
    
    print(f"Test data shape: {test_data.shape}")
    print(f"Test weather_ids: {test_data['weather_id'].tolist()}")
    
    try:
        # Call the actual prediction function
        print("\nCalling predict_button_callback...")
        result_df = predict_button_callback('eplus', test_data, None)
        
        print(f"Prediction result shape: {result_df.shape if result_df is not None else 'None'}")
        
        # Check final state
        ses = SessionLocal()
        p_count = ses.query(Prediction).count()
        c_count = ses.query(ComfortLevel).count()
        print(f"After prediction - Predictions: {p_count}, ComfortLevels: {c_count}")
        
        if p_count > 0:
            # Sample prediction data
            pred = ses.query(Prediction).first()
            print(f"Sample prediction: ID={pred.prediction_id}, weather_id={pred.weather_id}")
            print(f"  temp={pred.predicted_temperature_c}, rh={pred.predicted_rh_percent}")
        
        ses.close()
        
    except Exception as e:
        print(f"Error during prediction: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_prediction_pipeline()
