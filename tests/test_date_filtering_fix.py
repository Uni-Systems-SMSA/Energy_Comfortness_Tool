#!/usr/bin/env python3
"""
Test the decimal handling fix for date filtering.
"""

import sys
import os
import logging
from datetime import date

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

def test_date_filtering_fix():
    """Test date filtering with decimal handling fix."""
    logger.info("Testing date filtering with decimal handling fix...")
    
    try:
        # Set up date filtering that should trigger the decimal conversion
        st.session_state['start_dt'] = date(2024, 1, 1)
        st.session_state['end_dt'] = date(2024, 10, 31)
        
        logger.info(f"Testing with date range: {st.session_state['start_dt']} to {st.session_state['end_dt']}")
        
        # Test retrieval with date filtering
        energy_data = _get_energy_data_from_database(sensor_id="CERTH Smart House - Living Room")
        
        if energy_data:
            logger.info("✅ SUCCESS: Retrieved energy data with date filtering")
            logger.info(f"   - Building ID: {energy_data.get('building_metadata', {}).get('building_id')}")
            logger.info(f"   - Heating total: {energy_data.get('heating', {}).get('total_energy_kwh', 0):.1f} kWh")
            logger.info(f"   - Cooling total: {energy_data.get('cooling', {}).get('total_energy_kwh', 0):.1f} kWh")
            logger.info(f"   - Zone count: {len(energy_data.get('zone_energy', {}))}")
            logger.info(f"   - Date filtered: Yes")
            return True
        else:
            logger.error("❌ No energy data returned")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error during date filtering test: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = test_date_filtering_fix()
    if success:
        print("\n✅ Date filtering with decimal handling is working!")
    else:
        print("\n❌ Date filtering is still broken!")
        sys.exit(1)
