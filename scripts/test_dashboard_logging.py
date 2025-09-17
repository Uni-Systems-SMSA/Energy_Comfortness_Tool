#!/usr/bin/env python3
"""
Test script to verify that dashboard logging is working correctly.

This script:
1. Tests the logging setup
2. Creates sample log entries
3. Verifies log files are created
4. Shows log file locations

Usage:
    python scripts/test_dashboard_logging.py
"""

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_dashboard_logging():
    """Test that dashboard logging is working correctly."""
    print("🧪 Testing Dashboard Logging Setup")
    print("=" * 50)
    
    try:
        # Import and test the logging setup
        from ece.utils.logging import get_logger
        
        # Create a test logger (similar to dashboard)
        logger = get_logger("dashboard.app")
        
        # Test different log levels
        logger.info("✅ Testing INFO level logging")
        logger.warning("⚠️ Testing WARNING level logging")
        logger.error("❌ Testing ERROR level logging")
        logger.debug("🔍 Testing DEBUG level logging (may not appear if level is INFO)")
        
        # Check if log files were created
        logs_dir = Path("logs")
        log_file = logs_dir / "dashboard.app.log"
        
        print(f"\n📁 Log Directory: {logs_dir.absolute()}")
        print(f"📄 Expected Log File: {log_file.absolute()}")
        
        if log_file.exists():
            print("✅ Log file created successfully!")
            
            # Read and display recent log entries
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                recent_lines = lines[-10:] if len(lines) > 10 else lines
            
            print(f"\n📖 Recent log entries ({len(recent_lines)} lines):")
            print("-" * 50)
            for line in recent_lines:
                print(line.rstrip())
            print("-" * 50)
            
            # Show file size
            file_size = log_file.stat().st_size
            print(f"📊 Log file size: {file_size} bytes")
            
        else:
            print("❌ Log file was not created!")
            print("   This might indicate an issue with the logging setup.")
        
        # List all log files in the directory
        if logs_dir.exists():
            log_files = list(logs_dir.glob("*.log"))
            print(f"\n📋 All log files in {logs_dir}:")
            for log_file in log_files:
                size = log_file.stat().st_size
                print(f"   📄 {log_file.name} ({size} bytes)")
        
        print("\n✅ Logging test completed!")
        
    except Exception as e:
        print(f"❌ Logging test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_dashboard_logging()
