# Tests

This directory contains test files and debugging utilities for the Energy Comfortness Tool.

## Test Organization

### Core Functionality Tests
- `test_basic_retrieval.py` - Basic data retrieval functionality
- `test_database_filtering.py` - Database filtering and querying
- `test_database_queries.py` - Complex database query validation
- `test_date_filtering.py` - Date filtering functionality
- `test_date_filtering_fix.py` - Date filtering bug fixes validation
- `test_decimal_conversion.py` - Decimal to float conversion utilities

### Energy System Tests
- `test_energy_parsing.py` - EnergyPlus output parsing
- `test_energy_spaces.py` - Energy space data handling
- `test_energy_storage.py` - Energy data storage validation
- `test_eplus_pipeline.py` - EnergyPlus simulation pipeline integration

### Comfort Analysis Tests
- `test_comfort_creation.py` - ComfortLevel record creation
- `test_comfort_process.py` - Complete comfort analysis process
- `test_existing_prediction.py` - Creating comfort data for existing predictions
- `test_new_predictions.py` - New prediction system with comfort data
- `test_overall_comfort.py` - Overall comfort calculation functionality
- `test_prediction_fix.py` - Prediction logic fixes validation

### Spatial and Data Management Tests
- `test_space_csv.py` - Space CSV file processing
- `test_space_filtering.py` - Space-based data filtering
- `test_space_mapping.py` - Zone ID to space name mapping
- `test_space_specific_view.py` - Space-specific data views
- `test_sensor_ids.py` - Sensor ID handling and validation
- `test_sensor_variations.py` - Different sensor ID formats

### System Integration Tests
- `test_fallback.py` - Fallback mechanism validation
- `test_geocoding.py` - Geocoding functionality with geopy
- `test_geocoding_simple.py` - Simple geocoding validation
- `test_wrapper.py` - EnergyPlus wrapper functionality

### Unicode and Encoding Tests
- `test_conda_unicode.py` - Conda subprocess Unicode handling
- `test_unicode_fixes.py` - Unicode handling fixes validation
- `test_unicode_subprocess.py` - Subprocess Unicode error reproduction

### Maintenance and Validation Tests
- `test_fixes.py` - General bug fixes validation
- `test_db_check.py` - Database state checking utilities

### ML and Data Processing Tests
- `insert_to_db.py` - Database insertion utilities for testing
- `ml_train.py` - Machine learning model training utilities
- `ml_infer.py` - Machine learning inference testing

## Running Tests

### All Tests
```bash
python -m pytest tests/
```

### By Category
```bash
# Energy system tests
python -m pytest tests/test_energy_*.py

# Comfort analysis tests  
python -m pytest tests/test_comfort_*.py tests/test_overall_comfort.py tests/test_prediction_*.py

# Spatial data tests
python -m pytest tests/test_space_*.py tests/test_sensor_*.py

# System integration tests
python -m pytest tests/test_*pipeline*.py tests/test_wrapper.py tests/test_fallback.py

# Unicode and encoding tests
python -m pytest tests/test_*unicode*.py

# Database tests
python -m pytest tests/test_database_*.py tests/test_db_*.py
```

### Specific Test Files
```bash
python -m pytest tests/test_geocoding.py
python -m pytest tests/test_eplus_pipeline.py  
python -m pytest tests/test_comfort_creation.py
python -m pytest tests/test_energy_storage.py
```

## Test Dependencies

- **Conda environments**: Some tests require 'bim2sim' environment
- **External services**: Weather APIs, geocoding services
- **Database**: Properly configured PostgreSQL connection
- **EnergyPlus**: Version 9.4.0 installation required for simulation tests
- **File dependencies**: EPW files, IFC models, CSV data

## Test Categories

- **Unit Tests**: Individual function and method testing
- **Integration Tests**: Component interaction validation
- **System Tests**: End-to-end workflow testing
- **Regression Tests**: Bug fix and stability validation
- **Performance Tests**: Data processing and query optimization

## Notes

- Tests are organized by functional domain for easier maintenance
- Some tests require specific data files or external dependencies
- Database tests may modify test data - use appropriate test databases
- Unicode tests help ensure cross-platform compatibility
- Energy tests validate the complete simulation-to-visualization pipeline
