#!/usr/bin/env python3
"""
Test script to generate sample prediction and comfort level data.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from db.session import SessionLocal
from db.models import Weather, Prediction, ComfortLevel
from ece.helpers import (
    pmv_ppd, classify_thermal_category, classify_visual_category,
    classify_acoustic_category, classify_co2_category, yong_score, annoyance_level
)

def create_sample_data():
    """Create sample weather, prediction and comfort level data for testing"""
    
    print("🔄 Creating sample data...")
    
    with SessionLocal() as session:
        # Create sample weather data
        base_time = datetime(2024, 6, 1, 0, 0, 0)
        weather_records = []
        
        for i in range(24 * 7):  # 1 week of hourly data
            weather = Weather(
                time_end=base_time + timedelta(hours=i),
                sensor_id="CERTH Smart House - Living Room",
                outdoor_temperature_2m=20.0 + (i % 24) * 0.5,  # Vary by hour
                outdoor_relative_humidity_2m=60.0 + (i % 12) * 2,
                outdoor_pressure_msl=1013.25,
                outdoor_windspeed_10m=5.0,
                fetched_at=datetime.now()
            )
            session.add(weather)
            weather_records.append(weather)
        
        session.flush()  # Get weather IDs
        
        # Create sample predictions
        predictions = []
        for weather in weather_records:
            prediction = Prediction(
                model_id=1,  # Assume we have a model with ID 1
                weather_id=weather.weather_id,
                predicted_at=datetime.now(),
                predicted_temperature_c=22.0 + (weather.weather_id % 10),
                predicted_rh_percent=50.0 + (weather.weather_id % 20),
                predicted_luminance_lux=300.0 + (weather.weather_id % 200),
                predicted_average_noise_db=35.0 + (weather.weather_id % 15),
                predicted_co2_ppm=400.0 + (weather.weather_id % 200),
                predicted_co_ppm=1.0 + (weather.weather_id % 5),
                predicted_tvoc_ppb=50.0 + (weather.weather_id % 50),
                predicted_pm2_5_ugm3=5.0 + (weather.weather_id % 10),
                predicted_pm10_ugm3=10.0 + (weather.weather_id % 15)
            )
            session.add(prediction)
            predictions.append(prediction)
        
        session.flush()  # Get prediction IDs
        
        # Create comfort levels for different occupant profiles
        profiles = [
            {"name": "young", "age": 25},
            {"name": "middle_aged", "age": 45},
            {"name": "elderly", "age": 65},
            {"name": "default", "age": 35}
        ]
        
        comfort_levels = []
        for prediction in predictions:
            for profile in profiles:
                # Calculate comfort metrics
                temp = float(prediction.predicted_temperature_c)
                rh = float(prediction.predicted_rh_percent)
                lux = float(prediction.predicted_luminance_lux)
                noise_db = float(prediction.predicted_average_noise_db)
                age = profile["age"]
                
                # PMV/PPD calculation
                pmv_val, ppd_val = pmv_ppd(tdb=temp, rh=rh)
                if hasattr(pmv_val, '__len__'):
                    pmv_val = pmv_val[0] if len(pmv_val) > 0 else 0
                    ppd_val = ppd_val[0] if len(ppd_val) > 0 else 0
                
                # Comfort classifications
                thermal_class = classify_thermal_category([pmv_val], [ppd_val])[0]
                visual_class = classify_visual_category([lux])[0]
                acoustic_class = classify_acoustic_category([noise_db])[0]
                co2_class = classify_co2_category([prediction.predicted_co2_ppm])[0]
                
                # Age-dependent metrics
                vis_score = yong_score(lux)
                if hasattr(vis_score, '__len__'):
                    vis_score = vis_score[0] if len(vis_score) > 0 else 2.5
                
                annoy_level = annoyance_level(noise_db, age)
                if annoy_level is None:
                    annoy_level = 1.0
                
                # Overall comfort calculation
                class_to_score = {'A': 4, 'B': 3, 'C': 2, 'D': 1, 'NC': 0}
                scores = [
                    class_to_score.get(thermal_class, 0) * 0.3,
                    class_to_score.get(visual_class, 0) * 0.2,
                    class_to_score.get(acoustic_class, 0) * 0.2,
                    class_to_score.get(co2_class, 0) * 0.3
                ]
                overall_score = sum(scores)
                
                if overall_score >= 3.5:
                    overall_class = 'A'
                elif overall_score >= 2.5:
                    overall_class = 'B'
                elif overall_score >= 1.5:
                    overall_class = 'C'
                else:
                    overall_class = 'D'
                
                comfort_level = ComfortLevel(
                    prediction_id=prediction.prediction_id,
                    occupant_profile=profile["name"],
                    estimated_at=datetime.now(),
                    pmv=pmv_val,
                    ppd=ppd_val,
                    thermal_comfort_class=thermal_class,
                    visual_comfort_class=visual_class,
                    acoustic_comfort_class=acoustic_class,
                    co2_comfort_class=co2_class,
                    visual_comfort_score=vis_score,
                    acoustic_annoyance_level=annoy_level,
                    overall_comfort=overall_score,
                    overall_comfort_class=overall_class,
                    predicted_co2_ppm=prediction.predicted_co2_ppm,
                    predicted_rh_percent=prediction.predicted_rh_percent,
                    predicted_luminance_lux=prediction.predicted_luminance_lux,
                    predicted_average_noise_db=prediction.predicted_average_noise_db
                )
                session.add(comfort_level)
                comfort_levels.append(comfort_level)
        
        session.commit()
        
        print(f"✅ Created {len(weather_records)} weather records")
        print(f"✅ Created {len(predictions)} prediction records")
        print(f"✅ Created {len(comfort_levels)} comfort level records")
        print(f"📊 Profiles: {[p['name'] for p in profiles]}")
        print(f"📅 Date range: {weather_records[0].time_end} to {weather_records[-1].time_end}")

if __name__ == "__main__":
    create_sample_data()
