#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migration script to add the EnergyTimeSeries table for timestamped energy data.
Run this script to upgrade existing databases to support the new timestamped energy model.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from db.models import Base, EnergyTimeSeries

def main():
    """Create the EnergyTimeSeries table if it doesn't exist."""
    print("🔄 Starting migration to add timestamped energy data support...")
    
    # Load environment variables
    load_dotenv()
    
    # Create database connection
    DATABASE_URL = (
        f"postgresql+psycopg2://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ['POSTGRES_HOST']}:{os.environ.get('POSTGRES_PORT', 5432)}/"
        f"{os.environ['POSTGRES_DB']}"
    )
    
    try:
        engine = create_engine(DATABASE_URL, echo=True)
        
        # Check if the table already exists
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        
        if 'energy_timeseries' in existing_tables:
            print("✅ EnergyTimeSeries table already exists - migration not needed")
            return
        
        print("📝 Creating EnergyTimeSeries table...")
        
        # Create only the new table
        EnergyTimeSeries.__table__.create(engine)
        
        print("✅ Successfully created EnergyTimeSeries table!")
        print("📊 The database now supports timestamped energy data storage.")
        print("")
        print("🔄 Note: Existing energy simulation data will continue to work,")
        print("   but new simulations will store detailed timestamped data.")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise

if __name__ == "__main__":
    main()
