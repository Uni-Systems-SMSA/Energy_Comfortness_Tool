#!/usr/bin/env python3
"""
Test script to verify that the new prediction system creates comfort data in the predictions table.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from db.session import SessionLocal
from db.models import Prediction, Weather
from datetime import datetime, timezone
import pandas as pd

def test_prediction_comfort_integration():
    """Test that predictions now include comfort data directly."""
    
    print("🧪 Testing prediction-comfort integration...")
    
    with SessionLocal() as ses:
        # Check current state
        total_predictions = ses.query(Prediction).count()
        comfort_predictions = ses.query(Prediction).filter(Prediction.occupant_profile.is_not(None)).count()
        
        print(f"📊 Current database state:")
        print(f"  - Total predictions: {total_predictions}")
        print(f"  - Predictions with comfort data: {comfort_predictions}")
        
        # Check if we have weather data for testing
        weather_count = ses.query(Weather).count()
        print(f"  - Weather records available: {weather_count}")
        
        if weather_count > 0:
            # Get a sample weather record
            sample_weather = ses.query(Weather).first()
            print(f"  - Sample weather record: ID {sample_weather.weather_id}, sensor {sample_weather.sensor_id}")
            
            # Check if we have any predictions with this weather_id
            existing_pred = ses.query(Prediction).filter(Prediction.weather_id == sample_weather.weather_id).first()
            if existing_pred:
                print(f"  - Found existing prediction for weather_id {sample_weather.weather_id}")
                print(f"    - Occupant profile: {existing_pred.occupant_profile}")
                print(f"    - PMV: {existing_pred.pmv}")
                print(f"    - Overall comfort: {existing_pred.overall_comfort}")
                print(f"    - Overall comfort class: {existing_pred.overall_comfort_class}")
            else:
                print(f"  - No existing prediction found for weather_id {sample_weather.weather_id}")
        
        # Check latest prediction
        latest_pred = ses.query(Prediction).order_by(Prediction.predicted_at.desc()).first()
        if latest_pred:
            print(f"📊 Latest prediction:")
            print(f"  - ID: {latest_pred.prediction_id}")
            print(f"  - Predicted at: {latest_pred.predicted_at}")
            print(f"  - Occupant profile: {latest_pred.occupant_profile}")
            print(f"  - Has comfort data: {'Yes' if latest_pred.occupant_profile else 'No'}")
            if latest_pred.occupant_profile:
                print(f"  - Overall comfort: {latest_pred.overall_comfort}")
                print(f"  - Thermal class: {latest_pred.thermal_comfort_class}")
                print(f"  - Visual class: {latest_pred.visual_comfort_class}")
                print(f"  - Acoustic class: {latest_pred.acoustic_comfort_class}")
        
        print("\n✅ Database schema check completed!")
        print("Ready to test new prediction functionality in the dashboard.")

if __name__ == "__main__":
    test_prediction_comfort_integration()
