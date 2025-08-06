#!/usr/bin/env python3
"""
Check timestamp intervals in the energy timeseries data.
"""

from db.session import SessionLocal
from db.models import EnergyTimeSeries, EnergySpace, EnergyBuilding
from datetime import datetime, timedelta
import sys

def check_timestamps():
    """Check the timestamp intervals in the latest energy simulation data."""
    session = SessionLocal()
    
    try:
        print("🔍 Checking timestamp intervals in energy timeseries data...")
        print("=" * 70)
        
        # Get the latest building
        latest_building = session.query(EnergyBuilding).order_by(EnergyBuilding.building_id.desc()).first()
        
        if not latest_building:
            print("❌ No buildings found in database")
            return
            
        print(f"📊 Latest Building ID: {latest_building.building_id}")
        print(f"   Simulation time: {latest_building.simulation_timestamp}")
        print(f"   Period: {latest_building.simulation_start} to {latest_building.simulation_end}")
        
        # Get spaces from the latest building
        spaces = session.query(EnergySpace).filter(
            EnergySpace.building_id == latest_building.building_id
        ).all()
        
        print(f"🏠 Checking {len(spaces)} spaces from latest building")
        
        for space in spaces[:2]:  # Check first 2 spaces only
            print(f"\n🔍 Space: {space.zone_name} (ID: {space.space_id})")
            
            # Get first 10 timestamps for this space
            timeseries = session.query(EnergyTimeSeries).filter(
                EnergyTimeSeries.space_id == space.space_id
            ).order_by(EnergyTimeSeries.timestamp).limit(10).all()
            
            if not timeseries:
                print(f"   ❌ No timeseries data found")
                continue
                
            print(f"   📊 Found {len(timeseries)} sample points")
            print(f"   ⏰ First few timestamps:")
            
            prev_timestamp = None
            for i, ts in enumerate(timeseries):
                if prev_timestamp:
                    interval = ts.timestamp - prev_timestamp
                    interval_hours = interval.total_seconds() / 3600
                    print(f"      {i+1}: {ts.timestamp} (Δ={interval_hours:.2f}h)")
                else:
                    print(f"      {i+1}: {ts.timestamp}")
                prev_timestamp = ts.timestamp
                
                if i >= 4:  # Show first 5 points
                    break
            
            # Check if intervals are exactly 1 hour
            if len(timeseries) >= 3:
                first_interval = timeseries[1].timestamp - timeseries[0].timestamp
                second_interval = timeseries[2].timestamp - timeseries[1].timestamp
                
                first_hours = first_interval.total_seconds() / 3600
                second_hours = second_interval.total_seconds() / 3600
                
                if first_hours == 1.0 and second_hours == 1.0:
                    print(f"   ✅ Hourly intervals confirmed (1.00h)")
                else:
                    print(f"   ❌ Non-hourly intervals detected ({first_hours:.2f}h, {second_hours:.2f}h)")
        
        print("\n" + "=" * 70)
        print("✅ Timestamp check completed")
        
    except Exception as e:
        print(f"❌ Error checking timestamps: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()

if __name__ == "__main__":
    check_timestamps()
