#!/usr/bin/env python3
"""
Migration to remove redundant comfort columns from predictions table.

Comfort data should only be stored in comfort_levels table with occupant profiles.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from db.session import SessionLocal
from sqlalchemy import text

def remove_comfort_columns_from_predictions():
    """Remove redundant comfort columns from predictions table"""
    
    print("🔧 Removing redundant comfort columns from predictions table...")
    
    with SessionLocal() as session:
        # List of comfort columns to remove from predictions table
        comfort_columns = [
            'pmv_value',
            'ppd_value', 
            'thermal_comfort_class',
            'visual_comfort_class',
            'acoustic_comfort_class',
            'visual_comfort_score',
            'acoustic_annoyance_level',
            'co2_comfort_class',
            'co_comfort_class',
            'tvoc_comfort_class',
            'pm25_comfort_class',
            'pm10_comfort_class',
            'overall_comfort',
            'overall_comfort_class'
        ]
        
        # Check which columns actually exist
        result = session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'predictions' AND (column_name LIKE '%comfort%' OR column_name LIKE 'pmv%' OR column_name LIKE 'ppd%' OR column_name LIKE '%_class')"
        ))
        existing_comfort_cols = [row[0] for row in result.fetchall()]
        
        print(f"📋 Found comfort columns in predictions: {existing_comfort_cols}")
        
        # Remove each comfort column
        removed_count = 0
        for column in comfort_columns:
            if column in existing_comfort_cols:
                try:
                    session.execute(text(f"ALTER TABLE predictions DROP COLUMN {column}"))
                    print(f"  ✅ Removed column: {column}")
                    removed_count += 1
                except Exception as e:
                    print(f"  ❌ Failed to remove {column}: {e}")
        
        if removed_count > 0:
            session.commit()
            print(f"\n🎉 Successfully removed {removed_count} redundant comfort columns from predictions!")
        else:
            print("\n📝 No comfort columns found to remove from predictions.")
        
        # Show the cleaned predictions table structure
        result = session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'predictions' ORDER BY ordinal_position"
        ))
        remaining_columns = [row[0] for row in result.fetchall()]
        
        print(f"\n📊 Final predictions table structure:")
        for col in remaining_columns:
            print(f"  - {col}")

if __name__ == "__main__":
    remove_comfort_columns_from_predictions()
    print("\n✨ Migration completed successfully!")
