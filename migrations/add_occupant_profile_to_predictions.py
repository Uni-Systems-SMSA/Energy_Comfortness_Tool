#!/usr/bin/env python3
"""
Migration: Add occupant_profile column to predictions table

This migration adds the missing occupant_profile column to the predictions table
to match the current SQLAlchemy model definition.

Usage:
    python migrations/add_occupant_profile_to_predictions.py

This script:
1. Checks if the occupant_profile column exists in predictions table
2. Adds the column if it doesn't exist
3. Also renames pmv_value/ppd_value to pmv/ppd if they exist
"""

import sys
import os
import logging
from sqlalchemy import text, inspect

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.session import SessionLocal, engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    inspector = inspect(engine)
    columns = inspector.get_columns(table_name)
    return any(col['name'] == column_name for col in columns)


def migrate_predictions_table():
    """Add missing occupant_profile column to predictions table."""
    logger.info("🔄 Starting migration: Add occupant_profile to predictions table")
    
    try:
        with SessionLocal() as session:
            # Check if occupant_profile column exists
            has_occupant_profile = check_column_exists('predictions', 'occupant_profile')
            logger.info(f"   occupant_profile column exists: {has_occupant_profile}")
            
            # Check if old column names exist
            has_pmv_value = check_column_exists('predictions', 'pmv_value')
            has_ppd_value = check_column_exists('predictions', 'ppd_value')
            has_pmv = check_column_exists('predictions', 'pmv')
            has_ppd = check_column_exists('predictions', 'ppd')
            
            logger.info(f"   pmv_value column exists: {has_pmv_value}")
            logger.info(f"   ppd_value column exists: {has_ppd_value}")
            logger.info(f"   pmv column exists: {has_pmv}")
            logger.info(f"   ppd column exists: {has_ppd}")
            
            changes_made = False
            
            # Add occupant_profile column if missing
            if not has_occupant_profile:
                logger.info("➕ Adding occupant_profile column to predictions table...")
                session.execute(text("""
                    ALTER TABLE predictions 
                    ADD COLUMN occupant_profile VARCHAR(50)
                """))
                changes_made = True
                logger.info("✅ Added occupant_profile column")
            else:
                logger.info("✅ occupant_profile column already exists")
            
            # Rename pmv_value to pmv if needed
            if has_pmv_value and not has_pmv:
                logger.info("➕ Renaming pmv_value column to pmv...")
                session.execute(text("""
                    ALTER TABLE predictions 
                    RENAME COLUMN pmv_value TO pmv
                """))
                changes_made = True
                logger.info("✅ Renamed pmv_value to pmv")
            
            # Rename ppd_value to ppd if needed
            if has_ppd_value and not has_ppd:
                logger.info("➕ Renaming ppd_value column to ppd...")
                session.execute(text("""
                    ALTER TABLE predictions 
                    RENAME COLUMN ppd_value TO ppd
                """))
                changes_made = True
                logger.info("✅ Renamed ppd_value to ppd")
            
            if changes_made:
                session.commit()
                logger.info("✅ Migration completed successfully")
            else:
                logger.info("✅ No changes needed - schema is already up to date")
            
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        raise


if __name__ == "__main__":
    migrate_predictions_table()
