#!/usr/bin/env python3
"""
Test script to check space name mapping and why only "Bad" is showing.
"""

import os
import sys
import logging
from pathlib import Path
import pandas as pd

# Add the parent directory to Python path for imports
sys.path.append(os.path.abspath(os.path.join(__file__, "..")))

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from db.session import SessionLocal
from db.models import EnergyBuilding, EnergySpace

def test_space_name_mapping():
    """Test space name mapping from CSV file."""
    logger.info("Testing space name mapping...")
    
    try:
        with SessionLocal() as session:
            # Get the latest building
            building = session.query(EnergyBuilding).order_by(EnergyBuilding.simulation_timestamp.desc()).first()
            
            if not building:
                logger.error("❌ No buildings found")
                return False
                
            logger.info(f"✅ Found building ID: {building.building_id}")
            logger.info(f"   - Results path: {building.eplus_results_path}")
            
            # Get all spaces
            spaces = session.query(EnergySpace).filter(
                EnergySpace.building_id == building.building_id
            ).all()
            
            logger.info(f"✅ Found {len(spaces)} spaces in database:")
            for space in spaces:
                logger.info(f"   - Zone ID: '{space.zone_id}' -> Name: '{space.zone_name}' | Sensor: '{space.sensor_id}'")
            
            # Try to load space.csv from the results path
            results_dir = Path(building.eplus_results_path)
            export_dir = results_dir.parent.parent.parent  # Go up from SimResults/{uuid} to export/
            space_csv_path = export_dir / "space.csv"
            
            logger.info(f"Looking for space.csv at: {space_csv_path}")
            
            if space_csv_path.exists():
                logger.info("✅ Found space.csv file")
                
                # Read and display the CSV
                space_df = pd.read_csv(space_csv_path)
                logger.info(f"Space CSV shape: {space_df.shape}")
                logger.info(f"Space CSV columns: {list(space_df.columns)}")
                
                # Show all rows
                logger.info("Space CSV contents:")
                for idx, row in space_df.iterrows():
                    logger.info(f"   Row {idx}: {dict(row)}")
                
                # Create mapping like the app does
                if len(space_df.columns) >= 3:
                    zone_id_col = space_df.columns[1]  # 2nd column: ID
                    space_name_col = space_df.columns[2]  # 3rd column: long_name
                    
                    valid_rows = space_df.dropna(subset=[zone_id_col, space_name_col])
                    zone_ids_upper = valid_rows[zone_id_col].astype(str).str.upper()
                    space_names = valid_rows[space_name_col].astype(str)
                    space_mapping = dict(zip(zone_ids_upper, space_names))
                    
                    logger.info(f"✅ Created space mapping with {len(space_mapping)} entries:")
                    for zone_id_upper, space_name in space_mapping.items():
                        logger.info(f"   '{zone_id_upper}' -> '{space_name}'")
                    
                    # Check which database spaces match the CSV
                    logger.info("Matching database spaces with CSV:")
                    valid_count = 0
                    for space in spaces:
                        zone_id_upper = space.zone_id.upper()
                        if zone_id_upper in space_mapping:
                            csv_name = space_mapping[zone_id_upper]
                            logger.info(f"   ✅ MATCH: '{space.zone_id}' -> '{csv_name}' (heating: {space.heating_kwh} kWh)")
                            valid_count += 1
                        else:
                            logger.info(f"   ❌ NO MATCH: '{space.zone_id}' -> no mapping found")
                    
                    logger.info(f"Total valid spaces (found in CSV): {valid_count} out of {len(spaces)}")
                    
                    if valid_count == 0:
                        logger.error("❌ No spaces from database match the CSV - this explains why no data is shown!")
                        return False
                    elif valid_count == 1:
                        logger.warning(f"⚠️ Only 1 space matches CSV - this explains why only one space is shown!")
                        
            else:
                logger.error(f"❌ No space.csv file found at: {space_csv_path}")
                # Try alternative locations
                alt_paths = [
                    results_dir.parent.parent / "space.csv",
                    results_dir.parent / "space.csv",
                    results_dir / "space.csv",
                ]
                for alt_path in alt_paths:
                    logger.info(f"   Checking alternative: {alt_path} -> {'EXISTS' if alt_path.exists() else 'NOT FOUND'}")
                return False
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Test failed: {str(e)}", exc_info=True)
        return False

if __name__ == "__main__":
    print("🧪 Testing space name mapping...")
    success = test_space_name_mapping()
    if success:
        print("✅ Space name mapping test completed!")
    else:
        print("❌ Space name mapping test failed!")
        sys.exit(1)
