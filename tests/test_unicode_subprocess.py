#!/usr/bin/env python3
"""
Test script to reproduce and debug the Unicode error in bim2sim subprocess.
"""

import subprocess
import sys
from pathlib import Path

def test_unicode_handling():
    """Test subprocess with potential Unicode issues"""
    
    # Find the actual files
    epw_files = list(Path('.').glob('**/weather_CERTH*.epw'))
    ifc_files = list(Path('.').glob('**/CERTH*.ifc'))
    
    print(f"Found EPW files: {epw_files}")
    print(f"Found IFC files: {ifc_files}")
    
    if not epw_files or not ifc_files:
        print("Required files not found")
        return
    
    epw_file = epw_files[0]
    ifc_file = ifc_files[0]
    
    print(f"\nTesting file paths for Unicode issues:")
    print(f"EPW: {epw_file}")
    print(f"IFC: {ifc_file}")
    
    # Check if paths contain non-ASCII characters
    for file_path in [epw_file, ifc_file]:
        path_str = str(file_path)
        try:
            path_str.encode('ascii')
            print(f"✅ {file_path.name} - ASCII compatible path")
        except UnicodeEncodeError as e:
            print(f"❌ {file_path.name} - Non-ASCII characters in path: {e}")
    
    # Test basic conda command with Unicode handling
    test_commands = [
        # Test basic conda environment
        ["conda", "info", "--envs"],
        
        # Test bim2sim environment specifically  
        ["conda", "run", "-n", "bim2sim", "python", "-c", "print('Hello from bim2sim')"],
        
        # Test with file paths
        ["conda", "run", "-n", "bim2sim", "python", "-c", f"print('EPW: {epw_file}')"],
        ["conda", "run", "-n", "bim2sim", "python", "-c", f"print('IFC: {ifc_file}')"],
    ]
    
    for i, cmd in enumerate(test_commands):
        print(f"\n--- Test {i+1}: {' '.join(cmd[:4])}... ---")
        
        try:
            # Test with different encoding strategies
            for encoding_strategy in [
                {"encoding": "utf-8", "errors": "strict"},
                {"encoding": "utf-8", "errors": "replace"},
                {"encoding": "cp1252", "errors": "replace"},  # Windows default
                {"encoding": None},  # Use system default
            ]:
                print(f"  Testing with encoding: {encoding_strategy}")
                
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        **encoding_strategy
                    )
                    
                    if result.returncode == 0:
                        print(f"    ✅ Success with {encoding_strategy}")
                        if result.stdout.strip():
                            print(f"    Output: {result.stdout.strip()[:100]}...")
                        break
                    else:
                        print(f"    ❌ Failed with return code {result.returncode}")
                        if result.stderr:
                            error_msg = result.stderr.strip()[:200]
                            print(f"    Error: {error_msg}")
                            
                            # Check for specific Unicode error patterns
                            if 'unicode' in error_msg.lower() or 'ffd' in error_msg.lower():
                                print(f"    🔍 UNICODE ERROR DETECTED: {error_msg}")
                        
                except UnicodeDecodeError as e:
                    print(f"    ❌ UnicodeDecodeError with {encoding_strategy}: {e}")
                except Exception as e:
                    print(f"    ❌ Other error with {encoding_strategy}: {e}")
                    
        except Exception as e:
            print(f"  ❌ Command failed completely: {e}")

if __name__ == "__main__":
    test_unicode_handling()
