"""Check the actual date range of energy data in the database"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import sessionmaker
from db.models import EnergyBuilding, EnergySpace, EnergyTimeSeries
from db.session import SessionLocal

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_energy_date_range():
    """Check the actual date range of energy data"""
    logger.info("Checking energy data date range...")
    
    session = SessionLocal()
    try:
        # Get the latest building
        building = session.query(EnergyBuilding).order_by(EnergyBuilding.building_id.desc()).first()
        if not building:
            logger.error("❌ No building found")
            return False
            
        logger.info(f"✅ Using building ID: {building.building_id}")
        logger.info(f"Simulation timestamp: {building.simulation_timestamp}")
        
        # Get all spaces for this building
        spaces = session.query(EnergySpace).filter_by(building_id=building.building_id).all()
        space_ids = [space.space_id for space in spaces]
        
        # Get date range of energy data
        date_range = session.query(
            func.min(EnergyTimeSeries.timestamp).label('min_date'),
            func.max(EnergyTimeSeries.timestamp).label('max_date'),
            func.count(EnergyTimeSeries.timeseries_id).label('total_records')
        ).filter(EnergyTimeSeries.space_id.in_(space_ids)).first()
        
        if date_range and date_range.min_date:
            logger.info(f"📅 Energy data date range:")
            logger.info(f"   Min date: {date_range.min_date}")
            logger.info(f"   Max date: {date_range.max_date}")
            logger.info(f"   Total records: {date_range.total_records}")
            
            # Check what years are covered
            min_year = date_range.min_date.year
            max_year = date_range.max_date.year
            logger.info(f"   Years covered: {min_year} to {max_year}")
            
            # Sample some records to see the pattern
            sample_records = session.query(EnergyTimeSeries).filter(
                EnergyTimeSeries.space_id.in_(space_ids)
            ).limit(5).all()
            
            logger.info(f"📊 Sample energy records:")
            for record in sample_records:
                logger.info(f"   {record.timestamp} | "
                          f"Heating: {record.heating_energy_kwh} kWh | "
                          f"Cooling: {record.cooling_energy_kwh} kWh")
        else:
            logger.warning("⚠️ No energy timeseries data found")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error checking energy date range: {e}")
        return False
    finally:
        session.close()

if __name__ == "__main__":
    logger.info("🔍 Checking energy data date range...")
    success = check_energy_date_range()
    if success:
        logger.info("✅ Energy date range check completed!")
    else:
        logger.error("❌ Energy date range check failed!")
        sys.exit(1)
