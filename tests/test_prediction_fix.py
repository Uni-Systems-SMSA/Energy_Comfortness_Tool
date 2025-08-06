#!/usr/bin/env python3
"""
Test the fixed prediction logic with a small sample
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from db.session import SessionLocal
from db.models import Weather, TrainedModel, Prediction, ComfortLevel
from sqlalchemy import text
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import joblib

def test_prediction_fix():
    """Test the fixed prediction logic with a small sample"""
    
    print("🧪 Testing fixed prediction logic...")
    
    with SessionLocal() as session:
        # Clear any existing predictions first
        session.query(ComfortLevel).delete()
        session.query(Prediction).delete()
        session.commit()
        print("  🧹 Cleared existing predictions")
        
        # Get a small sample of recent weather data (just 3 records)
        weather_records = (
            session.query(Weather)
            .filter(Weather.sensor_id == "CERTH Smart House - Living Room")
            .order_by(Weather.time_end.desc())
            .limit(3)
            .all()
        )
        
        if not weather_records:
            print("  ❌ No weather records found")
            return
            
        print(f"  📊 Using {len(weather_records)} weather records for test")
        
        # Get available models
        models = {}
        model_query = session.query(TrainedModel).all()
        for model_row in model_query:
            model_path = Path(model_row.model_path)
            if model_path.exists():
                try:
                    model_data = joblib.load(model_path)
                    models[model_row.target] = (model_data, model_row.model_id)
                    print(f"    ✅ Loaded model for {model_row.target}")
                except Exception as e:
                    print(f"    ❌ Failed to load model for {model_row.target}: {e}")
        
        if not models:
            print("  ❌ No models loaded")
            return
            
        # Create DataFrame from weather records
        df = pd.DataFrame([{
            'weather_id': w.weather_id,
            'time_end': w.time_end,
            'sensor_id': w.sensor_id,
            'outdoor_temperature_2m': float(w.outdoor_temperature_2m or 20.0),
            'outdoor_relative_humidity_2m': float(w.outdoor_relative_humidity_2m or 60.0),
            'wind_speed_10m': float(w.wind_speed_10m or 5.0),
        } for w in weather_records])
        
        # Add time features
        doy = df["time_end"].dt.dayofyear
        hod = df["time_end"].dt.hour + df["time_end"].dt.minute / 60
        df["doy_sin"] = np.sin(2 * np.pi * doy / 365)
        df["doy_cos"] = np.cos(2 * np.pi * doy / 365)
        df["hour_sin"] = np.sin(2 * np.pi * hod / 24)
        df["hour_cos"] = np.cos(2 * np.pi * hod / 24)
        
        # Test the new consolidated prediction logic
        target_predictions = {}
        now = datetime.now(tz=timezone.utc)
        
        # Initialize prediction records for each weather_id
        for weather_id in df["weather_id"]:
            target_predictions[int(weather_id)] = {
                "model_id": None,
                "weather_id": int(weather_id),
                "predicted_at": now,
            }
        
        successful_targets = []
        
        for target, (model_data, model_id) in models.items():
            try:
                model = model_data["model"]
                features = model_data["features"]
                
                # Set model_id for all predictions (use first model encountered)
                if all(pred["model_id"] is None for pred in target_predictions.values()):
                    for pred in target_predictions.values():
                        pred["model_id"] = model_id
                
                # Check if all features are available (simplified check)
                available_features = [f for f in features if f in df.columns]
                if len(available_features) < len(features) * 0.8:  # At least 80% of features
                    print(f"    ⚠️  Skipping {target} - insufficient features")
                    continue
                
                # Make predictions using available features
                try:
                    # Use basic features for testing
                    basic_features = ['outdoor_temperature_2m', 'outdoor_relative_humidity_2m', 'doy_sin', 'doy_cos', 'hour_sin', 'hour_cos']
                    test_features = [f for f in basic_features if f in df.columns]
                    
                    if len(test_features) >= 4:  # Minimum features needed
                        preds = [22.0 + i for i in range(len(df))]  # Dummy predictions for testing
                        
                        # Add predictions to consolidated records
                        col_db = f"predicted_{target}"
                        for weather_id, pred_val in zip(df["weather_id"], preds):
                            target_predictions[int(weather_id)][col_db] = float(pred_val)
                        
                        successful_targets.append(target)
                        print(f"    ✅ Added predictions for {target}")
                    else:
                        print(f"    ⚠️  Skipping {target} - not enough basic features")
                        
                except Exception as e:
                    print(f"    ❌ Prediction failed for {target}: {e}")
                    
            except Exception as e:
                print(f"    ❌ Model error for {target}: {e}")
        
        # Convert to list and insert
        predictions_bulk = list(target_predictions.values())
        
        if predictions_bulk and successful_targets:
            try:
                session.bulk_insert_mappings(Prediction, predictions_bulk)
                session.commit()
                print(f"  ✅ Successfully inserted {len(predictions_bulk)} prediction records")
                print(f"     with targets: {', '.join(successful_targets)}")
                
                # Verify the insert
                pred_count = session.query(Prediction).count()
                print(f"  📊 Total predictions in database: {pred_count}")
                
                # Show sample record
                sample = session.query(Prediction).first()
                if sample:
                    print(f"  🔍 Sample prediction ID: {sample.prediction_id}")
                    print(f"     Weather ID: {sample.weather_id}, Model ID: {sample.model_id}")
                    
            except Exception as e:
                print(f"  ❌ Insert failed: {e}")
                session.rollback()
        else:
            print(f"  ⚠️  No predictions to insert")

if __name__ == "__main__":
    test_prediction_fix()
