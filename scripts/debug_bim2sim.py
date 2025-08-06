#!/usr/bin/env python3
"""Test script to debug bim2sim import issues"""

import sys
import os
from pathlib import Path

print("Python executable:", sys.executable)
print("Python version:", sys.version)
print("Working directory:", os.getcwd())
print("Python path:")
for p in sys.path:
    print(f"  {p}")

print("\nTrying to import bim2sim...")
try:
    import bim2sim
    print("✅ bim2sim imported successfully!")
    print(f"bim2sim location: {bim2sim.__file__}")
    print(f"bim2sim version: {getattr(bim2sim, '__version__', 'unknown')}")
except ImportError as e:
    print(f"❌ Failed to import bim2sim: {e}")
    print("\nChecking if conda environment is activated...")
    print(f"CONDA_DEFAULT_ENV: {os.environ.get('CONDA_DEFAULT_ENV', 'None')}")
    print(f"CONDA_PREFIX: {os.environ.get('CONDA_PREFIX', 'None')}")
