#!/usr/bin/env python3
"""Test space.csv loading specifically"""

import os
import sys
from pathlib import Path
import logging

# Add the project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Import after adding to path
from dashboard.app import _load_space_names_from_csv

def test_space_csv_loading():
    print("=" * 60)
    print("🔍 TESTING SPACE.CSV LOADING")
    print("=" * 60)
    
    # Get the latest simulation results path
    eplus_results_path = r"eplus_sim\results\sim_CERTH Smart House - Living Room_20250801_194432\export\EnergyPlus\SimResults\CERTH Smart House - Living Room_20250801_194426"
    
    print(f"Using EnergyPlus results path: {eplus_results_path}")
    
    # Test the function
    space_mapping = _load_space_names_from_csv(eplus_results_path)
    
    print(f"Results: {len(space_mapping)} space mappings loaded")
    if space_mapping:
        print("Space mappings:")
        for zone_id, space_name in space_mapping.items():
            print(f"  '{zone_id}' -> '{space_name}'")
    else:
        print("❌ No space mappings loaded!")
    
    # Also manually check the file
    results_dir = Path(eplus_results_path)
    export_dir = results_dir.parent.parent.parent
    space_csv_path = export_dir / "space.csv"
    
    print(f"\nManual file check:")
    print(f"  Expected path: {space_csv_path}")
    print(f"  File exists: {space_csv_path.exists()}")
    
    if space_csv_path.exists():
        import pandas as pd
        df = pd.read_csv(space_csv_path)
        print(f"  Rows: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        if len(df) > 0:
            print(f"  Sample zone IDs: {df.iloc[:3, 1].tolist()}")

if __name__ == "__main__":
    test_space_csv_loading()
