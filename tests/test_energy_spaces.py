"""Test that the Energy tab can now show all spaces correctly"""
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

def test_energy_tab_data():
    """Test energy data availability for each space"""
    logger.info("Testing energy data availability for each space...")
    
    session = SessionLocal()
    try:
        # Get the latest building (as would be used by the dashboard)
        building = session.query(EnergyBuilding).order_by(EnergyBuilding.building_id.desc()).first()
        if not building:
            logger.error("❌ No building found")
            return False
            
        logger.info(f"✅ Using latest building ID: {building.building_id}")
        
        # Get all unique space names (sensor_ids) that should appear in dropdown
        unique_spaces = session.query(EnergySpace.sensor_id).filter_by(building_id=building.building_id).distinct().all()
        space_names = [space[0] for space in unique_spaces]
        logger.info(f"✅ Available spaces in dropdown: {len(space_names)}")
        for space_name in sorted(space_names):
            logger.info(f"  - '{space_name}'")
        
        # Test filtering by each space name
        logger.info(f"\n--- Testing space-specific energy data ---")
        for space_name in space_names:
            logger.info(f"\nTesting space: '{space_name}'")
            
            # Get the space(s) for this sensor_id
            spaces_for_sensor = session.query(EnergySpace).filter_by(
                building_id=building.building_id,
                sensor_id=space_name
            ).all()
            
            logger.info(f"  Spaces matching sensor_id: {len(spaces_for_sensor)}")
            
            if spaces_for_sensor:
                # Get energy data for these spaces
                space_ids = [space.space_id for space in spaces_for_sensor]
                space_energy = session.query(EnergyTimeSeries).filter(
                    EnergyTimeSeries.space_id.in_(space_ids)
                ).all()
                
                logger.info(f"  Energy records: {len(space_energy)}")
                
                if space_energy:
                    # Show some sample data
                    latest_record = space_energy[-1]
                    logger.info(f"  Latest: {latest_record.timestamp} | "
                              f"Heating: {latest_record.heating_energy_kwh:.2f} kWh | "
                              f"Cooling: {latest_record.cooling_energy_kwh:.2f} kWh")
                    logger.info(f"  ✅ Space '{space_name}' has energy data")
                else:
                    logger.warning(f"  ⚠️ Space '{space_name}' has no energy data")
            else:
                logger.warning(f"  ⚠️ No spaces found for sensor_id '{space_name}'")
        
        # Test building-wide query (when no space filter is applied)
        all_spaces = session.query(EnergySpace).filter_by(building_id=building.building_id).all()
        all_space_ids = [space.space_id for space in all_spaces]
        all_energy = session.query(EnergyTimeSeries).filter(
            EnergyTimeSeries.space_id.in_(all_space_ids)
        ).all()
        
        logger.info(f"\n--- Building-wide energy data ---")
        logger.info(f"Total energy records: {len(all_energy)}")
        
        if all_energy:
            # Get unique sensor_ids by mapping through spaces
            space_id_to_sensor = {space.space_id: space.sensor_id for space in all_spaces}
            unique_sensors_in_data = set(space_id_to_sensor[record.space_id] for record in all_energy)
            logger.info(f"Unique sensor_ids in energy data: {len(unique_sensors_in_data)}")
            logger.info(f"Sensor IDs in data: {sorted(unique_sensors_in_data)}")
            
            # Check if all spaces have energy data
            missing_data = set(space_names) - unique_sensors_in_data
            if missing_data:
                logger.warning(f"⚠️ Spaces missing energy data: {missing_data}")
            else:
                logger.info("✅ All spaces have energy data")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error testing energy data: {e}")
        return False
    finally:
        session.close()

if __name__ == "__main__":
    logger.info("🧪 Testing Energy tab space availability...")
    success = test_energy_tab_data()
    if success:
        logger.info("✅ Energy tab test completed!")
    else:
        logger.error("❌ Energy tab test failed!")
        sys.exit(1)
