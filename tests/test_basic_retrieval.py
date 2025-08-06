#!/usr/bin/env python3
"""
Simple test to verify that _get_energy_data_from_database works correctly.
"""

import sys
import os
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Mock streamlit session state to avoid issues
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

def test_basic_retrieval():
    """Test basic energy data retrieval without any date filtering."""
    logger.info("Testing basic energy data retrieval...")
    
    try:
        # Clear session state to ensure no date filtering
        st.session_state._data = {}
        
        # Test retrieval
        energy_data = _get_energy_data_from_database()
        
        if energy_data:
            logger.info("✅ Successfully retrieved energy data")
            logger.info(f"   - Building metadata: {energy_data.get('building_metadata', {}).get('building_id')}")
            logger.info(f"   - Heating total: {energy_data.get('heating', {}).get('total_energy_kwh', 0):.1f} kWh")
            logger.info(f"   - Cooling total: {energy_data.get('cooling', {}).get('total_energy_kwh', 0):.1f} kWh")
            logger.info(f"   - Zone count: {len(energy_data.get('zone_energy', {}))}")
            return True
        else:
            logger.error("❌ No energy data returned from database")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error during basic retrieval test: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = test_basic_retrieval()
    if success:
        print("\n✅ Basic energy data retrieval is working!")
    else:
        print("\n❌ Energy data retrieval is broken!")
        sys.exit(1)
