#!/usr/bin/env python3
"""
Script to check the existence of records in energy-related database tables.
"""

import sys
from pathlib import Path

# Add the project root to Python path
sys.path.append(str(Path(__file__).parent))

from db.session import SessionLocal
from db.models import EnergyBuilding, EnergySpace, EnergyTimeSeries

def check_energy_tables():
    """Check for records in energy-related database tables."""
    
    try:
        with SessionLocal() as session:
            print("🔍 Checking energy database tables...")
            print("=" * 50)
            
            # Check EnergyBuilding table
            building_count = session.query(EnergyBuilding).count()
            print(f"📊 EnergyBuilding records: {building_count}")
            
            if building_count > 0:
                # Get details of the most recent building
                latest_building = session.query(EnergyBuilding).order_by(
                    EnergyBuilding.simulation_timestamp.desc()
                ).first()
                
                print(f"   Latest simulation: {latest_building.simulation_timestamp}")
                print(f"   Building ID: {latest_building.building_id}")
                print(f"   Total energy: {latest_building.total_energy_kwh:.1f} kWh")
                print(f"   Zones count: {latest_building.zones_count}")
                print(f"   IFC file: {Path(latest_building.ifc_file_path).name}")
                print(f"   Weather file: {Path(latest_building.weather_file_path).name}")
            
            print()
            
            # Check EnergySpace table
            space_count = session.query(EnergySpace).count()
            print(f"🏠 EnergySpace records: {space_count}")
            
            if space_count > 0:
                # Get sample spaces
                sample_spaces = session.query(EnergySpace).limit(3).all()
                print("   Sample spaces:")
                for space in sample_spaces:
                    print(f"     - Zone '{space.zone_id}' ({space.zone_name}): {space.total_kwh:.1f} kWh")
                
                # Check if there are multiple buildings
                distinct_buildings = session.query(EnergySpace.building_id).distinct().count()
                print(f"   Spaces belong to {distinct_buildings} building(s)")
            
            print()
            
            # Check EnergyTimeSeries table
            timeseries_count = session.query(EnergyTimeSeries).count()
            print(f"⏰ EnergyTimeSeries records: {timeseries_count}")
            
            if timeseries_count > 0:
                # Get time range info
                earliest = session.query(EnergyTimeSeries.timestamp).order_by(
                    EnergyTimeSeries.timestamp.asc()
                ).first()[0]
                
                latest = session.query(EnergyTimeSeries.timestamp).order_by(
                    EnergyTimeSeries.timestamp.desc()
                ).first()[0]
                
                print(f"   Time range: {earliest} to {latest}")
                
                # Count distinct spaces with timeseries data
                distinct_spaces = session.query(EnergyTimeSeries.space_id).distinct().count()
                print(f"   Data for {distinct_spaces} space(s)")
                
                # Sample some data points
                sample_data = session.query(EnergyTimeSeries).limit(3).all()
                print("   Sample data points:")
                for data in sample_data:
                    print(f"     - {data.timestamp}: H={data.heating_power_w}W, C={data.cooling_power_w}W")
            
            print()
            print("=" * 50)
            
            # Summary
            if building_count == 0 and space_count == 0 and timeseries_count == 0:
                print("❌ No energy simulation data found in database")
                print("💡 Run an energy simulation to populate these tables")
            elif building_count > 0 and space_count == 0:
                print("⚠️  Buildings exist but no spaces found")
                print("💡 This suggests an issue with space data storage")
            elif building_count > 0 and space_count > 0 and timeseries_count == 0:
                print("⚠️  Buildings and spaces exist but no timeseries data")
                print("💡 This suggests an issue with timeseries data storage")
            else:
                print("✅ Energy simulation data found in database")
                print(f"   {building_count} building(s), {space_count} space(s), {timeseries_count} timeseries point(s)")
            
    except Exception as e:
        print(f"❌ Error checking database: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_energy_tables()
