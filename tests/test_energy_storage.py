#!/usr/bin/env python3
"""Test energy storage functionality"""

import os
import sys
from pathlib import Path
import logging
from datetime import datetime, timedelta

# Add the project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Import after adding to path
from dashboard.app import _parse_energyplus_outputs, _store_energy_simulation_results

def test_energy_storage():
    print("=" * 60)
    print("🔍 TESTING ENERGY STORAGE")
    print("=" * 60)
    
    # Get the latest simulation results path
    results_dir = r"eplus_sim\results\sim_CERTH Smart House - Living Room_20250801_194432\export\EnergyPlus\SimResults\CERTH Smart House - Living Room_20250801_194426"
    
    print(f"Using results directory: {results_dir}")
    
    # Parse the energy data first
    print("\n📊 STEP 1: Parsing energy data...")
    energy_data = _parse_energyplus_outputs(results_dir)
    
    print(f"✅ Parsed energy data sections: {list(energy_data.keys())}")
    
    if 'zone_energy' in energy_data:
        print(f"✅ Zone energy data found: {len(energy_data['zone_energy'])} zones")
        for zone_id, zone_info in energy_data['zone_energy'].items():
            heating_kwh = zone_info.get('heating_kwh', 0)
            cooling_kwh = zone_info.get('cooling_kwh', 0)
            print(f"   Zone '{zone_id}': H={heating_kwh:.2f}kWh, C={cooling_kwh:.2f}kWh")
    else:
        print("❌ No zone energy data found!")
        return
    
    # Now test storage
    print("\n💾 STEP 2: Testing energy storage...")
    sensor_id = "test_storage_sensor"
    ifc_file_path = "test.ifc"
    epw_file_path = "test.epw"
    
    # Create simulation_results dict with energy_data
    simulation_results = {
        'energy_data': energy_data,
        'eplus_results_path': results_dir,
        'start_dt': datetime.now(),
        'end_dt': datetime.now() + timedelta(hours=8760)
    }
    
    try:
        # Call the storage function with the correct parameters
        success = _store_energy_simulation_results(
            simulation_results=simulation_results,
            sensor_id=sensor_id,
            ifc_file_path=ifc_file_path,
            epw_file_path=epw_file_path
        )
        
        if success:
            print("✅ Energy storage completed successfully!")
        else:
            print("❌ Energy storage failed!")
            
        print(f"✅ Storage function returned: {success}")
        
    except Exception as e:
        print(f"❌ Energy storage failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_energy_storage()
