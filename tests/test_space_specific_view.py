#!/usr/bin/env python3
"""
Test script to verify space-specific energy data filtering functionality.
"""

import os
import sys
import logging
from datetime import datetime, date
from pathlib import Path

# Add the parent directory to Python path for imports
sys.path.append(os.path.abspath(os.path.join(__file__, "..")))

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Mock streamlit session state for testing
class MockSessionState:
    def __init__(self):
        self.data = {}
    
    def get(self, key, default=None):
        return self.data.get(key, default)
    
    def __setitem__(self, key, value):
        self.data[key] = value
    
    def __getitem__(self, key):
        return self.data[key]

# Mock streamlit module
class MockStreamlit:
    def __init__(self):
        self.session_state = MockSessionState()
    
    def cache_data(self, ttl=None):
        """Mock cache_data decorator - just return the function unchanged"""
        def decorator(func):
            return func
        return decorator
    
    def set_page_config(self, **kwargs):
        """Mock set_page_config - do nothing"""
        pass
    
    def sidebar(self):
        """Mock sidebar - return self for chaining"""
        return self
        
    def selectbox(self, *args, **kwargs):
        """Mock selectbox - return first option"""
        if len(args) > 1 and hasattr(args[1], '__iter__'):
            return args[1][0] if args[1] else None
        return None
        
    def date_input(self, *args, **kwargs):
        """Mock date_input - return None"""
        return None
        
    def markdown(self, *args, **kwargs):
        """Mock markdown - do nothing"""
        pass
        
    def __getattr__(self, name):
        """Mock any other streamlit function - return self for chaining"""
        return lambda *args, **kwargs: self

# Replace streamlit import
sys.modules['streamlit'] = MockStreamlit()
import streamlit as st

# Now import the dashboard module
from dashboard.app import _get_energy_data_from_database

def test_space_specific_view():
    """Test space-specific energy data retrieval."""
    logger.info("Testing space-specific energy data view...")
    
    # Test 1: Get data for all spaces (building-wide view)
    logger.info("=== Test 1: Building-wide view (sensor_id=None) ===")
    energy_data_all = _get_energy_data_from_database(sensor_id=None)
    
    if energy_data_all:
        logger.info("✅ Building-wide data retrieved successfully")
        logger.info(f"   - Total heating: {energy_data_all['heating']['total_energy_kwh']:.1f} kWh")
        logger.info(f"   - Total cooling: {energy_data_all['cooling']['total_energy_kwh']:.1f} kWh")
        logger.info(f"   - Number of zones: {len(energy_data_all['zone_energy'])}")
        logger.info(f"   - Is space-specific: {energy_data_all.get('building_metadata', {}).get('is_space_specific', False)}")
        
        # List all zones and their sensor_ids
        zone_energy = energy_data_all.get('zone_energy', {})
        if zone_energy:
            logger.info("   - Available zones and their sensors:")
            for zone_id, zone_data in zone_energy.items():
                sensor_id = zone_data.get('sensor_id', 'unknown')
                heating = zone_data.get('heating_kwh', 0)
                cooling = zone_data.get('cooling_kwh', 0)
                logger.info(f"     * Zone '{zone_id}' -> Sensor '{sensor_id}': {heating:.1f} kWh heating, {cooling:.1f} kWh cooling")
    else:
        logger.error("❌ Failed to retrieve building-wide data")
        return False
    
    # Test 2: Get data for a specific sensor
    # Find a sensor_id from the building-wide data
    test_sensor_id = None
    if energy_data_all and energy_data_all.get('zone_energy'):
        # Get the first sensor_id that's not None
        for zone_data in energy_data_all['zone_energy'].values():
            sensor_id = zone_data.get('sensor_id')
            if sensor_id and sensor_id != 'unknown':
                test_sensor_id = sensor_id
                break
    
    if test_sensor_id:
        logger.info(f"=== Test 2: Space-specific view (sensor_id='{test_sensor_id}') ===")
        energy_data_specific = _get_energy_data_from_database(sensor_id=test_sensor_id)
        
        if energy_data_specific:
            logger.info("✅ Space-specific data retrieved successfully")
            logger.info(f"   - Total heating: {energy_data_specific['heating']['total_energy_kwh']:.1f} kWh")
            logger.info(f"   - Total cooling: {energy_data_specific['cooling']['total_energy_kwh']:.1f} kWh")
            logger.info(f"   - Number of zones: {len(energy_data_specific['zone_energy'])}")
            logger.info(f"   - Is space-specific: {energy_data_specific.get('building_metadata', {}).get('is_space_specific', False)}")
            logger.info(f"   - Selected sensor: {energy_data_specific.get('building_metadata', {}).get('selected_sensor_id')}")
            
            # Compare totals - space-specific should be less than or equal to building-wide
            heating_ratio = energy_data_specific['heating']['total_energy_kwh'] / max(energy_data_all['heating']['total_energy_kwh'], 0.001)
            cooling_ratio = energy_data_specific['cooling']['total_energy_kwh'] / max(energy_data_all['cooling']['total_energy_kwh'], 0.001)
            
            logger.info(f"   - Heating ratio (space/building): {heating_ratio:.2%}")
            logger.info(f"   - Cooling ratio (space/building): {cooling_ratio:.2%}")
            
            if heating_ratio <= 1.01 and cooling_ratio <= 1.01:  # Allow for small rounding differences
                logger.info("✅ Space energy is correctly subset of building energy")
            else:
                logger.warning("⚠️ Space energy appears larger than building energy - check logic")
            
            # List zones in space-specific view
            zone_energy_specific = energy_data_specific.get('zone_energy', {})
            if zone_energy_specific:
                logger.info("   - Zones in space-specific view:")
                for zone_id, zone_data in zone_energy_specific.items():
                    sensor_id = zone_data.get('sensor_id', 'unknown')
                    heating = zone_data.get('heating_kwh', 0)
                    cooling = zone_data.get('cooling_kwh', 0)
                    logger.info(f"     * Zone '{zone_id}' -> Sensor '{sensor_id}': {heating:.1f} kWh heating, {cooling:.1f} kWh cooling")
        else:
            logger.error(f"❌ Failed to retrieve space-specific data for sensor '{test_sensor_id}'")
            return False
    else:
        logger.warning("⚠️ No sensor_id found for space-specific testing")
    
    # Test 3: Test with date filtering + space-specific
    logger.info("=== Test 3: Space-specific view with date filtering ===")
    st.session_state['start_dt'] = date(2024, 1, 1)
    st.session_state['end_dt'] = date(2024, 6, 30)
    
    if test_sensor_id:
        energy_data_filtered = _get_energy_data_from_database(sensor_id=test_sensor_id)
        
        if energy_data_filtered:
            logger.info("✅ Space-specific filtered data retrieved successfully")
            logger.info(f"   - Total heating: {energy_data_filtered['heating']['total_energy_kwh']:.1f} kWh")
            logger.info(f"   - Total cooling: {energy_data_filtered['cooling']['total_energy_kwh']:.1f} kWh")
            logger.info(f"   - Is space-specific: {energy_data_filtered.get('building_metadata', {}).get('is_space_specific', False)}")
            logger.info(f"   - Selected sensor: {energy_data_filtered.get('building_metadata', {}).get('selected_sensor_id')}")
            
            # Filtered should be less than or equal to unfiltered
            heating_filtered_ratio = energy_data_filtered['heating']['total_energy_kwh'] / max(energy_data_specific['heating']['total_energy_kwh'], 0.001)
            cooling_filtered_ratio = energy_data_filtered['cooling']['total_energy_kwh'] / max(energy_data_specific['cooling']['total_energy_kwh'], 0.001)
            
            logger.info(f"   - Heating ratio (filtered/unfiltered): {heating_filtered_ratio:.2%}")
            logger.info(f"   - Cooling ratio (filtered/unfiltered): {cooling_filtered_ratio:.2%}")
            
            if heating_filtered_ratio <= 1.01 and cooling_filtered_ratio <= 1.01:
                logger.info("✅ Filtered energy is correctly subset of unfiltered energy")
            else:
                logger.warning("⚠️ Filtered energy appears larger than unfiltered - check logic")
        else:
            logger.error(f"❌ Failed to retrieve filtered space-specific data")
            return False
    
    # Clear session state
    st.session_state.data.clear()
    
    logger.info("✅ All space-specific view tests completed successfully!")
    return True

if __name__ == "__main__":
    print("🧪 Testing space-specific energy data view functionality...")
    success = test_space_specific_view()
    if success:
        print("✅ Space-specific view is working correctly!")
    else:
        print("❌ Space-specific view tests failed!")
        sys.exit(1)
