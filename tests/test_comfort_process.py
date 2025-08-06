#!/usr/bin/env python3
"""Test the complete ComfortLevel creation process."""

from datetime import datetime, timezone
from db.session import SessionLocal
from db.models import Weather, Prediction, ComfortLevel
from ece.helpers import (
    pmv_ppd, classify_thermal_category, classify_visual_category,
    classify_acoustic_category, yong_score, annoyance_level
)

def test_comfort_creation_process():
    """Test the complete 4-step process for ComfortLevel creation."""
    print('🔍 Testing ComfortLevel creation process with multiple profiles...')
    print('=' * 60)

    with SessionLocal() as ses:
        # Get current state
        initial_count = ses.query(ComfortLevel).count()
        print(f'Initial ComfortLevel records: {initial_count}')
        
        # Test data for different profiles
        profiles_to_test = [
            {'name': 'young', 'age': 25},
            {'name': 'elderly', 'age': 65}
        ]
        
        # Get a prediction to work with
        prediction = ses.query(Prediction).offset(1).first()
        if not prediction:
            print('❌ No prediction records found')
            return
            
        print(f'Using Prediction ID: {prediction.prediction_id}')
        
        for profile in profiles_to_test:
            try:
                print(f'\n🧑‍💼 Creating ComfortLevel for profile: {profile["name"]} (age {profile["age"]})')
                
                # Extract prediction values
                temp = float(prediction.predicted_temperature_c) if prediction.predicted_temperature_c else 22.0
                rh = float(prediction.predicted_rh_percent) if prediction.predicted_rh_percent else 50.0
                lux = float(prediction.predicted_luminance_lux) if prediction.predicted_luminance_lux else 300.0
                noise = float(prediction.predicted_average_noise_db) if prediction.predicted_average_noise_db else 40.0
                
                # Step 3: Calculate comfort metrics for this profile
                
                # Thermal comfort (age-independent)
                pmv_val, ppd_val = pmv_ppd(ta=temp, tr=temp, vel=0.1, rh=rh, met=1.2, clo=0.7)
                thermal_class = classify_thermal_category([pmv_val], [ppd_val])
                
                # Visual comfort (age-independent)
                visual_class = classify_visual_category([lux])
                vis_score = yong_score([lux])
                
                # Acoustic comfort (age-dependent - this is where the profile matters!)
                acoustic_class = classify_acoustic_category([noise])
                annoy_level_val = annoyance_level([noise], age=profile["age"])
                
                print(f'   PMV: {pmv_val:.2f}, Thermal: {thermal_class[0]}')
                print(f'   Visual: {lux} lux → {visual_class[0]}')
                print(f'   Acoustic: {noise} dB → {acoustic_class[0]} (age {profile["age"]}, annoyance: {annoy_level_val[0]:.2f})')
                
                # Step 4: Create ComfortLevel record
                comfort_level = ComfortLevel(
                    prediction_id=prediction.prediction_id,
                    occupant_profile=profile["name"],
                    pmv=float(pmv_val),
                    ppd=float(ppd_val),
                    thermal_comfort_class=thermal_class[0],
                    visual_comfort_class=visual_class[0],
                    visual_comfort_score=float(vis_score[0]),
                    acoustic_comfort_class=acoustic_class[0],
                    acoustic_annoyance_level=float(annoy_level_val[0]),
                    overall_comfort=2.8,  # Example overall score
                    overall_comfort_class='B',
                    estimated_at=datetime.now(tz=timezone.utc)
                )
                
                ses.add(comfort_level)
                ses.commit()
                
                print(f'   ✅ Created ComfortLevel ID: {comfort_level.comfort_id}')
                
            except Exception as e:
                print(f'   ❌ Error for profile {profile["name"]}: {e}')
                ses.rollback()
                import traceback
                traceback.print_exc()
        
        # Final verification
        final_count = ses.query(ComfortLevel).count()
        print(f'\n📊 Final ComfortLevel records: {final_count} (added {final_count - initial_count})')
        
        # Show all comfort records
        print('\n🔍 All ComfortLevel records:')
        all_comfort = ses.query(ComfortLevel).all()
        for c in all_comfort:
            print(f'   ID {c.comfort_id}: {c.occupant_profile} → PMV={c.pmv:.2f}, Thermal={c.thermal_comfort_class}, Acoustic={c.acoustic_comfort_class}')
        
        print('\n✅ ComfortLevel creation process test completed!')

if __name__ == "__main__":
    test_comfort_creation_process()
