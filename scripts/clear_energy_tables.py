#!/usr/bin/env python3
"""
Clear all energy database tables.
"""

from db.session import SessionLocal
from db.models import EnergyTimeSeries, EnergySpace, EnergyBuilding
import sys

def clear_energy_tables():
    """Clear all records from the three energy tables."""
    session = SessionLocal()
    
    try:
        print("🗑️ Clearing all energy database tables...")
        print("=" * 50)
        
        # Get counts before deletion
        timeseries_count = session.query(EnergyTimeSeries).count()
        spaces_count = session.query(EnergySpace).count()
        buildings_count = session.query(EnergyBuilding).count()
        
        print(f"📊 Records before deletion:")
        print(f"   - EnergyTimeSeries: {timeseries_count}")
        print(f"   - EnergySpace: {spaces_count}")
        print(f"   - EnergyBuilding: {buildings_count}")
        print()
        
        if timeseries_count == 0 and spaces_count == 0 and buildings_count == 0:
            print("✅ All tables are already empty")
            return
        
        # Delete in correct order (foreign key constraints)
        print("🗑️ Deleting records...")
        
        # 1. Delete timeseries data first (references spaces)
        if timeseries_count > 0:
            deleted_ts = session.query(EnergyTimeSeries).delete()
            print(f"   ✅ Deleted {deleted_ts} EnergyTimeSeries records")
        
        # 2. Delete spaces (references buildings)
        if spaces_count > 0:
            deleted_spaces = session.query(EnergySpace).delete()
            print(f"   ✅ Deleted {deleted_spaces} EnergySpace records")
        
        # 3. Delete buildings last
        if buildings_count > 0:
            deleted_buildings = session.query(EnergyBuilding).delete()
            print(f"   ✅ Deleted {deleted_buildings} EnergyBuilding records")
        
        # Commit the changes
        session.commit()
        
        print("\n" + "=" * 50)
        print("✅ All energy tables cleared successfully!")
        
        # Verify deletion
        final_timeseries = session.query(EnergyTimeSeries).count()
        final_spaces = session.query(EnergySpace).count()
        final_buildings = session.query(EnergyBuilding).count()
        
        print(f"📊 Records after deletion:")
        print(f"   - EnergyTimeSeries: {final_timeseries}")
        print(f"   - EnergySpace: {final_spaces}")
        print(f"   - EnergyBuilding: {final_buildings}")
        
    except Exception as e:
        print(f"❌ Error clearing tables: {e}")
        session.rollback()
        import traceback
        traceback.print_exc()
    finally:
        session.close()

if __name__ == "__main__":
    # Ask for confirmation
    response = input("⚠️ This will delete ALL energy data. Are you sure? (yes/no): ")
    if response.lower() in ['yes', 'y']:
        clear_energy_tables()
    else:
        print("❌ Operation cancelled")
