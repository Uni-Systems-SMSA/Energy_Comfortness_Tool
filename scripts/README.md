# Utility Scripts

This folder contains utility and debugging scripts for the Energy Comfortness Tool.

## Analysis and Debugging Scripts

### `analyze_duplicates.py`
Analyzes duplicate records in the database and provides statistics on data quality issues.

### `analyze_predictions.py` 
Analyzes prediction data volume, distribution, and quality metrics.

### `debug_prediction.py`
Debug prediction saving issues and model loading problems.

### `debug_prediction_pipeline.py`
Debug the complete prediction pipeline to identify where ComfortLevel records aren't being created.

### `debug_unicode.py`
Simple test script to debug Unicode issues in bim2sim command line processing.

### `debug_bim2sim.py`
Test script to debug bim2sim import issues. This script helps diagnose Python environment and import problems when working with the bim2sim library for IFC file processing.

## Data Checking and Validation Scripts

### `check_csv_data.py`
Verify the completeness and structure of EnergyPlus CSV output files.

### `check_db_state.py`
Quick database state check - shows current record counts and sample data.

### `check_schema.py`
Check current database schema status and verify migration completeness.

### `check_unicode.py`
Check files for non-ASCII characters and print their positions for debugging.

### `check_database_structure.py`
Comprehensive database structure validation and schema verification.

### `check_energy_dates.py`
Validate energy data date ranges and identify temporal gaps.

### `check_energy_tables.py`
Check energy-related database tables for data integrity.

### `check_timestamps.py`
Validate timestamp consistency across energy data tables.

## Data Cleanup and Maintenance Scripts

### `clean_predictions.py`
Clean predictions table - removes all prediction records from the database for testing new functionality.

### `cleanup_duplicates.py`
Remove duplicate records from database tables (predictions, weather, measurements) with dry-run capability.

### `clear_energy_tables.py`
Clear all energy-related tables for fresh simulation runs.

### `update_sensor_ids.py`
Update sensor IDs across tables to maintain consistency.

## Sample Data Creation

### `create_sample_data.py`
Test script to generate sample prediction and comfort level data for development and testing.

## Usage Examples

```bash
# Check database state
python scripts/check_db_state.py

# Analyze predictions with full output
python scripts/analyze_predictions.py

# Clean predictions table (with confirmation)
python scripts/clean_predictions.py

# Run duplicate cleanup in dry-run mode first
python scripts/cleanup_duplicates.py --dry-run

# Debug Unicode issues
python scripts/debug_unicode.py

# Validate database schema
python scripts/check_schema.py

# Create sample data for testing
python scripts/create_sample_data.py
```

## Categories

- **Analysis**: `analyze_*.py` - Data analysis and metrics
- **Debugging**: `debug_*.py` - Troubleshooting and diagnostics  
- **Checking**: `check_*.py` - Validation and verification
- **Cleanup**: `clean*.py` - Data cleanup and maintenance
- **Utilities**: Other maintenance and helper scripts

These scripts are essential for maintaining data quality, debugging issues, and supporting development workflows.
