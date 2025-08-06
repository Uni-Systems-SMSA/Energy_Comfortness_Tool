#!/usr/bin/env python3
"""
Test the sensor_id handling fix for _get_energy_data_from_database.
"""

import sys
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Mock streamlit session state
class MockSessionState:
    def __init__(self):
        self._data = {}
    
    def get(self, key, default=None):
        return self._data.get(key, default)
    
    def __setitem__(self, key, value):
        self._data[key] = value
        
    def __getitem__(self, key):
        return self._data[key]
    
    def __contains__(self, key):
        return key in self._data

# Import streamlit and mock session state
import streamlit as st
st.session_state = MockSessionState()

# Import the function to test
from dashboard.app import _get_energy_data_from_database

def test_sensor_id_variations():
    """Test different sensor_id variations."""
    logger.info("Testing different sensor_id variations...")
    
    test_cases = [
        (None, "No sensor_id (should get latest)"),
        ("latest", "sensor_id='latest' (should get latest)"),
        ("nonexistent", "Nonexistent sensor_id (should return None)"),
    ]
    
    for sensor_id, description in test_cases:
        logger.info(f"\n--- Testing: {description} ---")
        try:
            st.session_state._data = {}  # Clear session state
            energy_data = _get_energy_data_from_database(sensor_id=sensor_id)
            
            if energy_data:
                logger.info(f"✅ SUCCESS: Retrieved energy data")
                logger.info(f"   - Building ID: {energy_data.get('building_metadata', {}).get('building_id')}")
                logger.info(f"   - Total energy: {energy_data.get('heating', {}).get('total_energy_kwh', 0) + energy_data.get('cooling', {}).get('total_energy_kwh', 0):.1f} kWh")
            else:
                logger.info(f"❌ No data returned for sensor_id: {sensor_id}")
                
        except Exception as e:
            logger.error(f"❌ Error with sensor_id '{sensor_id}': {e}", exc_info=True)
    
    return True

if __name__ == "__main__":
    test_sensor_id_variations()
    print("\n✅ Sensor ID variation testing completed!")
