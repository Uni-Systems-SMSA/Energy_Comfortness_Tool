#!/usr/bin/env python3
"""
Database schema migration script to move sensor_id from energy_buildings to energy_spaces
"""

import psycopg2
from psycopg2 import sql
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_sensor_id():
    """Migrate sensor_id column from energy_buildings to energy_spaces"""
    try:
        # Connect to PostgreSQL database
        conn = psycopg2.connect(
            host='localhost',
            port=5442,
            database='ect_db',
            user='ect_admin',
            password='ect_pwd'
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        logger.info('Connected to database successfully')
        
        # Step 1: Check current schema
        logger.info('Checking current schema...')
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'energy_buildings' 
            ORDER BY ordinal_position;
        """)
        buildings_columns = cursor.fetchall()
        logger.info(f'energy_buildings columns: {buildings_columns}')
        
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'energy_spaces' 
            ORDER BY ordinal_position;
        """)
        spaces_columns = cursor.fetchall()
        logger.info(f'energy_spaces columns: {spaces_columns}')
        
        # Step 2: Check if sensor_id exists in energy_buildings
        has_sensor_id_in_buildings = any(col[0] == 'sensor_id' for col in buildings_columns)
        has_sensor_id_in_spaces = any(col[0] == 'sensor_id' for col in spaces_columns)
        
        logger.info(f'sensor_id in energy_buildings: {has_sensor_id_in_buildings}')
        logger.info(f'sensor_id in energy_spaces: {has_sensor_id_in_spaces}')
        
        # Step 3: Migrate data if needed
        if has_sensor_id_in_buildings and not has_sensor_id_in_spaces:
            logger.info('Starting migration: sensor_id exists in buildings but not in spaces')
            
            # Add sensor_id column to energy_spaces
            logger.info('Adding sensor_id column to energy_spaces...')
            cursor.execute("""
                ALTER TABLE energy_spaces 
                ADD COLUMN sensor_id VARCHAR(50);
            """)
            
            # Copy sensor_id data from buildings to spaces (if any spaces exist)
            logger.info('Copying sensor_id data from buildings to spaces...')
            cursor.execute("""
                UPDATE energy_spaces 
                SET sensor_id = (
                    SELECT eb.sensor_id 
                    FROM energy_buildings eb 
                    WHERE eb.building_id = energy_spaces.building_id
                )
                WHERE EXISTS (
                    SELECT 1 FROM energy_buildings eb 
                    WHERE eb.building_id = energy_spaces.building_id 
                    AND eb.sensor_id IS NOT NULL
                );
            """)
            
            rows_updated = cursor.rowcount
            logger.info(f'Updated {rows_updated} energy_spaces records with sensor_id')
            
            # Drop unique constraint on energy_buildings if it exists
            logger.info('Dropping unique constraint on energy_buildings...')
            try:
                cursor.execute("""
                    ALTER TABLE energy_buildings 
                    DROP CONSTRAINT IF EXISTS uq_energy_buildings_sensor_id_ifc_path;
                """)
                logger.info('Dropped unique constraint successfully')
            except Exception as e:
                logger.warning(f'Could not drop unique constraint: {e}')
            
            # Remove sensor_id column from energy_buildings
            logger.info('Removing sensor_id column from energy_buildings...')
            cursor.execute("""
                ALTER TABLE energy_buildings 
                DROP COLUMN sensor_id;
            """)
            
            # Add index on sensor_id in energy_spaces for performance
            logger.info('Adding index on sensor_id in energy_spaces...')
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_energy_spaces_sensor_id 
                ON energy_spaces(sensor_id);
            """)
            
            logger.info('✅ Migration completed successfully!')
            
        elif not has_sensor_id_in_buildings and has_sensor_id_in_spaces:
            logger.info('✅ Schema already migrated - sensor_id is in energy_spaces')
            
        elif has_sensor_id_in_buildings and has_sensor_id_in_spaces:
            logger.info('Both tables have sensor_id - removing from energy_buildings only...')
            
            # Drop unique constraint and remove column from buildings
            try:
                cursor.execute("""
                    ALTER TABLE energy_buildings 
                    DROP CONSTRAINT IF EXISTS uq_energy_buildings_sensor_id_ifc_path;
                """)
            except Exception as e:
                logger.warning(f'Could not drop unique constraint: {e}')
                
            cursor.execute("""
                ALTER TABLE energy_buildings 
                DROP COLUMN sensor_id;
            """)
            
            logger.info('✅ Removed sensor_id from energy_buildings')
            
        else:
            logger.info('Adding sensor_id column to energy_spaces...')
            cursor.execute("""
                ALTER TABLE energy_spaces 
                ADD COLUMN sensor_id VARCHAR(50);
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_energy_spaces_sensor_id 
                ON energy_spaces(sensor_id);
            """)
            
            logger.info('✅ Added sensor_id column to energy_spaces')
        
        # Step 4: Verify final schema
        logger.info('Verifying final schema...')
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'energy_buildings' 
            ORDER BY ordinal_position;
        """)
        final_buildings_columns = cursor.fetchall()
        logger.info(f'Final energy_buildings columns: {final_buildings_columns}')
        
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'energy_spaces' 
            ORDER BY ordinal_position;
        """)
        final_spaces_columns = cursor.fetchall()
        logger.info(f'Final energy_spaces columns: {final_spaces_columns}')
        
        cursor.close()
        conn.close()
        logger.info('Database connection closed')
        
        return True
        
    except Exception as e:
        logger.error(f'Migration failed: {str(e)}')
        raise

if __name__ == "__main__":
    migrate_sensor_id()
    print('Database schema migration completed successfully!')
