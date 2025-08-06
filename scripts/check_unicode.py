#!/usr/bin/env python3
import os
import sys

def check_file_for_unicode(file_path):
    """Check a file for non-ASCII characters and print their positions."""
    print(f"\nChecking file: {file_path}")
    
    if not os.path.exists(file_path):
        print(f"File does not exist: {file_path}")
        return
    
    try:
        with open(file_path, 'rb') as f:
            content = f.read()
        
        non_ascii_found = []
        
        for i, byte in enumerate(content):
            if byte > 127:  # Non-ASCII character
                # Try to decode to see what character it is
                try:
                    char = chr(byte)
                    non_ascii_found.append((i, byte, char))
                except:
                    non_ascii_found.append((i, byte, '?'))
        
        if non_ascii_found:
            print(f"Found {len(non_ascii_found)} non-ASCII characters:")
            for pos, byte_val, char in non_ascii_found[:20]:  # Show first 20
                print(f"  Position {pos}: byte value {byte_val} (0x{byte_val:02x}) = '{char}'")
            if len(non_ascii_found) > 20:
                print(f"  ... and {len(non_ascii_found) - 20} more")
        else:
            print("No non-ASCII characters found")
            
        # Also check filename itself
        filename = os.path.basename(file_path)
        filename_encoded = filename.encode('ascii', errors='ignore').decode('ascii')
        if filename != filename_encoded:
            print(f"Filename contains non-ASCII characters: {filename}")
        else:
            print(f"Filename is ASCII-safe: {filename}")
            
    except Exception as e:
        print(f"Error reading file: {e}")

# Check the specific files mentioned
epw_file = "weather_CERTH Smart House - Living Room_2024_full_year.epw"
ifc_file = "CERTH Smart House - Living Room_20250804_125328.ifc"

# Look for these files in likely directories
for root, dirs, files in os.walk('.'):
    for file in files:
        if file == epw_file or file == ifc_file:
            full_path = os.path.join(root, file)
            check_file_for_unicode(full_path)

# Also check if the specific Unicode character "ffd" exists
print("\n" + "="*60)
print("Searching for specific Unicode character 'ffd' (U+FFFD - replacement character)")

for root, dirs, files in os.walk('.'):
    for file in [f for f in files if f.endswith(('.epw', '.ifc'))]:
        file_path = os.path.join(root, file)
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
                if '\ufffd' in content:
                    print(f"Found replacement character (U+FFFD) in: {file_path}")
                    # Find positions
                    positions = [i for i, c in enumerate(content) if c == '\ufffd']
                    print(f"  Positions: {positions[:10]}")  # Show first 10
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
