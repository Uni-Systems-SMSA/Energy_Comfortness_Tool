#!/usr/bin/env python3
"""
Update existing database records to have unique sensor_ids that match zone_ids.
"""

import os
import sys
import logging

# Add the parent directory to Python path for imports
sys.path.append(os.path.abspath(os.path.join(__file__, "..")))

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from db.session import SessionLocal
from db.models import EnergySpace

def update_sensor_ids():
    """Update existing spaces to have sensor_id = zone_id."""
    logger.info("Updating existing spaces to have unique sensor_ids...")
    
    try:
        with SessionLocal() as session:
            # Get all spaces
            spaces = session.query(EnergySpace).all()
            logger.info(f"Found {len(spaces)} spaces to update")
            
            updated_count = 0
            for space in spaces:
                if space.sensor_id != space.zone_name:
                    logger.info(f"Updating space '{space.zone_id}': sensor_id '{space.sensor_id}' -> '{space.zone_name}'")
                    space.sensor_id = space.zone_name
                    updated_count += 1
                else:
                    logger.debug(f"Space '{space.zone_id}' already has correct sensor_id")
            
            # Commit the changes
            if updated_count > 0:
                session.commit()
                logger.info(f"✅ Successfully updated {updated_count} spaces")
            else:
                logger.info("✅ All spaces already have correct sensor_ids")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Failed to update sensor_ids: {str(e)}", exc_info=True)
        return False

def verify_update():
    """Verify that all spaces now have unique sensor_ids."""
    logger.info("Verifying sensor_id update...")
    
    try:
        with SessionLocal() as session:
            spaces = session.query(EnergySpace).all()
            
            sensor_ids = [space.sensor_id for space in spaces]
            unique_sensor_ids = set(sensor_ids)
            
            logger.info(f"Total spaces: {len(spaces)}")
            logger.info(f"Unique sensor IDs: {len(unique_sensor_ids)}")
            
            if len(unique_sensor_ids) == len(spaces):
                logger.info("✅ SUCCESS: All spaces now have unique sensor IDs!")
                
                # Show the mapping
                for space in spaces:
                    logger.info(f"   - Zone: '{space.zone_id}' | Sensor: '{space.sensor_id}' | Name: '{space.zone_name}'")
                
                return True
            else:
                logger.error(f"❌ FAILED: Still have duplicate sensor IDs")
                return False
                
    except Exception as e:
        logger.error(f"❌ Verification failed: {str(e)}", exc_info=True)
        return False

if __name__ == "__main__":
    print("🔧 Updating existing database records to have unique sensor_ids...")
    
    # Update the records
    success = update_sensor_ids()
    if not success:
        print("❌ Failed to update sensor_ids!")
        sys.exit(1)
    
    # Verify the update
    success = verify_update()
    if success:
        print("✅ Database update completed successfully!")
        print("💡 Now each space has its own unique sensor_id matching its zone_id")
        print("📊 The Energy tab should now show space-specific data correctly")
    else:
        print("❌ Database update verification failed!")
        sys.exit(1)
