#!/usr/bin/env python3
"""
Script to test energy data parsing with detailed logging.
"""

import sys
import os
from pathlib import Path
import logging

# Add the project root to Python path
sys.path.append(str(Path(__file__).parent))

# Configure logging to see all debug messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('energy_debug.log')
    ]
)

from dashboard.app import _get_latest_simulation_results, _parse_energyplus_outputs

def test_energy_parsing():
    """Test the energy parsing functionality with detailed logging."""
    
    print("🔍 Testing energy data parsing with detailed logging...")
    print("=" * 60)
    
    # Get the latest simulation results
    simulation_results = _get_latest_simulation_results()
    
    if not simulation_results:
        print("❌ No simulation results found")
        return
    
    print(f"✅ Found simulation results: {simulation_results}")
    
    # Extract the results directory
    if 'eplus_results_path' in simulation_results:
        results_dir = Path(simulation_results['eplus_results_path'])
    elif 'project_path' in simulation_results:
        project_path = Path(simulation_results['project_path'])
        export_dir = project_path / "export" / "EnergyPlus" / "SimResults"
        if export_dir.exists():
            result_dirs = [d for d in export_dir.iterdir() if d.is_dir()]
            if result_dirs:
                results_dir = result_dirs[0]
            else:
                print("❌ No result directories found")
                return
        else:
            print("❌ Export directory not found")
            return
    else:
        print("❌ No valid results path found")
        return
    
    print(f"📂 Using results directory: {results_dir}")
    
    # Parse the energy data with detailed logging
    energy_data = _parse_energyplus_outputs(results_dir)
    
    print("\n" + "=" * 60)
    print("📊 PARSING RESULTS SUMMARY:")
    print("=" * 60)
    
    print(f"Energy data sections: {list(energy_data.keys())}")
    
    if 'heating' in energy_data:
        heating = energy_data['heating']
        print(f"🔥 Heating: {heating['total_energy_kwh']:.1f} kWh, {heating.get('zones_detected', 0)} zones")
    
    if 'cooling' in energy_data:
        cooling = energy_data['cooling']
        print(f"❄️ Cooling: {cooling['total_energy_kwh']:.1f} kWh, {cooling.get('zones_detected', 0)} zones")
    
    if 'zone_energy' in energy_data:
        zone_energy = energy_data['zone_energy']
        print(f"🏠 Zone energy data: {len(zone_energy)} zones")
        for zone_id, zone_data in zone_energy.items():
            heating_kwh = zone_data.get('heating_kwh', 0)
            cooling_kwh = zone_data.get('cooling_kwh', 0)
            heating_ts = len(zone_data.get('heating_timeseries', []))
            cooling_ts = len(zone_data.get('cooling_timeseries', []))
            print(f"   Zone '{zone_id}': H={heating_kwh:.2f}kWh({heating_ts}pts), C={cooling_kwh:.2f}kWh({cooling_ts}pts)")
    else:
        print("❌ No zone energy data found")
    
    if 'space_names' in energy_data:
        space_names = energy_data['space_names']
        print(f"📝 Space names: {len(space_names)} loaded")
        for zone_id, name in list(space_names.items())[:3]:
            print(f"   '{zone_id}' -> '{name}'")
        if len(space_names) > 3:
            print(f"   ... and {len(space_names) - 3} more")
    else:
        print("❌ No space names loaded")
    
    print("\n📝 Check energy_debug.log for detailed logging output")

if __name__ == "__main__":
    test_energy_parsing()
