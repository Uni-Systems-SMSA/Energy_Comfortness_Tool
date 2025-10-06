#!/usr/bin/env python3
"""
Simple test script to debug Unicode issues in bim2sim command line processing.
"""

import sys
import os
from pathlib import Path

def test_unicode_handling():
    """Test Unicode handling in file paths and command line arguments"""
    
    print("Testing Unicode handling in bim2sim pipeline...")
    print("=" * 60)
    
    # Test the exact file paths from your command
    ifc_path = r"C:\Software\github\energy_comfortness_tool\eplus_sim\models\CERTH Smart House - Living Room_20250804_125328.ifc"
    epw_path = r"C:\Software\github\energy_comfortness_tool\eplus_sim\weather\weather_CERTH Smart House - Living Room_2024_full_year.epw"
    sensor_id = "CERTH Smart House - Living Room"
    ep_path = "/usr/local/EnergyPlus-9-4-0"
    project_dir = r"C:\Software\github\energy_comfortness_tool\eplus_sim"
    
    print(f"Testing file paths:")
    print(f"IFC: {ifc_path}")
    print(f"EPW: {epw_path}")
    print(f"Sensor: {sensor_id}")
    print(f"EP Path: {ep_path}")
    print(f"Project Dir: {project_dir}")
    
    # Test encoding of each path
    paths_to_test = [
        ("IFC", ifc_path),
        ("EPW", epw_path), 
        ("Sensor ID", sensor_id),
        ("EP Path", ep_path),
        ("Project Dir", project_dir)
    ]
    
    print("\nTesting encoding compatibility:")
    for name, path in paths_to_test:
        try:
            # Test ASCII encoding
            path.encode('ascii')
            print(f"✅ {name}: ASCII compatible")
        except UnicodeEncodeError as e:
            print(f"❌ {name}: ASCII encoding failed - {e}")
            
        try:
            # Test UTF-8 encoding
            path.encode('utf-8')
            print(f"✅ {name}: UTF-8 compatible")
        except UnicodeEncodeError as e:
            print(f"❌ {name}: UTF-8 encoding failed - {e}")
            
        try:
            # Test Windows CP1252 encoding
            path.encode('cp1252')
            print(f"✅ {name}: CP1252 compatible")
        except UnicodeEncodeError as e:
            print(f"❌ {name}: CP1252 encoding failed - {e}")
    
    # Test file existence
    print("\nTesting file existence:")
    for name, path in [("IFC", ifc_path), ("EPW", epw_path)]:
        if os.path.exists(path):
            print(f"✅ {name}: File exists")
        else:
            print(f"❌ {name}: File not found")
    
    # Test Path object creation
    print("\nTesting Path object creation:")
    try:
        ifc_pathobj = Path(ifc_path)
        print(f"✅ IFC Path object: {ifc_pathobj}")
    except Exception as e:
        print(f"❌ IFC Path object failed: {e}")
        
    try:
        epw_pathobj = Path(epw_path)
        print(f"✅ EPW Path object: {epw_pathobj}")
    except Exception as e:
        print(f"❌ EPW Path object failed: {e}")
    
    # Test sys.argv encoding
    print("\nTesting command line argument encoding:")
    print(f"sys.argv encoding: {sys.stdout.encoding}")
    print(f"File system encoding: {sys.getfilesystemencoding()}")
    print(f"Default encoding: {sys.getdefaultencoding()}")
    
    # Simulate command line arguments
    simulated_args = [
        "pipeline_eplus.py",
        "--ifc", ifc_path,
        "--weather", epw_path,
        "--sensor", sensor_id,
        "--ep-path", ep_path,
        "--project-dir", project_dir
    ]
    
    print(f"\nSimulated sys.argv:")
    for i, arg in enumerate(simulated_args):
        try:
            arg.encode('utf-8')
            print(f"  [{i}] ✅ {arg}")
        except UnicodeEncodeError as e:
            print(f"  [{i}] ❌ {arg} - {e}")
    
    # Test bim2sim import with error handling
    print("\nTesting bim2sim import:")
    try:
        import bim2sim
        print(f"✅ bim2sim imported successfully: {bim2sim.__version__ if hasattr(bim2sim, '__version__') else 'version unknown'}")
        
        # Test specific bim2sim components
        try:
            from bim2sim import Project, run_project, ConsoleDecisionHandler
            from bim2sim.utilities.types import IFCDomain
            print("✅ bim2sim components imported successfully")
        except ImportError as e:
            print(f"❌ bim2sim component import failed: {e}")
            
    except ImportError as e:
        print(f"❌ bim2sim import failed: {e}")
    
    print("\n" + "=" * 60)
    print("Unicode testing completed!")

if __name__ == "__main__":
    test_unicode_handling()
