#!/usr/bin/env python3
"""
Test script to verify Overall Comfort calculation functionality.

This script tests the _calculate_overall_comfort function with sample data.
"""

import os
import sys
import pandas as pd
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the function from dashboard.app
from dashboard.app import _calculate_overall_comfort

def test_overall_comfort_calculation():
    """Test the overall comfort calculation with various scenarios."""
    
    print("Testing Overall Comfort Calculation...")
    print("=" * 50)
    
    # Test Case 1: All comfort classes available (best case)
    print("\n1. Test Case: All comfort classes 'A' (best comfort)")
    test_df1 = pd.DataFrame({
        'thermal_class': ['A', 'A', 'A'],
        'acoustic_class': ['A', 'A', 'A'],
        'visual_class': ['A', 'A', 'A'],
        'co2_ppm_class': ['A', 'A', 'A'],
        'co_ppm_class': ['A', 'A', 'A'],
        'tvoc_ppb_class': ['A', 'A', 'A'],
        'pm2_5_ugm3_class': ['A', 'A', 'A'],
        'pm10_ugm3_class': ['A', 'A', 'A'],
    })
    
    result1 = _calculate_overall_comfort(test_df1)
    print(f"Overall Comfort Scores: {result1.tolist()}")
    print(f"Expected: [4.0, 4.0, 4.0] (all A's should give maximum score of 4)")
    print(f"Average: {result1.mean():.2f}")
    
    # Test Case 2: Mixed comfort classes
    print("\n2. Test Case: Mixed comfort classes")
    test_df2 = pd.DataFrame({
        'thermal_class': ['A', 'B', 'C'],
        'acoustic_class': ['B', 'C', 'D'],
        'visual_class': ['A', 'A', 'B'],
        'co2_ppm_class': ['A', 'B', 'C'],
        'co_ppm_class': ['A', 'A', 'B'],
    })
    
    result2 = _calculate_overall_comfort(test_df2)
    print(f"Overall Comfort Scores: {[f'{x:.2f}' for x in result2.tolist()]}")
    print(f"Average: {result2.mean():.2f}")
    
    # Show the calculation breakdown for the first row
    print("\nCalculation breakdown for first row:")
    print("Thermal (A=4) * weight(1.0) = 4.0")
    print("Acoustic (B=3) * weight(0.6) = 1.8")
    print("Visual (A=4) * weight(0.6) = 2.4")
    print("CO2 (A=4) * weight(0.2) = 0.8")
    print("CO (A=4) * weight(0.2) = 0.8")
    print("Total weighted sum = 9.8")
    print("Total weights = 2.6")
    print(f"Overall comfort = 9.8/2.6 = {9.8/2.6:.2f}")
    
    # Test Case 3: Partial data (some classes missing)
    print("\n3. Test Case: Only thermal and acoustic data available")
    test_df3 = pd.DataFrame({
        'thermal_class': ['A', 'B', 'C'],
        'acoustic_class': ['A', 'B', 'C'],
        # Other classes missing
    })
    
    result3 = _calculate_overall_comfort(test_df3)
    print(f"Overall Comfort Scores: {[f'{x:.2f}' for x in result3.tolist()]}")
    print(f"Average: {result3.mean():.2f}")
    print("(Should still work with missing data, adjusting weights accordingly)")
    
    # Test Case 4: Some NaN values
    print("\n4. Test Case: Some NaN/missing values")
    test_df4 = pd.DataFrame({
        'thermal_class': ['A', np.nan, 'B'],
        'acoustic_class': ['A', 'B', np.nan],
        'visual_class': ['A', 'A', 'A'],
    })
    
    result4 = _calculate_overall_comfort(test_df4)
    print(f"Overall Comfort Scores: {[f'{x:.2f}' if not pd.isna(x) else 'NaN' for x in result4.tolist()]}")
    print("(Should handle NaN values gracefully)")
    
    # Test Case 5: All missing data
    print("\n5. Test Case: No comfort data available")
    test_df5 = pd.DataFrame({
        'some_other_column': ['A', 'B', 'C'],
        # No comfort class columns
    })
    
    result5 = _calculate_overall_comfort(test_df5)
    print(f"Overall Comfort Scores: {[f'{x:.2f}' if not pd.isna(x) else 'NaN' for x in result5.tolist()]}")
    print("(Should return NaN when no comfort data is available)")
    
    print("\n" + "=" * 50)
    print("✅ Overall Comfort calculation tests completed!")
    
    return True

if __name__ == "__main__":
    test_overall_comfort_calculation()
