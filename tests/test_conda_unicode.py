#!/usr/bin/env python3
"""
Minimal test to reproduce Unicode error with conda subprocess.
"""

import subprocess
import sys

def test_conda_unicode():
    """Test conda subprocess with potential Unicode issues"""
    
    print("Testing conda subprocess Unicode handling...")
    
    # The exact command that's failing
    cmd = [
        "conda", "run", "-n", "bim2sim", 
        "python", "-c", "print('Testing Unicode: \\u00e1\\u00e9\\u00ed\\u00f3\\u00fa')"
    ]
    
    print(f"Command: {' '.join(cmd)}")
    
    try:
        # Test different encoding strategies
        for encoding_strategy in [
            {"encoding": "utf-8", "errors": "strict"},
            {"encoding": "utf-8", "errors": "replace"},
            {"encoding": "cp1252", "errors": "replace"},
        ]:
            print(f"\nTesting with {encoding_strategy}:")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                **encoding_strategy
            )
            
            print(f"Return code: {result.returncode}")
            if result.stdout:
                print(f"Stdout: {result.stdout.strip()}")
            if result.stderr:
                print(f"Stderr: {result.stderr.strip()}")
                
            if result.returncode == 0:
                print("✅ Success!")
                break
            else:
                print("❌ Failed")
                
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    test_conda_unicode()
