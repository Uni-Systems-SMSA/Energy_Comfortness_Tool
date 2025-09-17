# Database Migrations

This folder contains database migration scripts for the Energy Comfortness Tool.

## Migration Scripts

### `migrate_schema.py`
Database schema migration script to move sensor_id from energy_buildings to energy_spaces table. This migration restructures the database to better support multi-sensor building simulations.

### `migrate_timestamped_energy.py`
Migration script to add the EnergyTimeSeries table for timestamped energy data. Run this script to upgrade existing databases to support the new timestamped energy model with hourly data points.

### `add_occupant_profile_to_predictions.py` ⭐ **NEW**
Migration script to add the missing `occupant_profile` column to the predictions table and rename `pmv_value`/`ppd_value` columns to `pmv`/`ppd` to match the current SQLAlchemy model. Run this if you get "column predictions.occupant_profile does not exist" errors.

## Common Issues

### "column predictions.occupant_profile does not exist"
This error occurs when the database schema doesn't match the current SQLAlchemy model. Run:
```bash
python migrations/add_occupant_profile_to_predictions.py
```

### Schema Diagnosis
To check your database schema for issues:
```bash
python scripts/check_db_schema.py
```

## Usage

Run these scripts when upgrading the database schema to newer versions. Make sure to backup your database before running any migration scripts.

```bash
python migrations/migrate_schema.py
python migrations/migrate_timestamped_energy.py
python migrations/add_occupant_profile_to_predictions.py
```

## Prerequisites

- PostgreSQL database connection configured
- Backup of existing database (recommended)
- Required Python packages installed (psycopg2, etc.)
