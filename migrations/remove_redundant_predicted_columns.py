#!/usr/bin/env python3
"""
Migration to remove redundant predicted_* columns from ComfortLevel table.

The predicted values are already accessible via the prediction_id foreign key,
making these duplicate columns unnecessary and potentially inconsistent.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from db.session import SessionLocal
from sqlalchemy import text

def remove_redundant_predicted_columns():
    """
    Remove redundant predicted_* columns from comfort_levels table.
    
    These columns are redundant because:
    1. All predicted values are already stored in the predictions table
    2. ComfortLevel has prediction_id foreign key to access them
    3. Duplication can lead to inconsistency
    4. Missing predicted_temperature_c was never added anyway
    """
    
    print("🔧 Removing redundant predicted_* columns from comfort_levels table...")
    
    with SessionLocal() as session:
        # List of redundant columns to remove
        redundant_columns = [
            'predicted_co2_ppm',
            'predicted_rh_percent', 
            'predicted_luminance_lux',
            'predicted_average_noise_db',
            'predicted_pm2_5_ugm3',
            'predicted_tvoc_ppb',
            'predicted_peak_db',
            'predicted_co_ppm',
            'predicted_pm10_ugm3'
        ]
        
        # Check which columns actually exist
        result = session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'comfort_levels' AND column_name LIKE 'predicted_%'"
        ))
        existing_predicted_cols = [row[0] for row in result.fetchall()]
        
        print(f"📋 Found predicted_* columns: {existing_predicted_cols}")
        
        # Remove each redundant column
        removed_count = 0
        for column in redundant_columns:
            if column in existing_predicted_cols:
                try:
                    session.execute(text(f"ALTER TABLE comfort_levels DROP COLUMN {column}"))
                    print(f"  ✅ Removed column: {column}")
                    removed_count += 1
                except Exception as e:
                    print(f"  ❌ Failed to remove {column}: {e}")
        
        if removed_count > 0:
            session.commit()
            print(f"\n🎉 Successfully removed {removed_count} redundant columns!")
        else:
            print("\n📝 No redundant columns found to remove.")
        
        # Show the cleaned table structure
        result = session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'comfort_levels' ORDER BY ordinal_position"
        ))
        remaining_columns = [row[0] for row in result.fetchall()]
        
        print(f"\n📊 Final ComfortLevel table structure:")
        for col in remaining_columns:
            print(f"  - {col}")

def verify_database_integrity():
    """Verify that the migration didn't break anything"""
    
    print("\n🔍 Verifying database integrity...")
    
    with SessionLocal() as session:
        # Check that foreign key relationship still works
        result = session.execute(text(
            "SELECT cl.comfort_id, cl.prediction_id, p.predicted_temperature_c "
            "FROM comfort_levels cl "
            "JOIN predictions p ON cl.prediction_id = p.prediction_id "
            "LIMIT 1"
        ))
        
        test_row = result.fetchone()
        if test_row:
            print("  ✅ Foreign key relationship working - can access prediction data")
        else:
            print("  📝 No data to test relationship (tables empty)")
        
        # Check table structure
        result = session.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name = 'comfort_levels'"
        ))
        col_count = result.scalar()
        print(f"  ✅ ComfortLevel table has {col_count} columns")

if __name__ == "__main__":
    remove_redundant_predicted_columns()
    verify_database_integrity()
    print("\n✨ Migration completed successfully!")
