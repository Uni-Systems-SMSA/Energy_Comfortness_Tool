#!/usr/bin/env python3
"""
Clean predictions table - removes all prediction records from the database.
This will allow testing the new prediction functionality with comfort data from scratch.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from db.session import SessionLocal
from db.models import Prediction
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s – %(message)s")
logger = logging.getLogger(__name__)

def clean_predictions_table():
    """Clean all records from the predictions table"""
    logger.info("Starting predictions table cleanup...")
    
    with SessionLocal() as session:
        try:
            # Count current predictions
            current_count = session.query(Prediction).count()
            logger.info(f"Current predictions in database: {current_count}")
            
            if current_count > 0:
                # Delete all predictions
                deleted_count = session.query(Prediction).delete()
                session.commit()
                
                logger.info(f"Successfully deleted {deleted_count} prediction records")
                print(f"✅ Cleaned predictions table: {deleted_count} records removed")
            else:
                logger.info("Predictions table is already empty")
                print("✅ Predictions table is already empty")
                
            # Verify cleanup
            remaining_count = session.query(Prediction).count()
            if remaining_count == 0:
                logger.info("Verification: Predictions table is now empty")
                print("✅ Verification successful: Predictions table is clean")
                return True
            else:
                logger.error(f"Verification failed: {remaining_count} records still remain")
                print(f"❌ Verification failed: {remaining_count} records still remain")
                return False
                
        except Exception as e:
            logger.error(f"Error cleaning predictions table: {e}")
            print(f"❌ Error cleaning predictions table: {e}")
            session.rollback()
            return False

if __name__ == "__main__":
    print("🧹 Cleaning predictions table...")
    print("This will remove all prediction records from the database.")
    
    try:
        success = clean_predictions_table()
        
        if success:
            print("\n🎉 Predictions table cleaned successfully!")
            print("Ready to test new prediction functionality with comfort data.")
        else:
            print("\n💥 Failed to clean predictions table.")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n💥 Cleanup failed with error: {e}")
        logger.exception("Cleanup exception details:")
        sys.exit(1)
