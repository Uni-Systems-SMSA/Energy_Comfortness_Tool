#!/usr/bin/env python3
"""
Debug prediction saving issue
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from db.session import SessionLocal
from db.models import TrainedModel, Weather, Prediction
from sqlalchemy import text
from datetime import datetime, timezone

def debug_prediction_issue():
    """Debug why predictions aren't being saved"""
    
    with SessionLocal() as session:
        # Check if we have the prerequisites
        model_count = session.query(TrainedModel).count()
        weather_count = session.query(Weather).count()
        
        print(f"📊 Prerequisites:")
        print(f"  - Trained models: {model_count}")
        print(f"  - Weather records: {weather_count}")
        
        if model_count == 0:
            print("❌ No trained models - need to train first")
            return
            
        if weather_count == 0:
            print("❌ No weather data - need weather data first")
            return
        
        # Check recent weather data
        result = session.execute(text(
            "SELECT sensor_id, COUNT(*) as count, MIN(time_end) as earliest, MAX(time_end) as latest "
            "FROM weather GROUP BY sensor_id ORDER BY sensor_id"
        ))
        
        print(f"\n📋 Weather data by sensor:")
        for row in result.fetchall():
            print(f"  - {row[0]}: {row[1]} records ({row[2]} to {row[3]})")
        
        # Check trained model targets
        models = session.query(TrainedModel).all()
        print(f"\n🤖 Available models:")
        for model in models:
            print(f"  - {model.target} (v{model.version}) - {model.algorithm}")
        
        # Try a simple prediction insert test
        print(f"\n🧪 Testing simple prediction insert...")
        
        # Get first weather record and first model
        first_weather = session.query(Weather).first()
        first_model = session.query(TrainedModel).first()
        
        if first_weather and first_model:
            test_prediction = Prediction(
                model_id=first_model.model_id,
                weather_id=first_weather.weather_id,
                predicted_at=datetime.now(timezone.utc),
                predicted_temperature_c=22.5  # Test value
            )
            
            try:
                session.add(test_prediction)
                session.commit()
                print("  ✅ Test prediction insert successful")
                
                # Clean up test record
                session.delete(test_prediction)
                session.commit()
                print("  ✅ Test prediction cleaned up")
                
            except Exception as e:
                print(f"  ❌ Test prediction failed: {e}")
                session.rollback()
        else:
            print("  ❌ No weather or model data for test")

if __name__ == "__main__":
    debug_prediction_issue()
