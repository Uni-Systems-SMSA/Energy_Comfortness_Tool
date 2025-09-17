# Energy Comfortness Tool - Project Structure

## Overview
This document describes the organized structure of the Energy Comfortness Tool repository after cleanup and reorganization.

## Directory Structure

```
energy_comfortness_tool/
├── README.md                    # Main project documentation
├── requirements.txt             # Python dependencies
├── docker-compose.yml          # Docker configuration
├── .env                        # Environment variables
├── .gitignore                  # Git ignore rules
│
├── dashboard/                   # Streamlit web application
│   ├── app.py                  # Main dashboard application
│   ├── assets/                 # Static assets
│   ├── logs/                   # Dashboard logs
│   ├── models/                 # ML model files
│   └── model_reports/          # Model performance reports
│
├── db/                         # Database layer
│   ├── __init__.py
│   ├── models.py               # SQLAlchemy ORM models
│   └── session.py              # Database session management
│
├── ece/                        # Energy Comfortness Engine
│   ├── __init__.py
│   ├── data.py                 # Data processing utilities
│   ├── feature_map.py          # Feature mapping and definitions
│   ├── helpers.py              # Comfort calculation helpers
│   ├── model_zoo.py            # Machine learning models
│   ├── pipeline_eplus.py       # EnergyPlus pipeline
│   ├── pipeline_eplus_wrapper.py # EnergyPlus wrapper
│   ├── pipeline_ml.py          # ML training pipeline
│   ├── pipeline_weather.py     # Weather data pipeline
│   ├── weather_api.py          # Weather API integration
│   └── utils/                  # Utility modules
│
├── eplus_sim/                  # EnergyPlus simulation files
│   ├── idf/                    # IDF model files
│   ├── weather/                # EPW weather files
│   ├── results/                # Simulation results
│   ├── logs/                   # Simulation logs
│   ├── models/                 # Building models
│   ├── scripts/                # Simulation scripts
│   └── templates/              # Template files
│
├── migrations/                 # Database migrations
│   ├── README.md              # Migration documentation
│   ├── add_comfort_to_predictions.py
│   ├── add_overall_comfort_to_predictions.py
│   ├── add_overall_comfort_class_to_predictions.py
│   ├── migrate_comfort_levels_schema.py
│   ├── migrate_comfort_to_predictions.py
│   ├── migrate_schema.py
│   ├── migrate_timestamped_energy.py
│   ├── remove_comfort_from_predictions.py
│   └── remove_redundant_predicted_columns.py
│
├── tests/                      # Test suite
│   ├── README.md              # Test documentation
│   ├── __init__.py
│   │
│   ├── # Core functionality tests
│   ├── test_basic_retrieval.py
│   ├── test_database_filtering.py
│   ├── test_database_queries.py
│   ├── test_date_filtering.py
│   ├── test_date_filtering_fix.py
│   ├── test_decimal_conversion.py
│   │
│   ├── # Energy system tests
│   ├── test_energy_parsing.py
│   ├── test_energy_spaces.py
│   ├── test_energy_storage.py
│   ├── test_eplus_pipeline.py
│   │
│   ├── # Comfort analysis tests
│   ├── test_comfort_creation.py
│   ├── test_comfort_process.py
│   ├── test_existing_prediction.py
│   ├── test_new_predictions.py
│   ├── test_overall_comfort.py
│   ├── test_prediction_fix.py
│   │
│   ├── # Spatial and data tests
│   ├── test_space_csv.py
│   ├── test_space_filtering.py
│   ├── test_space_mapping.py
│   ├── test_space_specific_view.py
│   ├── test_sensor_ids.py
│   ├── test_sensor_variations.py
│   │
│   ├── # System integration tests
│   ├── test_fallback.py
│   ├── test_geocoding.py
│   ├── test_geocoding_simple.py
│   ├── test_wrapper.py
│   │
│   ├── # Unicode and encoding tests
│   ├── test_conda_unicode.py
│   ├── test_unicode_fixes.py
│   ├── test_unicode_subprocess.py
│   │
│   ├── # Maintenance tests
│   ├── test_fixes.py
│   ├── test_db_check.py
│   │
│   └── # ML and data processing tests
│       ├── insert_to_db.py
│       ├── ml_infer.py
│       └── ml_train.py
│
├── scripts/                    # Utility and maintenance scripts
│   ├── README.md              # Scripts documentation
│   │
│   ├── # Analysis and debugging
│   ├── analyze_duplicates.py
│   ├── analyze_predictions.py
│   ├── debug_prediction.py
│   ├── debug_prediction_pipeline.py
│   ├── debug_unicode.py
│   ├── debug_bim2sim.py
│   │
│   ├── # Data checking and validation
│   ├── check_csv_data.py
│   ├── check_db_state.py
│   ├── check_schema.py
│   ├── check_unicode.py
│   ├── check_database_structure.py
│   ├── check_energy_dates.py
│   ├── check_energy_tables.py
│   ├── check_timestamps.py
│   │
│   ├── # Data cleanup and maintenance
│   ├── clean_predictions.py
│   ├── cleanup_duplicates.py
│   ├── clear_energy_tables.py
│   ├── update_sensor_ids.py
│   │
│   └── # Sample data creation
│       └── create_sample_data.py
│
├── docs/                       # Documentation
│   ├── LICENSE                 # License file
│   ├── EPLUS_PIPELINE_SUMMARY.md
│   ├── EPW_ENHANCEMENT_SUMMARY.md
│   ├── EPW_LOCATION_HEADER_FIX.md
│   ├── OVERALL_COMFORT_FEATURE.md
│   │
│   └── summaries/              # Project summaries
│       ├── COMMIT_SUMMARY.md
│       └── TIMESTAMP_FIXES_SUMMARY.md
│
├── models/                     # Trained ML models
├── model_store/               # Model storage and versioning
├── model_reports/             # Model performance reports
│
├── database/                  # Database setup and data
│   ├── data/                  # Database data files
│   └── docker-entrypoint-initdb.d/ # Database initialization
│
├── logs/                      # Application logs
├── uploads/                   # File uploads
├── etc/                       # Configuration files
│   └── weather/               # Weather configuration
│
└── catboost_info/             # CatBoost model information
    ├── catboost_training.json
    ├── learn_error.tsv
    ├── time_left.tsv
    ├── learn/
    └── tmp/
```

## Key Components

### Dashboard (`dashboard/`)
- **app.py**: Main Streamlit application with energy analysis and comfort visualization
- Contains the web UI for the Energy Comfortness Tool

### Engine (`ece/`)
- **Core algorithms**: Comfort calculations, ML pipelines, data processing
- **Integration**: EnergyPlus, weather APIs, ML models
- **Pipelines**: Energy simulation, weather data, ML training

### Database (`db/`)
- **ORM Models**: SQLAlchemy models for all database entities
- **Session Management**: Database connection and session handling

### EnergyPlus Simulation (`eplus_sim/`)
- **Building Models**: IDF files and building geometry
- **Weather Data**: EPW files for simulations
- **Results**: Simulation outputs and analysis

### Tests (`tests/`)
- **Comprehensive test suite** covering all major functionality
- **Organized by domain**: Energy, comfort, ML, spatial analysis, system integration
- **Unicode and encoding tests** for cross-platform compatibility

### Scripts (`scripts/`)
- **Maintenance utilities**: Data cleanup, validation, debugging
- **Analysis tools**: Performance analysis, data exploration
- **Development aids**: Sample data creation, schema validation

### Documentation (`docs/`)
- **Technical documentation**: Feature specifications, pipeline summaries
- **Project summaries**: Major changes and implementation details
- **Architectural guides**: System design and component interaction

## Usage Guidelines

### Running Tests
```bash
# Run all tests
python -m pytest tests/

# Run specific test categories
python -m pytest tests/test_energy_*.py
python -m pytest tests/test_comfort_*.py
python -m pytest tests/test_space_*.py
```

### Using Scripts
```bash
# Check database state
python scripts/check_db_state.py

# Analyze predictions
python scripts/analyze_predictions.py

# Clean duplicate data
python scripts/cleanup_duplicates.py
```

### Development
- **Main application**: `streamlit run dashboard/app.py`
- **Database migrations**: Run scripts in `migrations/` folder
- **New features**: Add tests in `tests/` and documentation in `docs/`

## Maintenance

### Adding New Tests
- Place test files in appropriate `tests/` subdirectory
- Follow naming convention: `test_<feature_name>.py`
- Include docstrings and clear test descriptions

### Adding New Scripts
- Place utility scripts in `scripts/` directory
- Add documentation to `scripts/README.md`
- Include usage examples and parameter descriptions

### Documentation Updates
- Update relevant files in `docs/` for new features
- Add summaries to `docs/summaries/` for major changes
- Keep `PROJECT_STRUCTURE.md` current with directory changes

This organized structure improves maintainability, testing, and development workflow while keeping the root directory clean and focused.
