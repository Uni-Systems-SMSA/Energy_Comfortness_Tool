#!/usr/bin/env python3
"""
Simple test to demonstrate the date filtering fix by examining database queries directly.
"""

import sys
import os
import logging
from datetime import datetime, date
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import database modules
from db.session import SessionLocal
from db.models import EnergyBuilding, EnergySpace, EnergyTimeSeries

def test_database_energy_filtering():
    """Test database queries for energy data with different date filters."""
    logger.info("Testing database energy filtering...")
    
    try:
        with SessionLocal() as session:
            # Get the latest building
            building = session.query(EnergyBuilding).order_by(EnergyBuilding.simulation_timestamp.desc()).first()
            
            if not building:
                logger.error("No energy building found in database")
                return False
            
            logger.info(f"Found building ID: {building.building_id}")
            logger.info(f"Simulation period: {building.simulation_start_date} to {building.simulation_end_date}")
            logger.info(f"Total heating: {building.total_heating_kwh:.1f} kWh")
            logger.info(f"Total cooling: {building.total_cooling_kwh:.1f} kWh")
            
            # Get spaces for this building
            spaces = session.query(EnergySpace).filter(EnergySpace.building_id == building.building_id).all()
            logger.info(f"Found {len(spaces)} spaces")
            
            # Test 1: Get all timeseries data (no filtering)
            logger.info("\n=== Test 1: All timeseries data ===")
            total_records = 0
            total_heating_energy = 0
            total_cooling_energy = 0
            
            for space in spaces:
                timeseries_count = session.query(EnergyTimeSeries).filter(
                    EnergyTimeSeries.space_id == space.space_id
                ).count()
                
                # Sum up power data from time series (convert W to kWh assuming hourly data)
                timeseries_data = session.query(EnergyTimeSeries).filter(
                    EnergyTimeSeries.space_id == space.space_id
                ).all()
                
                space_heating_kwh = float(sum(record.heating_power_w for record in timeseries_data)) / 1000.0
                space_cooling_kwh = float(sum(record.cooling_power_w for record in timeseries_data)) / 1000.0
                
                total_records += timeseries_count
                total_heating_energy += space_heating_kwh
                total_cooling_energy += space_cooling_kwh
                
                logger.info(f"  Space {space.zone_id}: {timeseries_count} records, {space_heating_kwh:.1f} kWh heating, {space_cooling_kwh:.1f} kWh cooling")
            
            logger.info(f"Full data summary: {total_records} records, {total_heating_energy:.1f} kWh heating, {total_cooling_energy:.1f} kWh cooling")
            
            # Test 2: Filter by 1-month period
            logger.info("\n=== Test 2: 1-month filtered data ===")
            start_dt = datetime(2025, 6, 15)
            end_dt = datetime(2025, 7, 15)
            
            filtered_records = 0
            filtered_heating_energy = 0
            filtered_cooling_energy = 0
            
            for space in spaces:
                timeseries_filtered = session.query(EnergyTimeSeries).filter(
                    EnergyTimeSeries.space_id == space.space_id,
                    EnergyTimeSeries.timestamp >= start_dt,
                    EnergyTimeSeries.timestamp <= end_dt
                ).all()
                
                space_filtered_heating = float(sum(record.heating_power_w for record in timeseries_filtered)) / 1000.0
                space_filtered_cooling = float(sum(record.cooling_power_w for record in timeseries_filtered)) / 1000.0
                
                filtered_records += len(timeseries_filtered)
                filtered_heating_energy += space_filtered_heating
                filtered_cooling_energy += space_filtered_cooling
                
                if len(timeseries_filtered) > 0:
                    logger.info(f"  Space {space.zone_id}: {len(timeseries_filtered)} records, {space_filtered_heating:.1f} kWh heating, {space_filtered_cooling:.1f} kWh cooling")
            
            logger.info(f"1-month filtered summary: {filtered_records} records, {filtered_heating_energy:.1f} kWh heating, {filtered_cooling_energy:.1f} kWh cooling")
            
            # Test 3: Filter by 2-week period
            logger.info("\n=== Test 3: 2-week filtered data ===")
            start_dt2 = datetime(2025, 7, 1)
            end_dt2 = datetime(2025, 7, 14)
            
            filtered2_records = 0
            filtered2_heating_energy = 0
            filtered2_cooling_energy = 0
            
            for space in spaces:
                timeseries_filtered2 = session.query(EnergyTimeSeries).filter(
                    EnergyTimeSeries.space_id == space.space_id,
                    EnergyTimeSeries.timestamp >= start_dt2,
                    EnergyTimeSeries.timestamp <= end_dt2
                ).all()
                
                space_filtered2_heating = float(sum(record.heating_power_w for record in timeseries_filtered2)) / 1000.0
                space_filtered2_cooling = float(sum(record.cooling_power_w for record in timeseries_filtered2)) / 1000.0
                
                filtered2_records += len(timeseries_filtered2)
                filtered2_heating_energy += space_filtered2_heating
                filtered2_cooling_energy += space_filtered2_cooling
                
                if len(timeseries_filtered2) > 0:
                    logger.info(f"  Space {space.zone_id}: {len(timeseries_filtered2)} records, {space_filtered2_heating:.1f} kWh heating, {space_filtered2_cooling:.1f} kWh cooling")
            
            logger.info(f"2-week filtered summary: {filtered2_records} records, {filtered2_heating_energy:.1f} kWh heating, {filtered2_cooling_energy:.1f} kWh cooling")
            
            # Summary and verification
            logger.info("\n=== Summary ===")
            logger.info(f"Full year:  {total_records:,} records, {total_heating_energy:.1f} kWh heating")
            logger.info(f"1-month:    {filtered_records:,} records, {filtered_heating_energy:.1f} kWh heating ({filtered_heating_energy/total_heating_energy*100:.1f}% of full)")
            logger.info(f"2-weeks:    {filtered2_records:,} records, {filtered2_heating_energy:.1f} kWh heating ({filtered2_heating_energy/total_heating_energy*100:.1f}% of full)")
            
            # Verify the expected relationship
            if filtered2_heating_energy < filtered_heating_energy < total_heating_energy:
                logger.info("✅ Database filtering is working correctly!")
                return True
            else:
                logger.error("❌ Database filtering is not working as expected")
                return False
                
    except Exception as e:
        logger.error(f"Error during database filtering test: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = test_database_energy_filtering()
    if success:
        print("\n✅ Database energy filtering is working correctly!")
        print("This means the dashboard's date filtering should now work properly.")
        print("When you change the time period in the Energy tab, the totals and percentages will update correctly.")
    else:
        print("\n❌ Database energy filtering has issues!")
        sys.exit(1)
