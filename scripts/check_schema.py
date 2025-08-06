#!/usr/bin/env python3
"""
Check current database schema status
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from db.session import SessionLocal
from sqlalchemy import text

def check_database_schema():
    """Check the current state of the database schema"""
    
    with SessionLocal() as session:
        # Check what tables exist
        result = session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
        tables = [row[0] for row in result.fetchall()]
        print('📋 Existing tables:')
        for table in sorted(tables):
            print(f'  - {table}')
        
        # Check if comfort_levels table exists
        if 'comfort_levels' in tables:
            print('\n✅ comfort_levels table exists')
            
            # Check comfort_levels structure
            result = session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'comfort_levels' ORDER BY ordinal_position"))
            columns = [row[0] for row in result.fetchall()]
            print('   Columns:')
            for col in columns:
                print(f'     - {col}')
            
            # Check for key new columns
            has_prediction_id = 'prediction_id' in columns
            has_occupant_profile = 'occupant_profile' in columns
            
            print(f'\n🔍 Migration status:')
            print(f'   - prediction_id column: {"✅" if has_prediction_id else "❌"}')
            print(f'   - occupant_profile column: {"✅" if has_occupant_profile else "❌"}')
            
            if has_prediction_id and has_occupant_profile:
                print('\n🎉 Migration appears to be complete!')
                return True
            else:
                print('\n⚠️  Migration needed!')
                return False
        else:
            print('\n❌ comfort_levels table does not exist - migration needed!')
            return False

if __name__ == "__main__":
    check_database_schema()
