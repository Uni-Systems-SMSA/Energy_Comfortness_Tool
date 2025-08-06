#!/usr/bin/env python3
"""
Test script to verify that date filtering works correctly for energy data visualization.
"""

import sys
import os
import logging
from datetime import datetime, date

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add the parent directory to the Python path to import the dashboard module
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import Streamlit and create mock session state
import streamlit as st

# Create mock session state class
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

# Mock st.session_state
st.session_state = MockSessionState()

# Import dashboard functions
from dashboard.app import _get_energy_data_from_database

def test_date_filtering():
    """Test date filtering functionality for energy data."""
    logger.info("Testing date filtering functionality...")
    
    # Test 1: No date filtering (should get full data)
    logger.info("\n=== Test 1: No date filtering ===")
    st.session_state._data = {}  # Clear session state
    
    energy_data_full = _get_energy_data_from_database()
    
    if energy_data_full:
        full_heating_total = energy_data_full['heating']['total_energy_kwh']
        full_cooling_total = energy_data_full['cooling']['total_energy_kwh']
        full_zones = len(energy_data_full.get('zone_energy', {}))
        
        logger.info(f"Full data - Heating: {full_heating_total:.1f} kWh, Cooling: {full_cooling_total:.1f} kWh")
        logger.info(f"Full data - Zones: {full_zones}")
        logger.info(f"Date filtered: {'Yes' if energy_data_full.get('building_metadata', {}).get('date_filtered') else 'No'}")
    else:
        logger.error("No energy data found - cannot test date filtering")
        return False
    
    # Test 2: Date filtering for 1 month period
    logger.info("\n=== Test 2: Date filtering (1 month) ===")
    st.session_state['start_dt'] = date(2025, 6, 15)
    st.session_state['end_dt'] = date(2025, 7, 15)
    
    energy_data_filtered = _get_energy_data_from_database()
    
    if energy_data_filtered:
        filtered_heating_total = energy_data_filtered['heating']['total_energy_kwh']
        filtered_cooling_total = energy_data_filtered['cooling']['total_energy_kwh']
        filtered_zones = len(energy_data_filtered.get('zone_energy', {}))
        
        logger.info(f"Filtered data - Heating: {filtered_heating_total:.1f} kWh, Cooling: {filtered_cooling_total:.1f} kWh")
        logger.info(f"Filtered data - Zones: {filtered_zones}")
        
        # Check that filtered totals are different (should be less than full year)
        if filtered_heating_total < full_heating_total:
            logger.info("✅ Date filtering working correctly - heating total reduced")
        else:
            logger.warning(f"⚠️ Date filtering may not be working - filtered heating ({filtered_heating_total:.1f}) >= full heating ({full_heating_total:.1f})")
        
        # Check zone-level filtering
        sample_zone_id = list(energy_data_filtered['zone_energy'].keys())[0] if energy_data_filtered['zone_energy'] else None
        if sample_zone_id:
            zone_data = energy_data_filtered['zone_energy'][sample_zone_id]
            logger.info(f"Sample zone '{sample_zone_id}': heating={zone_data['heating_kwh']:.1f} kWh, ts_points={len(zone_data.get('heating_timeseries', []))}")
        
    else:
        logger.error("No filtered energy data found")
        return False
    
    # Test 3: Different date range
    logger.info("\n=== Test 3: Date filtering (2 weeks) ===")
    st.session_state['start_dt'] = date(2025, 7, 1)
    st.session_state['end_dt'] = date(2025, 7, 14)
    
    energy_data_filtered2 = _get_energy_data_from_database()
    
    if energy_data_filtered2:
        filtered2_heating_total = energy_data_filtered2['heating']['total_energy_kwh']
        filtered2_cooling_total = energy_data_filtered2['cooling']['total_energy_kwh']
        
        logger.info(f"2-week filtered data - Heating: {filtered2_heating_total:.1f} kWh, Cooling: {filtered2_cooling_total:.1f} kWh")
        
        # This should be even less than the 1-month filter
        if filtered2_heating_total < filtered_heating_total:
            logger.info("✅ Date filtering working correctly - shorter period shows less energy")
        else:
            logger.warning(f"⚠️ Shorter period filtering may not be working correctly")
        
    else:
        logger.error("No second filtered energy data found")
        return False
    
    logger.info("\n=== Date Filtering Test Summary ===")
    logger.info(f"Full year heating: {full_heating_total:.1f} kWh")
    logger.info(f"1-month heating: {filtered_heating_total:.1f} kWh ({filtered_heating_total/full_heating_total*100:.1f}% of full)")
    logger.info(f"2-week heating: {filtered2_heating_total:.1f} kWh ({filtered2_heating_total/full_heating_total*100:.1f}% of full)")
    
    # Verify the expected relationship
    if filtered2_heating_total < filtered_heating_total < full_heating_total:
        logger.info("✅ All date filtering tests passed!")
        return True
    else:
        logger.error("❌ Date filtering tests failed - energy totals don't follow expected pattern")
        return False

if __name__ == "__main__":
    success = test_date_filtering()
    if success:
        print("\n✅ Date filtering functionality is working correctly!")
    else:
        print("\n❌ Date filtering functionality has issues!")
        sys.exit(1)
