#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for EnergyPlus pipeline CLI
"""

import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ece.pipeline_eplus_wrapper import test_bim2sim_environment, run_eplus_simulation_async

def test_bim2sim_env():
    """Test if bim2sim environment is available"""
    print("Testing bim2sim environment...")
    
    result = test_bim2sim_environment()
    
    if result:
        print("✅ bim2sim environment is available and working!")
        return True
    else:
        print("❌ bim2sim environment is not available")
        print("Make sure you have:")
        print("  1. conda installed")
        print("  2. A conda environment named 'bim2sim'")
        print("  3. bim2sim package installed in that environment")
        return False

def test_cli_help():
    """Test the CLI help output"""
    print("\nTesting CLI help output...")
    
    import subprocess
    
    try:
        pipeline_script = Path(__file__).parent / "ece" / "pipeline_eplus.py"
        
        result = subprocess.run([
            "conda", "run", "-n", "bim2sim",
            "python", str(pipeline_script), "--help"
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            print("✅ CLI help works!")
            print("Help output:")
            print(result.stdout)
            return True
        else:
            print("❌ CLI help failed")
            print("Error:", result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ Failed to test CLI: {e}")
        return False

if __name__ == "__main__":
    print("EnergyPlus Pipeline Test")
    print("=" * 40)
    
    # Test 1: Check bim2sim environment
    env_ok = test_bim2sim_env()
    
    if env_ok:
        # Test 2: Check CLI interface
        cli_ok = test_cli_help()
        
        if cli_ok:
            print("\n🎉 All tests passed! The EnergyPlus pipeline is ready to use.")
        else:
            print("\n⚠️ Environment is available but CLI has issues.")
    else:
        print("\n⚠️ Setup required: Please install bim2sim in a conda environment.")
    
    print("\nNext steps:")
    print("1. Upload training data in the Streamlit app")
    print("2. Go to the Energy Comfortness tab")
    print("3. Upload an IFC file and run simulation")
