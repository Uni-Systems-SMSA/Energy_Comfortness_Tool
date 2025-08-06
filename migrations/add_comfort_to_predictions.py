#!/usr/bin/env python3
"""
Database migration to add comfort metrics to the Prediction table.
This adds columns for storing comfort analysis results alongside predictions.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from sqlalchemy import text
from db.session import SessionLocal, engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_comfort_columns_to_predictions():
    """Add comfort metric columns to the predictions table."""
    
    # SQL statements to add comfort columns
    add_columns_sql = """
    -- Add comfort metric columns to predictions table
    ALTER TABLE predictions 
    ADD COLUMN IF NOT EXISTS pmv_value NUMERIC,
    ADD COLUMN IF NOT EXISTS ppd_value NUMERIC,
    ADD COLUMN IF NOT EXISTS thermal_comfort_class VARCHAR(2),
    ADD COLUMN IF NOT EXISTS visual_comfort_class VARCHAR(2),
    ADD COLUMN IF NOT EXISTS acoustic_comfort_class VARCHAR(2),
    ADD COLUMN IF NOT EXISTS visual_comfort_score NUMERIC,
    ADD COLUMN IF NOT EXISTS acoustic_annoyance_level NUMERIC,
    ADD COLUMN IF NOT EXISTS co2_comfort_class VARCHAR(2),
    ADD COLUMN IF NOT EXISTS co_comfort_class VARCHAR(2),
    ADD COLUMN IF NOT EXISTS tvoc_comfort_class VARCHAR(2),
    ADD COLUMN IF NOT EXISTS pm25_comfort_class VARCHAR(2),
    ADD COLUMN IF NOT EXISTS pm10_comfort_class VARCHAR(2);
    """
    
    # Add comments for the new columns
    comments_sql = """
    COMMENT ON COLUMN predictions.pmv_value IS 'Predicted Mean Vote for thermal comfort';
    COMMENT ON COLUMN predictions.ppd_value IS 'Predicted Percentage Dissatisfied (%) for thermal comfort';
    COMMENT ON COLUMN predictions.thermal_comfort_class IS 'Thermal comfort class: A, B, C, NC';
    COMMENT ON COLUMN predictions.visual_comfort_class IS 'Visual comfort class: A, B, C, NC';
    COMMENT ON COLUMN predictions.acoustic_comfort_class IS 'Acoustic comfort class: A, B, C, D, NC';
    COMMENT ON COLUMN predictions.visual_comfort_score IS 'Yong visual comfort score (1-5 scale)';
    COMMENT ON COLUMN predictions.acoustic_annoyance_level IS 'Age-dependent acoustic annoyance level';
    COMMENT ON COLUMN predictions.co2_comfort_class IS 'CO2 comfort class: A, B, C, D, NC';
    COMMENT ON COLUMN predictions.co_comfort_class IS 'CO comfort class: A, B, NC';
    COMMENT ON COLUMN predictions.tvoc_comfort_class IS 'TVOC comfort class: A, B, NC';
    COMMENT ON COLUMN predictions.pm25_comfort_class IS 'PM2.5 comfort class: A, B, NC';
    COMMENT ON COLUMN predictions.pm10_comfort_class IS 'PM10 comfort class: A, B, NC';
    """
    
    try:
        with engine.connect() as conn:
            # Execute the ALTER TABLE statement
            logger.info("Adding comfort columns to predictions table...")
            conn.execute(text(add_columns_sql))
            
            # Add column comments
            logger.info("Adding column comments...")
            conn.execute(text(comments_sql))
            
            # Commit the transaction
            conn.commit()
            
            logger.info("✅ Successfully added comfort columns to predictions table")
            
            # Verify the columns were added
            result = conn.execute(text("""
                SELECT column_name, data_type, is_nullable 
                FROM information_schema.columns 
                WHERE table_name = 'predictions' 
                AND column_name LIKE '%comfort%' OR column_name IN ('pmv_value', 'ppd_value')
                ORDER BY column_name;
            """))
            
            logger.info("New comfort columns in predictions table:")
            for row in result:
                logger.info(f"  - {row.column_name} ({row.data_type}, nullable: {row.is_nullable})")
                
    except Exception as e:
        logger.error(f"❌ Error adding comfort columns: {e}", exc_info=True)
        raise

def check_existing_comfort_columns():
    """Check if comfort columns already exist in the predictions table."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as count
                FROM information_schema.columns 
                WHERE table_name = 'predictions' 
                AND (column_name LIKE '%comfort%' OR column_name IN ('pmv_value', 'ppd_value'))
            """))
            
            count = result.scalar()
            logger.info(f"Found {count} existing comfort columns in predictions table")
            return count > 0
            
    except Exception as e:
        logger.error(f"Error checking existing columns: {e}")
        return False

if __name__ == "__main__":
    logger.info("🔄 Starting comfort columns migration for predictions table")
    
    # Check if columns already exist
    if check_existing_comfort_columns():
        logger.info("⚠️ Comfort columns already exist in predictions table")
        
        # Ask user if they want to proceed anyway (in case of partial migration)
        response = input("Do you want to run the migration anyway (will use IF NOT EXISTS)? [y/N]: ")
        if response.lower() != 'y':
            logger.info("Migration cancelled by user")
            sys.exit(0)
    
    # Run the migration
    try:
        add_comfort_columns_to_predictions()
        logger.info("🎉 Migration completed successfully!")
        
    except Exception as e:
        logger.error(f"💥 Migration failed: {e}")
        sys.exit(1)
