"""Migration: Add space_id to trained_models table

This migration adds space_id to the trained_models table to support
training separate models per space. This allows for space-specific
model training and predictions.

Changes:
- Add space_id column to trained_models (nullable for backward compatibility)
- Drop old unique constraint (target, version)
- Add new unique constraint (target, version, space_id)

Run this script to apply the migration.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from db.session import SessionLocal, engine


def migrate():
    """Apply the migration."""
    
    with engine.begin() as conn:
        print("Starting migration: add_space_id_to_trained_models")
        
        # Step 1: Add space_id column (nullable initially for backward compatibility)
        print("  - Adding space_id column...")
        conn.execute(text("""
            ALTER TABLE trained_models 
            ADD COLUMN IF NOT EXISTS space_id VARCHAR
        """))
        
        # Step 2: Add foreign key constraint
        print("  - Adding foreign key constraint...")
        conn.execute(text("""
            ALTER TABLE trained_models
            ADD CONSTRAINT fk_trained_models_space_id
            FOREIGN KEY (space_id) REFERENCES spaces(space_id)
            ON DELETE CASCADE
        """))
        
        # Step 3: Drop old unique constraint
        print("  - Dropping old unique constraint...")
        conn.execute(text("""
            ALTER TABLE trained_models
            DROP CONSTRAINT IF EXISTS uq_trained_models_target_version
        """))
        
        # Step 4: Add new unique constraint including space_id
        print("  - Adding new unique constraint (target, version, space_id)...")
        conn.execute(text("""
            ALTER TABLE trained_models
            ADD CONSTRAINT uq_trained_models_target_version_space
            UNIQUE (target, version, space_id)
        """))
        
        print("✓ Migration completed successfully!")


def rollback():
    """Rollback the migration."""
    
    with engine.begin() as conn:
        print("Rolling back migration: add_space_id_to_trained_models")
        
        # Step 1: Drop new unique constraint
        print("  - Dropping new unique constraint...")
        conn.execute(text("""
            ALTER TABLE trained_models
            DROP CONSTRAINT IF EXISTS uq_trained_models_target_version_space
        """))
        
        # Step 2: Restore old unique constraint
        print("  - Restoring old unique constraint...")
        conn.execute(text("""
            ALTER TABLE trained_models
            ADD CONSTRAINT uq_trained_models_target_version
            UNIQUE (target, version)
        """))
        
        # Step 3: Drop foreign key constraint
        print("  - Dropping foreign key constraint...")
        conn.execute(text("""
            ALTER TABLE trained_models
            DROP CONSTRAINT IF EXISTS fk_trained_models_space_id
        """))
        
        # Step 4: Drop space_id column
        print("  - Dropping space_id column...")
        conn.execute(text("""
            ALTER TABLE trained_models
            DROP COLUMN IF EXISTS space_id
        """))
        
        print("✓ Rollback completed successfully!")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Migrate trained_models table to support per-space models")
    parser.add_argument("--rollback", action="store_true", help="Rollback the migration")
    args = parser.parse_args()
    
    if args.rollback:
        rollback()
    else:
        migrate()
