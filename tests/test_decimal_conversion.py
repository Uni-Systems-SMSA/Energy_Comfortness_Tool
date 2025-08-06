"""Test basic energy data retrieval and conversion"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
from datetime import datetime, date
from db.session import SessionLocal
from db.models import EnergyBuilding, EnergySpace, EnergyTimeSeries

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_energy_data_conversion():
    """Test that energy data can be retrieved and converted without errors"""
    logger.info("Testing energy data retrieval and conversion...")
    
    session = SessionLocal()
    try:
        # Get the latest building
        building = session.query(EnergyBuilding).order_by(EnergyBuilding.building_id.desc()).first()
        if not building:
            logger.error("❌ No building found")
            return False
            
        logger.info(f"✅ Using building ID: {building.building_id}")
        
        # Get a space
        space = session.query(EnergySpace).filter_by(building_id=building.building_id).first()
        if not space:
            logger.error("❌ No space found")
            return False
            
        logger.info(f"✅ Using space: {space.zone_name} (sensor_id: {space.sensor_id})")
        
        # Get some timeseries data
        timeseries = session.query(EnergyTimeSeries).filter_by(space_id=space.space_id).limit(5).all()
        
        logger.info(f"✅ Retrieved {len(timeseries)} timeseries records")
        
        # Test conversion to float
        for record in timeseries:
            heating_power = float(record.heating_power_w)
            cooling_power = float(record.cooling_power_w)
            heating_energy = float(record.heating_energy_kwh)
            cooling_energy = float(record.cooling_energy_kwh)
            
            logger.info(f"  {record.timestamp} | "
                      f"Powers: {heating_power:.1f}W heat, {cooling_power:.1f}W cool | "
                      f"Energies: {heating_energy:.2f}kWh heat, {cooling_energy:.2f}kWh cool")
        
        # Test data type
        if timeseries:
            sample_heating = [float(record.heating_power_w) for record in timeseries]
            sample_cooling = [float(record.cooling_power_w) for record in timeseries]
            
            logger.info(f"✅ Sample heating array: {sample_heating}")
            logger.info(f"✅ Sample cooling array: {sample_cooling}")
            
            # Test numpy operations
            import numpy as np
            avg_heating = np.mean(sample_heating)
            avg_cooling = np.mean(sample_cooling)
            
            # Test final conversion to ensure it works
            final_heating = float(avg_heating)
            final_cooling = float(avg_cooling)
            
            logger.info(f"✅ Averages: {final_heating:.2f}W heating, {final_cooling:.2f}W cooling")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error testing energy data conversion: {e}", exc_info=True)
        return False
    finally:
        session.close()

if __name__ == "__main__":
    logger.info("🧪 Testing energy data conversion...")
    success = test_energy_data_conversion()
    if success:
        logger.info("✅ Energy data conversion test passed!")
    else:
        logger.error("❌ Energy data conversion test failed!")
        sys.exit(1)
