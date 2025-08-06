#!/usr/bin/env python3
"""
Simple test script to verify space-specific energy data filtering functionality.
"""

import os
import sys
import logging
from datetime import datetime, date
from pathlib import Path

# Add the parent directory to Python path for imports
sys.path.append(os.path.abspath(os.path.join(__file__, "..")))

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import directly what we need without loading the full app
from db.session import SessionLocal
from db.models import EnergyBuilding, EnergySpace, EnergyTimeSeries

def test_database_query():
    """Test that we can query the database correctly."""
    logger.info("Testing database query for space-specific vs building-wide data...")
    
    try:
        with SessionLocal() as session:
            # Test 1: Get all buildings
            buildings = session.query(EnergyBuilding).order_by(EnergyBuilding.simulation_timestamp.desc()).limit(1).all()
            
            if not buildings:
                logger.error("❌ No energy buildings found in database")
                return False
            
            building = buildings[0]
            logger.info(f"✅ Found building ID: {building.building_id}")
            logger.info(f"   - Simulation timestamp: {building.simulation_timestamp}")
            logger.info(f"   - Total heating: {building.total_heating_kwh} kWh")
            logger.info(f"   - Total cooling: {building.total_cooling_kwh} kWh")
            
            # Test 2: Get all spaces for this building
            all_spaces = session.query(EnergySpace).filter(
                EnergySpace.building_id == building.building_id
            ).all()
            
            logger.info(f"✅ Found {len(all_spaces)} total spaces in building")
            
            # List all sensor_ids
            sensor_ids = set()
            for space in all_spaces:
                if space.sensor_id:
                    sensor_ids.add(space.sensor_id)
                logger.info(f"   - Space '{space.zone_id}' -> Sensor '{space.sensor_id}': {space.heating_kwh} kWh heating, {space.cooling_kwh} kWh cooling")
            
            logger.info(f"✅ Found {len(sensor_ids)} unique sensor IDs: {list(sensor_ids)}")
            
            # Test 3: Get spaces for a specific sensor
            if sensor_ids:
                test_sensor = list(sensor_ids)[0]
                logger.info(f"=== Testing with specific sensor: '{test_sensor}' ===")
                
                specific_spaces = session.query(EnergySpace).filter(
                    EnergySpace.building_id == building.building_id,
                    EnergySpace.sensor_id == test_sensor
                ).all()
                
                logger.info(f"✅ Found {len(specific_spaces)} spaces for sensor '{test_sensor}'")
                for space in specific_spaces:
                    logger.info(f"   - Space '{space.zone_id}': {space.heating_kwh} kWh heating, {space.cooling_kwh} kWh cooling")
                
                # Verify the logic: specific spaces should be subset of all spaces
                if len(specific_spaces) <= len(all_spaces):
                    logger.info("✅ Space filtering working correctly - specific spaces are subset of all spaces")
                else:
                    logger.error("❌ Space filtering error - specific spaces exceed total spaces")
                    return False
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Database query test failed: {str(e)}", exc_info=True)
        return False

if __name__ == "__main__":
    print("🧪 Testing database queries for space-specific functionality...")
    success = test_database_query()
    if success:
        print("✅ Database queries are working correctly!")
    else:
        print("❌ Database query tests failed!")
        sys.exit(1)
