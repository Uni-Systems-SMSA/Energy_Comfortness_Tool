#!/usr/bin/env python3
"""Test creating ComfortLevel for existing predictions."""

from datetime import datetime, timezone
from db.session import SessionLocal
from db.models import ComfortLevel, Prediction
from ece.helpers import pmv_ppd, classify_thermal_category, classify_visual_category, yong_score

def test_existing_prediction_comfort():
    """Test creating ComfortLevel for an existing prediction."""
    print('🔧 Testing ComfortLevel creation for existing predictions...')
    
    with SessionLocal() as ses:
        # Get an existing prediction
        existing_pred = ses.query(Prediction).first()
        if not existing_pred:
            print('❌ No existing predictions found')
            return
            
        print(f'✅ Found existing prediction ID: {existing_pred.prediction_id}')
        
        # Check if ComfortLevel already exists for this prediction
        existing_comfort = ses.query(ComfortLevel).filter(
            ComfortLevel.prediction_id == existing_pred.prediction_id,
            ComfortLevel.occupant_profile == 'test_profile'
        ).first()
        
        if existing_comfort:
            print(f'ℹ️ ComfortLevel already exists for this prediction: {existing_comfort.comfort_id}')
            return
        
        # Create a test ComfortLevel
        try:
            # Simple comfort calculations
            temp = float(existing_pred.predicted_temperature_c) if existing_pred.predicted_temperature_c else 22.0
            rh = float(existing_pred.predicted_rh_percent) if existing_pred.predicted_rh_percent else 50.0
            lux = float(existing_pred.predicted_luminance_lux) if existing_pred.predicted_luminance_lux else 300.0
            
            pmv_val, ppd_val = pmv_ppd(ta=temp, tr=temp, vel=0.1, rh=rh, met=1.2, clo=0.7)
            thermal_class = classify_thermal_category([pmv_val], [ppd_val])
            visual_class = classify_visual_category([lux])
            vis_score = yong_score([lux])
            
            comfort_level = ComfortLevel(
                prediction_id=existing_pred.prediction_id,
                occupant_profile='test_profile',
                pmv=float(pmv_val),
                ppd=float(ppd_val),
                thermal_comfort_class=thermal_class[0],
                visual_comfort_class=visual_class[0],
                visual_comfort_score=float(vis_score[0]),
                overall_comfort=2.5,
                overall_comfort_class='B',
                estimated_at=datetime.now(tz=timezone.utc)
            )
            
            ses.add(comfort_level)
            ses.commit()
            
            print(f'✅ Successfully created ComfortLevel ID: {comfort_level.comfort_id}')
            print(f'   Profile: {comfort_level.occupant_profile}')
            print(f'   PMV: {comfort_level.pmv:.2f}, Thermal: {comfort_level.thermal_comfort_class}')
            print(f'   Linked to Prediction ID: {comfort_level.prediction_id}')
            
            # Verify total count
            total_comfort = ses.query(ComfortLevel).count()
            print(f'📊 Total ComfortLevel records now: {total_comfort}')
            
        except Exception as e:
            print(f'❌ Error creating ComfortLevel: {e}')
            ses.rollback()

if __name__ == "__main__":
    test_existing_prediction_comfort()
