# Database Migrations

This folder contains database migration scripts for the Energy Comfortness Tool.

## Migration Scripts

### `migrate_schema.py`
Database schema migration script to move sensor_id from energy_buildings to energy_spaces table. This migration restructures the database to better support multi-sensor building simulations.

### `migrate_timestamped_energy.py`
Migration script to add the EnergyTimeSeries table for timestamped energy data. Run this script to upgrade existing databases to support the new timestamped energy model with hourly data points.

## Usage

Run these scripts when upgrading the database schema to newer versions. Make sure to backup your database before running any migration scripts.

```bash
python migrations/migrate_schema.py
python migrations/migrate_timestamped_energy.py
```

## Prerequisites

- PostgreSQL database connection configured
- Backup of existing database (recommended)
- Required Python packages installed (psycopg2, etc.)
