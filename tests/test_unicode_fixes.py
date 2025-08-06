#!/usr/bin/env python3
"""
Test the updated Unicode handling in the pipeline wrapper.
"""

import sys
from pathlib import Path

# Add the project root to the path
sys.path.append(str(Path(__file__).parent))

from ece.pipeline_eplus_wrapper import run_eplus_simulation_async, test_bim2sim_environment

def test_unicode_fixes():
    """Test the Unicode fixes in the pipeline wrapper"""
    
    print("Testing Unicode fixes in pipeline wrapper...")
    print("=" * 60)
    
    # First test if bim2sim environment is available
    print("1. Testing bim2sim environment availability...")
    bim2sim_available = test_bim2sim_environment()
    
    if bim2sim_available:
        print("✅ bim2sim environment is available")
    else:
        print("❌ bim2sim environment not available")
        print("   Cannot test full pipeline without bim2sim")
        return
    
    # Test file paths that might have Unicode issues
    ifc_file = Path("eplus_sim/models/CERTH Smart House - Living Room_20250804_125328.ifc")
    weather_file = Path("eplus_sim/weather/weather_CERTH Smart House - Living Room_2024_full_year.epw")
    sensor_id = "CERTH Smart House - Living Room"
    project_base_dir = Path("eplus_sim")
    
    print("\n2. Testing file path Unicode handling...")
    print(f"IFC file: {ifc_file}")
    print(f"Weather file: {weather_file}")
    print(f"Sensor ID: {sensor_id}")
    
    # Check if files exist
    if not ifc_file.exists():
        print(f"❌ IFC file not found: {ifc_file}")
        return
    if not weather_file.exists():
        print(f"❌ Weather file not found: {weather_file}")
        return
    
    print("✅ Required files exist")
    
    print("\n3. Testing Unicode sanitization...")
    # Test our sanitization function
    from ece.pipeline_eplus_wrapper import _sanitize_path_for_subprocess
    
    test_strings = [
        str(ifc_file),
        str(weather_file),
        sensor_id,
        "test\ufffdsymbol",  # String with replacement character
        "normal_string",
        "path with spaces"
    ]
    
    for test_str in test_strings:
        sanitized = _sanitize_path_for_subprocess(test_str)
        if test_str != sanitized:
            print(f"   Sanitized: '{test_str}' -> '{sanitized}'")
        else:
            print(f"   No change: '{test_str}'")
    
    print("\n4. Testing command building (dry run)...")
    try:
        # This will build the command and do initial validation but not actually run
        # We'll catch any errors before the subprocess call
        result = run_eplus_simulation_async(
            ifc_file_path=ifc_file,
            weather_file_path=weather_file,
            sensor_id=sensor_id,
            project_base_dir=project_base_dir,
            ep_install_path='C://EnergyPlusV9-4-0/'
        )
        
        print("✅ Command building and execution completed")
        print(f"Result success: {result.get('success', False)}")
        
        if not result.get('success', False):
            error_msg = result.get('error', 'Unknown error')
            print(f"❌ Simulation failed: {error_msg}")
            
            # Check if it's a Unicode-related error
            if 'unicode' in error_msg.lower() or 'ffd' in error_msg.lower():
                print("🔍 UNICODE ERROR DETECTED!")
                print("   This confirms the Unicode issue exists")
            else:
                print("   Error appears to be non-Unicode related")
        else:
            print("✅ Simulation completed successfully!")
            
    except Exception as e:
        print(f"❌ Exception during command execution: {e}")
        if 'unicode' in str(e).lower() or 'ffd' in str(e).lower():
            print("🔍 UNICODE EXCEPTION DETECTED!")
        
    print("\n" + "=" * 60)
    print("Unicode testing completed!")

if __name__ == "__main__":
    test_unicode_fixes()
