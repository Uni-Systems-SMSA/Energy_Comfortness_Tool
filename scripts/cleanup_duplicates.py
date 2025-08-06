#!/usr/bin/env python
"""
Database Cleanup Script - Remove Duplicate Records
================================================

This script removes duplicate records from the database tables:
- Predictions: Remove duplicates by weather_id (keep most recent)
- Weather: Remove duplicates by sensor_id + time_end (keep first)
- Measurements: Remove duplicates by sensor_id + time_end (keep first)

Run with --dry-run first to see what would be deleted.
Run with --execute to actually perform the cleanup.
"""

import sys
import argparse
from datetime import datetime
from sqlalchemy import text
from db.session import SessionLocal
from db.models import Measurement, Weather, Prediction

def analyze_before_cleanup(ses):
    """Show current state before cleanup."""
    print("📊 CURRENT DATABASE STATE")
    print("=" * 50)
    
    # Count current records
    measurements_count = ses.query(Measurement).count()
    weather_count = ses.query(Weather).count()
    predictions_count = ses.query(Prediction).count()
    
    print(f"Measurements: {measurements_count:,}")
    print(f"Weather: {weather_count:,}")
    print(f"Predictions: {predictions_count:,}")
    print(f"Total: {measurements_count + weather_count + predictions_count:,}")
    
    # Count duplicates in predictions (the main problem)
    duplicate_predictions = ses.execute(text("""
        SELECT COUNT(*) as duplicate_count
        FROM predictions p1
        WHERE EXISTS (
            SELECT 1 FROM predictions p2 
            WHERE p2.weather_id = p1.weather_id 
            AND p2.prediction_id > p1.prediction_id
        )
    """)).scalar()
    
    print(f"\nDuplicate predictions to remove: {duplicate_predictions:,}")
    print(f"Expected predictions after cleanup: {predictions_count - duplicate_predictions:,}")
    
    return {
        'measurements': measurements_count,
        'weather': weather_count,
        'predictions': predictions_count,
        'duplicates': duplicate_predictions
    }

def cleanup_predictions(ses, dry_run=True):
    """Remove duplicate predictions, keeping the most recent for each weather_id."""
    print("\n🔮 CLEANING PREDICTIONS TABLE")
    print("-" * 40)
    
    if dry_run:
        # Count what would be deleted
        count_query = text("""
            SELECT COUNT(*) 
            FROM predictions p1
            WHERE EXISTS (
                SELECT 1 FROM predictions p2 
                WHERE p2.weather_id = p1.weather_id 
                AND p2.prediction_id > p1.prediction_id
            )
        """)
        count = ses.execute(count_query).scalar()
        print(f"DRY RUN: Would delete {count:,} duplicate prediction records")
        return count
    else:
        # Actually delete duplicates (keep the one with highest prediction_id for each weather_id)
        delete_query = text("""
            DELETE FROM predictions 
            WHERE prediction_id NOT IN (
                SELECT MAX(prediction_id)
                FROM predictions
                GROUP BY weather_id
            )
        """)
        result = ses.execute(delete_query)
        deleted_count = result.rowcount
        print(f"✅ Deleted {deleted_count:,} duplicate prediction records")
        return deleted_count

def cleanup_weather(ses, dry_run=True):
    """Remove duplicate weather records, keeping the first for each sensor_id + time_end."""
    print("\n🌤️  CLEANING WEATHER TABLE")
    print("-" * 40)
    
    if dry_run:
        # Count what would be deleted
        count_query = text("""
            SELECT COUNT(*) 
            FROM weather w1
            WHERE EXISTS (
                SELECT 1 FROM weather w2 
                WHERE w2.sensor_id = w1.sensor_id 
                AND w2.time_end = w1.time_end 
                AND w2.weather_id < w1.weather_id
            )
        """)
        count = ses.execute(count_query).scalar()
        print(f"DRY RUN: Would delete {count:,} duplicate weather records")
        return count
    else:
        # Actually delete duplicates (keep the one with lowest weather_id for each sensor+time)
        delete_query = text("""
            DELETE FROM weather 
            WHERE weather_id NOT IN (
                SELECT MIN(weather_id)
                FROM weather
                GROUP BY sensor_id, time_end
            )
        """)
        result = ses.execute(delete_query)
        deleted_count = result.rowcount
        print(f"✅ Deleted {deleted_count:,} duplicate weather records")
        return deleted_count

def cleanup_measurements(ses, dry_run=True):
    """Remove duplicate measurements, keeping the first for each sensor_id + time_end."""
    print("\n📊 CLEANING MEASUREMENTS TABLE")
    print("-" * 40)
    
    if dry_run:
        # Count what would be deleted
        count_query = text("""
            SELECT COUNT(*) 
            FROM measurements m1
            WHERE EXISTS (
                SELECT 1 FROM measurements m2 
                WHERE m2.sensor_id = m1.sensor_id 
                AND m2.time_end = m1.time_end 
                AND m2.measurement_id < m1.measurement_id
            )
        """)
        count = ses.execute(count_query).scalar()
        print(f"DRY RUN: Would delete {count:,} duplicate measurement records")
        return count
    else:
        # Actually delete duplicates (keep the one with lowest measurement_id for each sensor+time)
        delete_query = text("""
            DELETE FROM measurements 
            WHERE measurement_id NOT IN (
                SELECT MIN(measurement_id)
                FROM measurements
                GROUP BY sensor_id, time_end
            )
        """)
        result = ses.execute(delete_query)
        deleted_count = result.rowcount
        print(f"✅ Deleted {deleted_count:,} duplicate measurement records")
        return deleted_count

def add_unique_constraints(ses, dry_run=True):
    """Add unique constraints to prevent future duplicates."""
    print("\n🔒 ADDING UNIQUE CONSTRAINTS")
    print("-" * 40)
    
    constraints = [
        ("measurements", "unique_measurement_sensor_time", "sensor_id, time_end"),
        ("weather", "unique_weather_sensor_time", "sensor_id, time_end"),
        ("predictions", "unique_prediction_weather", "weather_id")
    ]
    
    for table, constraint_name, columns in constraints:
        if dry_run:
            print(f"DRY RUN: Would add constraint {constraint_name} to {table}")
        else:
            try:
                constraint_sql = text(f"""
                    ALTER TABLE {table} 
                    ADD CONSTRAINT {constraint_name} 
                    UNIQUE ({columns})
                """)
                ses.execute(constraint_sql)
                print(f"✅ Added constraint {constraint_name} to {table}")
            except Exception as e:
                print(f"⚠️  Could not add constraint {constraint_name}: {e}")

def main():
    parser = argparse.ArgumentParser(description='Clean up duplicate database records')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show what would be deleted without actually deleting')
    parser.add_argument('--execute', action='store_true',
                       help='Actually perform the cleanup')
    parser.add_argument('--add-constraints', action='store_true',
                       help='Add unique constraints after cleanup')
    
    args = parser.parse_args()
    
    if not args.dry_run and not args.execute:
        print("❌ Error: Must specify either --dry-run or --execute")
        sys.exit(1)
    
    if args.execute and args.dry_run:
        print("❌ Error: Cannot specify both --dry-run and --execute")
        sys.exit(1)
    
    dry_run = args.dry_run
    
    print(f"🧹 DATABASE CLEANUP TOOL")
    print(f"{'='*50}")
    print(f"Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
    print(f"Time: {datetime.now()}")
    
    with SessionLocal() as ses:
        try:
            # Analyze current state
            initial_state = analyze_before_cleanup(ses)
            
            # Clean up each table
            deleted_measurements = cleanup_measurements(ses, dry_run)
            deleted_weather = cleanup_weather(ses, dry_run) 
            deleted_predictions = cleanup_predictions(ses, dry_run)
            
            # Add constraints if requested
            if args.add_constraints:
                add_unique_constraints(ses, dry_run)
            
            # Summary
            print(f"\n📋 CLEANUP SUMMARY")
            print("-" * 30)
            print(f"Measurements deleted: {deleted_measurements:,}")
            print(f"Weather deleted: {deleted_weather:,}")
            print(f"Predictions deleted: {deleted_predictions:,}")
            print(f"Total deleted: {deleted_measurements + deleted_weather + deleted_predictions:,}")
            
            if not dry_run:
                ses.commit()
                print(f"\n✅ Changes committed to database")
                
                # Show final state
                final_measurements = ses.query(Measurement).count()
                final_weather = ses.query(Weather).count()
                final_predictions = ses.query(Prediction).count()
                
                print(f"\n📊 FINAL STATE")
                print(f"Measurements: {final_measurements:,} (was {initial_state['measurements']:,})")
                print(f"Weather: {final_weather:,} (was {initial_state['weather']:,})")
                print(f"Predictions: {final_predictions:,} (was {initial_state['predictions']:,})")
                print(f"Total: {final_measurements + final_weather + final_predictions:,}")
            else:
                print(f"\n💡 Run with --execute to perform actual cleanup")
            
        except Exception as e:
            print(f"❌ Error during cleanup: {e}")
            if not dry_run:
                ses.rollback()
                print("🔄 Transaction rolled back")
            raise

if __name__ == "__main__":
    main()
