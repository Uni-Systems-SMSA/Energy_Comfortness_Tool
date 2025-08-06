#!/usr/bin/env python3
"""Test the actual wrapper function"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from ece.pipeline_eplus_wrapper import run_eplus_simulation_async

def test_wrapper():
    """Test the wrapper function with fake files"""
    print("Testing EnergyPlus wrapper...")
    
    # Create dummy files for testing
    test_dir = Path("test_simulation")
    test_dir.mkdir(exist_ok=True)
    
    # Create a dummy IFC file
    dummy_ifc = test_dir / "test.ifc"
    dummy_ifc.write_text("# Dummy IFC file for testing\n")
    
    # Create a dummy weather file  
    dummy_epw = test_dir / "test.epw"
    dummy_epw.write_text("LOCATION,Test Location,,,,,,,,,,\n")
    
    print(f"Created dummy files:")
    print(f"  IFC: {dummy_ifc.resolve()}")
    print(f"  EPW: {dummy_epw.resolve()}")
    
    # Test the wrapper function
    try:
        result = run_eplus_simulation_async(
            ifc_file_path=dummy_ifc,
            weather_file_path=dummy_epw,
            sensor_id="test_sensor",
            project_base_dir=test_dir / "results"
        )
        
        print("\nWrapper function result:")
        print(f"Success: {result.get('success', 'unknown')}")
        print(f"Error: {result.get('error', 'none')}")
        
        if not result.get('success'):
            print("\nProcess output:")
            print("STDOUT:", result.get('process_stdout', 'none'))
            print("STDERR:", result.get('process_stderr', 'none'))
            
        return result.get('success', False)
        
    except Exception as e:
        print(f"Exception in wrapper: {e}")
        return False
    
    finally:
        # Cleanup
        import shutil
        if test_dir.exists():
            shutil.rmtree(test_dir, ignore_errors=True)

if __name__ == "__main__":
    success = test_wrapper()
    print(f"\nTest {'PASSED' if success else 'FAILED'}")
