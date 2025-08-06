#!/usr/bin/env python3
"""
Migration script to update ComfortLevel table schema.

This migration:
1. Adds prediction_id column as foreign key to predictions table
2. Adds occupant_profile column
3. Makes measurement_id nullable
4. Adds comfort class columns
5. Migrates existing data if any
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import text
from db.session import SessionLocal, engine
from db.models import Base

def migrate_comfort_levels_schema():
    """Migrate the comfort_levels table to new schema"""
    
    print("🔄 Starting ComfortLevel table migration...")
    
    with SessionLocal() as session:
        # Check if migration is needed
        try:
            result = session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'comfort_levels' 
                AND column_name = 'prediction_id';
            """))
            
            if result.fetchone():
                print("✅ Migration already applied - prediction_id column exists")
                return
                
        except Exception as e:
            print(f"⚠️ Could not check existing schema: {e}")
        
        try:
            # Step 1: Add new columns
            print("📝 Adding new columns...")
            
            session.execute(text("""
                ALTER TABLE comfort_levels 
                ADD COLUMN IF NOT EXISTS prediction_id INTEGER;
            """))
            
            session.execute(text("""
                ALTER TABLE comfort_levels 
                ADD COLUMN IF NOT EXISTS occupant_profile VARCHAR(50);
            """))
            
            # Add comfort class columns
            comfort_columns = [
                "thermal_comfort_class VARCHAR(2)",
                "visual_comfort_class VARCHAR(2)", 
                "acoustic_comfort_class VARCHAR(2)",
                "co2_comfort_class VARCHAR(2)",
                "co_comfort_class VARCHAR(2)",
                "tvoc_comfort_class VARCHAR(2)",
                "pm25_comfort_class VARCHAR(2)",
                "pm10_comfort_class VARCHAR(2)",
                "visual_comfort_score NUMERIC",
                "acoustic_annoyance_level NUMERIC",
                "overall_comfort NUMERIC",
                "overall_comfort_class VARCHAR(2)"
            ]
            
            for col_def in comfort_columns:
                col_name = col_def.split()[0]
                session.execute(text(f"""
                    ALTER TABLE comfort_levels 
                    ADD COLUMN IF NOT EXISTS {col_def};
                """))
            
            session.commit()
            print("✅ New columns added successfully")
            
            # Step 2: Make measurement_id nullable
            print("📝 Making measurement_id nullable...")
            session.execute(text("""
                ALTER TABLE comfort_levels 
                ALTER COLUMN measurement_id DROP NOT NULL;
            """))
            
            session.commit()
            print("✅ measurement_id is now nullable")
            
            # Step 3: Add foreign key constraint for prediction_id
            print("📝 Adding foreign key constraint...")
            try:
                session.execute(text("""
                    ALTER TABLE comfort_levels 
                    ADD CONSTRAINT fk_comfort_levels_prediction_id_predictions 
                    FOREIGN KEY (prediction_id) REFERENCES predictions(prediction_id) ON DELETE CASCADE;
                """))
                session.commit()
                print("✅ Foreign key constraint added")
            except Exception as e:
                print(f"⚠️ Could not add foreign key constraint: {e}")
                # This might fail if there are existing orphaned records
            
            # Step 4: Set default occupant_profile for existing records
            print("📝 Setting default occupant_profile for existing records...")
            result = session.execute(text("""
                UPDATE comfort_levels 
                SET occupant_profile = 'default' 
                WHERE occupant_profile IS NULL;
            """))
            
            updated_count = result.rowcount
            session.commit()
            print(f"✅ Updated {updated_count} existing records with default occupant_profile")
            
            # Step 5: Make occupant_profile NOT NULL
            print("📝 Making occupant_profile NOT NULL...")
            session.execute(text("""
                ALTER TABLE comfort_levels 
                ALTER COLUMN occupant_profile SET NOT NULL;
            """))
            
            session.commit()
            print("✅ occupant_profile is now NOT NULL")
            
            print("🎉 ComfortLevel table migration completed successfully!")
            
        except Exception as e:
            session.rollback()
            print(f"❌ Migration failed: {e}")
            raise

def verify_migration():
    """Verify the migration was successful"""
    
    print("\n🔍 Verifying migration...")
    
    with SessionLocal() as session:
        try:
            # Check new columns exist
            result = session.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_name = 'comfort_levels' 
                ORDER BY column_name;
            """))
            
            columns = result.fetchall()
            
            expected_columns = [
                'prediction_id', 'occupant_profile', 'thermal_comfort_class',
                'visual_comfort_class', 'acoustic_comfort_class', 'overall_comfort'
            ]
            
            found_columns = [col[0] for col in columns]
            
            print("📋 Current comfort_levels columns:")
            for col_name, data_type, is_nullable in columns:
                nullable_str = "NULL" if is_nullable == "YES" else "NOT NULL"
                print(f"   {col_name}: {data_type} {nullable_str}")
            
            # Check if all expected columns exist
            missing_columns = [col for col in expected_columns if col not in found_columns]
            if missing_columns:
                print(f"⚠️ Missing columns: {missing_columns}")
            else:
                print("✅ All expected columns found")
                
        except Exception as e:
            print(f"❌ Verification failed: {e}")

if __name__ == "__main__":
    migrate_comfort_levels_schema()
    verify_migration()
