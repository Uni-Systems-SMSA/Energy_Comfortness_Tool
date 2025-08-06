"""Check the structure of buildings and spaces in the database"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from db.models import EnergyBuilding, EnergySpace, EnergyTimeSeries
from db.session import SessionLocal

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_database_structure():
    """Check buildings and spaces structure"""
    logger.info("Checking database structure...")
    
    session = SessionLocal()
    try:
        # Get all buildings
        buildings = session.query(EnergyBuilding).all()
        logger.info(f"Total buildings: {len(buildings)}")
        
        for building in buildings:
            logger.info(f"\n--- Building ID: {building.building_id} ---")
            logger.info(f"Simulation timestamp: {building.simulation_timestamp}")
            
            # Get spaces for this building
            spaces = session.query(EnergySpace).filter_by(building_id=building.building_id).all()
            logger.info(f"Spaces in building: {len(spaces)}")
            
            for space in spaces:
                logger.info(f"  - Zone: '{space.zone_id}' | Sensor: '{space.sensor_id}' | Name: '{space.zone_name}'")
        
        # Check sensor_id distribution
        all_spaces = session.query(EnergySpace).all()
        sensor_ids = [space.sensor_id for space in all_spaces]
        from collections import Counter
        sensor_counts = Counter(sensor_ids)
        
        logger.info(f"\n--- Sensor ID Distribution ---")
        for sensor_id, count in sensor_counts.items():
            logger.info(f"'{sensor_id}': {count} spaces")
            
        return True
        
    except Exception as e:
        logger.error(f"❌ Error checking database structure: {e}")
        return False
    finally:
        session.close()

if __name__ == "__main__":
    logger.info("🔍 Checking database structure...")
    success = check_database_structure()
    if success:
        logger.info("✅ Database structure check completed!")
    else:
        logger.error("❌ Database structure check failed!")
        sys.exit(1)
