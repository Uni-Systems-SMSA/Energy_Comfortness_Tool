#!/usr/bin/env python3
"""
Migration script to add overall_comfort column to predictions table.

This script adds the 'overall_comfort' column to store the weighted average 
of all comfort classes as a single numeric value (0-4 scale).

Run with: python migrations/add_overall_comfort_to_predictions.py
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db.session import engine

def main():
    """Add overall_comfort column to predictions table."""
    
    print("Adding overall_comfort column to predictions table...")
    
    migration_sql = """
    -- Add overall_comfort column to predictions table
    ALTER TABLE predictions 
    ADD COLUMN IF NOT EXISTS overall_comfort NUMERIC;
    
    -- Add comment to the column (PostgreSQL syntax)
    COMMENT ON COLUMN predictions.overall_comfort IS 'Weighted average of all comfort classes (scale 0-4, where 4 is best comfort)';
    """
    
    try:
        with engine.connect() as conn:
            # Execute the migration
            conn.execute(text(migration_sql))
            conn.commit()
            print("✅ Successfully added overall_comfort column to predictions table")
            
            # Verify the column was added
            result = conn.execute(text("""
                SELECT column_name, data_type
                FROM information_schema.columns 
                WHERE table_name = 'predictions' 
                AND column_name = 'overall_comfort'
            """))
            
            row = result.fetchone()
            if row:
                print(f"✅ Verified: Column '{row[0]}' added with type '{row[1]}'")
            else:
                print("⚠️  Warning: Could not verify column was added")
                
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
