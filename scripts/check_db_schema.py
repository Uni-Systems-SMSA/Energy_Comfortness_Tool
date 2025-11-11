#!/usr/bin/env python3
"""
Database Schema Diagnostic Tool

This script checks the current database schema and compares it with the expected SQLAlchemy model.
Use this to diagnose schema mismatches.

Usage:
    python scripts/check_db_schema.py
"""

import sys
import os
import logging
from sqlalchemy import inspect

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.session import SessionLocal, engine
from db.models import Prediction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_predictions_schema():
    """Check the predictions table schema and compare with expected columns."""
    logger.info("🔍 Checking predictions table schema...")
    
    try:
        inspector = inspect(engine)
        
        # Get actual columns from database
        actual_columns = inspector.get_columns('predictions')
        actual_column_names = [col['name'] for col in actual_columns]
        actual_column_names.sort()
        
        # Get expected columns from SQLAlchemy model
        expected_columns = [column.name for column in Prediction.__table__.columns]
        expected_columns.sort()
        
        logger.info(f"📊 Database columns ({len(actual_column_names)}):")
        for col in actual_column_names:
            logger.info(f"   ✓ {col}")
        
        logger.info(f"📋 Expected columns ({len(expected_columns)}):")
        for col in expected_columns:
            status = "✓" if col in actual_column_names else "❌"
            logger.info(f"   {status} {col}")
        
        # Find missing columns
        missing_columns = set(expected_columns) - set(actual_column_names)
        if missing_columns:
            logger.error(f"❌ Missing columns in database: {sorted(missing_columns)}")
        
        # Find extra columns
        extra_columns = set(actual_column_names) - set(expected_columns)
        if extra_columns:
            logger.warning(f"⚠️  Extra columns in database: {sorted(extra_columns)}")
        
        if not missing_columns and not extra_columns:
            logger.info("✅ Schema matches perfectly!")
        
        return len(missing_columns) == 0
        
    except Exception as e:
        logger.error(f"❌ Schema check failed: {e}")
        return False


def test_predictions_query():
    """Test if we can query the predictions table without errors."""
    logger.info("🧪 Testing predictions table query...")
    
    try:
        with SessionLocal() as session:
            count = session.query(Prediction).count()
            logger.info(f"✅ Successfully queried predictions table: {count} records")
            return True
    except Exception as e:
        logger.error(f"❌ Query failed: {e}")
        return False


if __name__ == "__main__":
    logger.info("🏥 Database Schema Diagnostic")
    logger.info("=" * 50)
    
    schema_ok = check_predictions_schema()
    query_ok = test_predictions_query()
    
    logger.info("=" * 50)
    if schema_ok and query_ok:
        logger.info("✅ Database schema is healthy!")
    else:
        logger.error("❌ Database schema issues detected")
        if not schema_ok:
            logger.error("   - Schema mismatch found")
        if not query_ok:
            logger.error("   - Query test failed")
        logger.info("💡 Run the migration script to fix schema issues:")
        logger.info("   python migrations/add_occupant_profile_to_predictions.py")
