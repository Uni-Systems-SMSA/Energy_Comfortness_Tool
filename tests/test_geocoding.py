#!/usr/bin/env python3
"""
Test script for the new geocoding functionality in EPW header generation.
"""

import sys
from pathlib import Path

# Add the project root to the path
sys.path.append(str(Path(__file__).parent))

from ece.pipeline_weather import get_location_info, create_epw_header

def test_geocoding():
    """Test the geocoding functionality with various coordinates."""
    
    print("Testing geocoding functionality...\n")
    
    # Test coordinates (Thessaloniki, Greece)
    test_coords = [
        (40.6401, 22.9444, "Thessaloniki, Greece"),
        (52.5200, 13.4050, "Berlin, Germany"), 
        (40.7128, -74.0060, "New York, USA"),
        (35.6762, 139.6503, "Tokyo, Japan"),
        (0.0, 0.0, "Null Island (Ocean)"),
    ]
    
    for lat, lon, description in test_coords:
        print(f"Testing coordinates: {lat:.4f}, {lon:.4f} ({description})")
        
        try:
            # Test location info retrieval
            location_info = get_location_info(lat, lon)
            print(f"  Result: {location_info}")
            
            # Test EPW header generation
            header_lines = create_epw_header(
                latitude=lat,
                longitude=lon,
                data_source="Test API"
            )
            
            # Print the LOCATION line
            location_line = header_lines[0].strip()
            print(f"  EPW LOCATION: {location_line}")
            
            # Validate the LOCATION line has correct number of fields
            fields = location_line.split(',')
            if len(fields) == 10:
                print(f"  ✅ LOCATION header has correct 10 fields")
            else:
                print(f"  ❌ LOCATION header has {len(fields)} fields, expected 10")
                print(f"     Fields: {fields}")
            
        except Exception as e:
            print(f"  ❌ Error: {e}")
        
        print()

if __name__ == "__main__":
    test_geocoding()
