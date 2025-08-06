#!/usr/bin/env python3

from db.session import SessionLocal
from db.models import Prediction, Weather
from sqlalchemy import func, text

def analyze_predictions():
    """Analyze prediction data volume and distribution"""
    
    ses = SessionLocal()
    
    try:
        print("=== PREDICTION ANALYSIS ===")
        
        # Total count
        total = ses.query(Prediction).count()
        print(f"Total predictions: {total}")
        print()
        
        # Date range
        print("Date range:")
        result = ses.execute(text("SELECT MIN(predicted_at), MAX(predicted_at) FROM predictions"))
        min_date, max_date = result.fetchone()
        print(f"From: {min_date}")
        print(f"To: {max_date}")
        print()
        
        # Predictions per day (last 10 days)
        print("Recent predictions per day:")
        result = ses.execute(text("""
            SELECT DATE(predicted_at) as pred_date, COUNT(*) as count 
            FROM predictions 
            GROUP BY DATE(predicted_at) 
            ORDER BY pred_date DESC 
            LIMIT 10
        """))
        for row in result.fetchall():
            print(f"  {row[0]}: {row[1]} predictions")
        print()
        
        # Check for duplicates by weather_id
        print("Checking for potential duplicates:")
        result = ses.execute(text("""
            SELECT weather_id, COUNT(*) as count 
            FROM predictions 
            GROUP BY weather_id 
            HAVING COUNT(*) > 1 
            ORDER BY count DESC 
            LIMIT 10
        """))
        duplicates = result.fetchall()
        if duplicates:
            print("Found weather_ids with multiple predictions:")
            for row in duplicates:
                print(f"  weather_id {row[0]}: {row[1]} predictions")
        else:
            print("No duplicate weather_ids found (good!)")
        print()
        
        # Sample of recent predictions
        print("Sample of recent predictions:")
        result = ses.execute(text("""
            SELECT prediction_id, weather_id, predicted_at, predicted_temperature_c, predicted_energy_kwh
            FROM predictions 
            ORDER BY predicted_at DESC 
            LIMIT 5
        """))
        for row in result.fetchall():
            print(f"  ID: {row[0]}, weather_id: {row[1]}, date: {row[2]}, temp: {row[3]}°C, energy: {row[4]}kWh")
        print()
        
        # Weather data count for comparison
        weather_count = ses.query(Weather).count()
        print(f"Total weather records: {weather_count}")
        
        # Check the ratio
        if weather_count > 0:
            ratio = total / weather_count
            print(f"Predictions per weather record: {ratio:.2f}")
            if ratio > 1.5:
                print("⚠️  WARNING: More predictions than weather records - possible duplication!")
            else:
                print("✅ Prediction count looks reasonable")
        
    except Exception as e:
        print(f"Error during analysis: {e}")
        import traceback
        traceback.print_exc()
    finally:
        ses.close()

if __name__ == "__main__":
    analyze_predictions()
