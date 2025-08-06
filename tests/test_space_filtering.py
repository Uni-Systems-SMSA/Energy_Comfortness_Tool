"""Test that space-specific filtering works correctly after sensor_id fix"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from db.models import EnergyBuilding, EnergySpace, EnergyTimeSeries
from db.session import SessionLocal

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_space_filtering():
    """Test that we can get space-specific energy data"""
    logger.info("Testing space-specific energy data filtering...")
    
    session = SessionLocal()
    try:
        # Get building
        building = session.query(EnergyBuilding).first()
        if not building:
            logger.error("❌ No building found")
            return False
            
        logger.info(f"✅ Found building ID: {building.id}")
        
        # Get all spaces
        spaces = session.query(EnergySpace).filter_by(building_id=building.id).all()
        logger.info(f"✅ Found {len(spaces)} spaces")
        
        # Test filtering by each space's sensor_id
        for space in spaces:
            logger.info(f"\n--- Testing space: {space.name} (sensor_id: {space.sensor_id}) ---")
            
            # Query energy data for this specific space
            space_energy = session.query(EnergyTimeSeries).filter_by(
                building_id=building.id,
                sensor_id=space.sensor_id
            ).all()
            
            logger.info(f"Energy records for space '{space.name}': {len(space_energy)}")
            
            if space_energy:
                # Show some sample data
                latest_record = space_energy[-1]
                logger.info(f"  Latest record: {latest_record.timestamp} | "
                          f"Heating: {latest_record.heating_kwh} kWh | "
                          f"Cooling: {latest_record.cooling_kwh} kWh")
        
        # Test building-wide query (should get all energy data)
        all_energy = session.query(EnergyTimeSeries).filter_by(building_id=building.id).all()
        logger.info(f"\n--- Building-wide energy data ---")
        logger.info(f"Total energy records across all spaces: {len(all_energy)}")
        
        # Count unique sensor_ids in energy data
        unique_sensors = set(record.sensor_id for record in all_energy)
        logger.info(f"Unique sensor_ids in energy data: {len(unique_sensors)}")
        logger.info(f"Sensor IDs: {sorted(unique_sensors)}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error testing space filtering: {e}")
        return False
    finally:
        session.close()

if __name__ == "__main__":
    logger.info("🧪 Testing space-specific energy data filtering...")
    success = test_space_filtering()
    if success:
        logger.info("✅ Space filtering test completed!")
    else:
        logger.error("❌ Space filtering test failed!")
        sys.exit(1)
