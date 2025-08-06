#!/usr/bin/env python3
"""
Analyze database duplicates to identify data quality issues.
This script checks for duplicate records in the Energy Comfortness Tool database.
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
from sqlalchemy import text

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

from db.session import SessionLocal
from db.models import Measurement, Weather, Prediction

def analyze_duplicates():
    """Analyze duplicate records in all tables."""
    print("🔍 Analyzing database duplicates...")
    print("=" * 60)
    
    with SessionLocal() as ses:
        # Analyze Measurements table
        print("\n📊 MEASUREMENTS TABLE")
        print("-" * 30)
        
        total_measurements = ses.query(Measurement).count()
        print(f"Total measurements: {total_measurements:,}")
        
        # Check for duplicates by (sensor_id, time_end)
        duplicate_measurements = ses.execute(text("""
            SELECT sensor_id, time_end, COUNT(*) as count
            FROM measurements 
            GROUP BY sensor_id, time_end 
            HAVING COUNT(*) > 1
            ORDER BY count DESC
            LIMIT 10
        """)).fetchall()
        
        if duplicate_measurements:
            print(f"\n⚠️  Found {len(duplicate_measurements)} duplicate (sensor_id, time_end) combinations:")
            for row in duplicate_measurements:
                print(f"  • Sensor: {row.sensor_id}, Time: {row.time_end}, Duplicates: {row.count}")
        else:
            print("✅ No duplicates found in measurements")
        
        # Sensor summary
        sensor_counts = ses.execute(text("""
            SELECT sensor_id, COUNT(*) as count, 
                   MIN(time_end) as min_time, 
                   MAX(time_end) as max_time
            FROM measurements 
            GROUP BY sensor_id 
            ORDER BY count DESC
        """)).fetchall()
        
        print(f"\n📈 Records per sensor:")
        for row in sensor_counts:
            duration_days = (row.max_time - row.min_time).days + 1
            expected_hourly = duration_days * 24
            print(f"  • {row.sensor_id}: {row.count:,} records ({row.min_time} to {row.max_time})")
            print(f"    Expected (hourly): ~{expected_hourly:,}, Ratio: {row.count/expected_hourly:.1f}x")
        
        # Analyze Weather table
        print("\n🌤️  WEATHER TABLE")
        print("-" * 30)
        
        total_weather = ses.query(Weather).count()
        print(f"Total weather records: {total_weather:,}")
        
        # Check for duplicates by (sensor_id, time_end)
        duplicate_weather = ses.execute(text("""
            SELECT sensor_id, time_end, COUNT(*) as count
            FROM weather 
            GROUP BY sensor_id, time_end 
            HAVING COUNT(*) > 1
            ORDER BY count DESC
            LIMIT 10
        """)).fetchall()
        
        if duplicate_weather:
            print(f"\n⚠️  Found {len(duplicate_weather)} duplicate (sensor_id, time_end) combinations:")
            for row in duplicate_weather:
                print(f"  • Sensor: {row.sensor_id}, Time: {row.time_end}, Duplicates: {row.count}")
        else:
            print("✅ No duplicates found in weather data")
        
        # Weather sensor summary
        weather_sensor_counts = ses.execute(text("""
            SELECT sensor_id, COUNT(*) as count, 
                   MIN(time_end) as min_time, 
                   MAX(time_end) as max_time
            FROM weather 
            GROUP BY sensor_id 
            ORDER BY count DESC
        """)).fetchall()
        
        print(f"\n📈 Weather records per sensor:")
        for row in weather_sensor_counts:
            duration_days = (row.max_time - row.min_time).days + 1
            expected_hourly = duration_days * 24
            print(f"  • {row.sensor_id}: {row.count:,} records ({row.min_time} to {row.max_time})")
            print(f"    Expected (hourly): ~{expected_hourly:,}, Ratio: {row.count/expected_hourly:.1f}x")
        
        # Analyze Predictions table
        print("\n🔮 PREDICTIONS TABLE")
        print("-" * 30)
        
        total_predictions = ses.query(Prediction).count()
        print(f"Total prediction records: {total_predictions:,}")
        
        # Check for duplicates by weather_id (should be unique)
        duplicate_predictions = ses.execute(text("""
            SELECT weather_id, COUNT(*) as count
            FROM predictions 
            GROUP BY weather_id 
            HAVING COUNT(*) > 1
            ORDER BY count DESC
            LIMIT 10
        """)).fetchall()
        
        if duplicate_predictions:
            print(f"\n⚠️  Found {len(duplicate_predictions)} duplicate weather_id references:")
            for row in duplicate_predictions:
                print(f"  • Weather ID: {row.weather_id}, Duplicates: {row.count}")
        else:
            print("✅ No duplicates found in predictions (by weather_id)")
        
        # Check predictions by sensor/time through JOIN
        prediction_sensor_counts = ses.execute(text("""
            SELECT w.sensor_id, COUNT(*) as count,
                   MIN(w.time_end) as min_time,
                   MAX(w.time_end) as max_time
            FROM predictions p
            JOIN weather w ON p.weather_id = w.weather_id
            GROUP BY w.sensor_id
            ORDER BY count DESC
        """)).fetchall()
        
        print(f"\n📈 Prediction records per sensor:")
        for row in prediction_sensor_counts:
            duration_days = (row.max_time - row.min_time).days + 1
            expected_hourly = duration_days * 24
            print(f"  • {row.sensor_id}: {row.count:,} predictions ({row.min_time} to {row.max_time})")
            print(f"    Expected (hourly): ~{expected_hourly:,}, Ratio: {row.count/expected_hourly:.1f}x")
        
        # Summary
        print("\n📋 SUMMARY")
        print("-" * 30)
        print(f"Total measurements: {total_measurements:,}")
        print(f"Total weather records: {total_weather:,}")
        print(f"Total predictions: {total_predictions:,}")
        print(f"Grand total: {total_measurements + total_weather + total_predictions:,}")
        
        if total_predictions > 50000:
            print(f"\n⚠️  ALERT: {total_predictions:,} prediction records is excessive!")
            print("   Expected: ~8,760 per sensor per year (hourly data)")
            print("   Recommendation: Clean up duplicates immediately")

def suggest_cleanup():
    """Suggest cleanup strategies."""
    print("\n🧹 CLEANUP RECOMMENDATIONS")
    print("=" * 60)
    print("""
1. Remove duplicate measurements:
   DELETE FROM measurements 
   WHERE measurement_id NOT IN (
       SELECT MIN(measurement_id) 
       FROM measurements 
       GROUP BY sensor_id, time_end
   );

2. Remove duplicate weather records:
   DELETE FROM weather 
   WHERE weather_id NOT IN (
       SELECT MIN(weather_id) 
       FROM weather 
       GROUP BY sensor_id, time_end
   );

3. Remove duplicate predictions (keep most recent):
   DELETE FROM predictions 
   WHERE prediction_id NOT IN (
       SELECT MAX(prediction_id) 
       FROM predictions 
       GROUP BY weather_id
   );

4. Consider creating unique constraints:
   ALTER TABLE measurements ADD CONSTRAINT unique_sensor_time 
   UNIQUE (sensor_id, time_end);
   
   ALTER TABLE weather ADD CONSTRAINT unique_weather_sensor_time 
   UNIQUE (sensor_id, time_end);
""")

if __name__ == "__main__":
    try:
        analyze_duplicates()
        suggest_cleanup()
    except Exception as e:
        print(f"❌ Error analyzing duplicates: {e}")
        import traceback
        traceback.print_exc()
