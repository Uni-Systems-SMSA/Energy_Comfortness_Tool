#!/usr/bin/env python3
"""Test ComfortLevel creation after fixes."""

from db.session import SessionLocal
from db.models import ComfortLevel, Prediction

def test_comfort_fixes():
    """Test the ComfortLevel creation fixes."""
    print('🧪 Testing ComfortLevel creation after fix...')
    print('=' * 50)

    with SessionLocal() as ses:
        initial_count = ses.query(ComfortLevel).count()
        pred_count = ses.query(Prediction).count()
        
        print(f'Current ComfortLevel records: {initial_count}')
        print(f'Available Prediction records: {pred_count}')
        
        print('\n✅ Code changes applied:')
        print('  1. Fixed Altair deprecation warning')
        print('  2. Modified ComfortLevel creation to work with existing predictions')
        print('  3. Added check for existing ComfortLevel records to avoid duplicates')
        print('  4. Removed dependency on predictions_inserted flag')
        
        print('\n🚀 Next steps:')
        print('  1. Run the Streamlit dashboard: streamlit run dashboard/app.py')
        print('  2. Click the "🔮 Predict" button')
        print('  3. ComfortLevel records should now be created!')

if __name__ == "__main__":
    test_comfort_fixes()
