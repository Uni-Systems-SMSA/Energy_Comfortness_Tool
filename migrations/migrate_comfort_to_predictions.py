#!/usr/bin/env python3
"""
Migration: Move comfort data from ComfortLevel table to Predictions table
This migration:
1. Adds comfort-related columns to Predictions table
2. Migrates existing ComfortLevel data to Predictions table
3. Drops the ComfortLevel table after successful migration
"""

import os
import sys
from pathlib import Path

# Add parent directory to path so we can import from the project
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text, Column, String, Numeric
from sqlalchemy.exc import OperationalError, ProgrammingError
from db.session import SessionLocal, engine
from db.models import Base
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s – %(message)s")
logger = logging.getLogger(__name__)

def migrate_comfort_to_predictions():
    """Main migration function"""
    logger.info("Starting migration: Move comfort data from ComfortLevel to Predictions table")
    
    with SessionLocal() as session:
        try:
            # Step 1: Add comfort columns to predictions table if they don't exist
            logger.info("Step 1: Adding comfort columns to predictions table...")
            
            comfort_columns = [
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS occupant_profile VARCHAR(50)",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS pmv NUMERIC",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS ppd NUMERIC",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS thermal_comfort_class VARCHAR(2)",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS visual_comfort_class VARCHAR(2)",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS acoustic_comfort_class VARCHAR(2)",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS co2_comfort_class VARCHAR(2)",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS co_comfort_class VARCHAR(2)",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS tvoc_comfort_class VARCHAR(2)",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS pm25_comfort_class VARCHAR(2)",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS pm10_comfort_class VARCHAR(2)",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS visual_comfort_score NUMERIC",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS acoustic_annoyance_level NUMERIC",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS overall_comfort NUMERIC",
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS overall_comfort_class VARCHAR(2)"
            ]
            
            for sql in comfort_columns:
                try:
                    session.execute(text(sql))
                    logger.info(f"  ✓ Added column: {sql.split()[-2]}")
                except (OperationalError, ProgrammingError) as e:
                    if "already exists" in str(e).lower():
                        logger.info(f"  ✓ Column already exists: {sql.split()[-2]}")
                    else:
                        logger.error(f"  ✗ Error adding column: {e}")
                        raise
            
            session.commit()
            logger.info("Step 1 completed: All comfort columns added to predictions table")
            
            # Step 2: Check if ComfortLevel table exists and has data to migrate
            logger.info("Step 2: Checking for existing ComfortLevel data...")
            
            try:
                comfort_count_result = session.execute(text("SELECT COUNT(*) FROM comfort_levels"))
                comfort_count = comfort_count_result.scalar()
                logger.info(f"Found {comfort_count} records in comfort_levels table")
                
                if comfort_count > 0:
                    # Step 3: Migrate existing ComfortLevel data to Predictions
                    logger.info("Step 3: Migrating ComfortLevel data to Predictions table...")
                    
                    migration_sql = """
                    UPDATE predictions 
                    SET 
                        occupant_profile = cl.occupant_profile,
                        pmv = cl.pmv,
                        ppd = cl.ppd,
                        thermal_comfort_class = cl.thermal_comfort_class,
                        visual_comfort_class = cl.visual_comfort_class,
                        acoustic_comfort_class = cl.acoustic_comfort_class,
                        co2_comfort_class = cl.co2_comfort_class,
                        co_comfort_class = cl.co_comfort_class,
                        tvoc_comfort_class = cl.tvoc_comfort_class,
                        pm25_comfort_class = cl.pm25_comfort_class,
                        pm10_comfort_class = cl.pm10_comfort_class,
                        visual_comfort_score = cl.visual_comfort_score,
                        acoustic_annoyance_level = cl.acoustic_annoyance_level,
                        overall_comfort = cl.overall_comfort,
                        overall_comfort_class = cl.overall_comfort_class
                    FROM comfort_levels cl
                    WHERE predictions.prediction_id = cl.prediction_id
                    """
                    
                    result = session.execute(text(migration_sql))
                    rows_updated = result.rowcount
                    session.commit()
                    
                    logger.info(f"Step 3 completed: Migrated comfort data for {rows_updated} predictions")
                else:
                    logger.info("Step 3 skipped: No ComfortLevel data to migrate")
                
                # Step 4: Drop ComfortLevel table (if it exists)
                logger.info("Step 4: Dropping ComfortLevel table...")
                try:
                    session.execute(text("DROP TABLE IF EXISTS comfort_levels CASCADE"))
                    session.commit()
                    logger.info("Step 4 completed: ComfortLevel table dropped")
                except Exception as e:
                    logger.warning(f"Step 4 warning: Could not drop comfort_levels table: {e}")
                
            except (OperationalError, ProgrammingError) as e:
                if "does not exist" in str(e).lower():
                    logger.info("Step 2-4 skipped: comfort_levels table does not exist")
                else:
                    logger.error(f"Error checking comfort_levels table: {e}")
                    raise
            
            # Step 5: Update database schema (recreate tables based on new models)
            logger.info("Step 5: Updating database schema...")
            try:
                Base.metadata.create_all(bind=engine)
                logger.info("Step 5 completed: Database schema updated")
            except Exception as e:
                logger.warning(f"Step 5 warning: Schema update had issues: {e}")
            
            logger.info("🎉 Migration completed successfully!")
            return True
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            session.rollback()
            raise

def verify_migration():
    """Verify that the migration was successful"""
    logger.info("Verifying migration...")
    
    with SessionLocal() as session:
        try:
            # Check predictions table has comfort columns
            result = session.execute(text("SELECT COUNT(*) FROM predictions WHERE occupant_profile IS NOT NULL"))
            comfort_predictions = result.scalar()
            
            total_predictions = session.execute(text("SELECT COUNT(*) FROM predictions")).scalar()
            
            logger.info(f"Verification: {total_predictions} total predictions, {comfort_predictions} with comfort data")
            
            # Check if comfort_levels table still exists
            try:
                session.execute(text("SELECT 1 FROM comfort_levels LIMIT 1"))
                logger.warning("Warning: comfort_levels table still exists after migration")
                return False
            except (OperationalError, ProgrammingError):
                logger.info("✓ comfort_levels table successfully removed")
                return True
                
        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return False

if __name__ == "__main__":
    print("🚀 Starting comfort data migration...")
    print("This will move all comfort data from ComfortLevel table to Predictions table")
    
    # Skip confirmation for automated execution
    print("Proceeding with migration...")
    
    try:
        # Run migration
        success = migrate_comfort_to_predictions()
        
        if success:
            # Verify migration
            if verify_migration():
                print("\n✅ Migration completed and verified successfully!")
                print("Comfort data is now stored directly in the Predictions table.")
            else:
                print("\n⚠️  Migration completed but verification failed.")
                print("Please check the logs for details.")
        else:
            print("\n❌ Migration failed.")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n💥 Migration failed with error: {e}")
        logger.exception("Migration exception details:")
        sys.exit(1)
