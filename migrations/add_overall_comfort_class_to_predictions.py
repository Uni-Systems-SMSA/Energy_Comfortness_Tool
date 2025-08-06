#!/usr/bin/env python3
"""
Add overall_comfort_class column to predictions table

This migration adds the overall_comfort_class column to store the classified
comfort level (A, B, C, D, NC) based on the overall comfort score.

Run this script to update the database schema.
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from db.session import DB_URL

def main():
    """Add overall_comfort_class column to predictions table"""
    engine = create_engine(DB_URL)
    
    try:
        with engine.connect() as conn:
            # Check if column already exists
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'predictions' 
                AND column_name = 'overall_comfort_class'
            """))
            
            if result.fetchone():
                print("Column 'overall_comfort_class' already exists in predictions table")
                return
            
            # Add the column
            conn.execute(text("""
                ALTER TABLE predictions 
                ADD COLUMN overall_comfort_class VARCHAR(2)
            """))
            
            conn.commit()
            print("Successfully added 'overall_comfort_class' column to predictions table")
            
    except Exception as e:
        print(f"Error adding column: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
