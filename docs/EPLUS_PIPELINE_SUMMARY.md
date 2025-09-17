# EnergyPlus Pipeline Summary

## Overview
Integration pipeline for EnergyPlus building energy simulations within the Energy Comfortness Tool, featuring advanced cross-year simulation capabilities.

## Pipeline Components

### 1. **IFC File Processing**
- Input: Building Information Model (BIM) files in IFC format
- Processing: Conversion to EnergyPlus-compatible format using bim2sim
- Output: EnergyPlus Input Data File (.idf)

### 2. **Weather Data Integration**
- Input: Location coordinates and time period
- Processing: EPW weather file generation using Open-Meteo API
- Output: EnergyPlus Weather (.epw) file

### 3. **Energy Simulation**
- Input: .idf building model + .epw weather file
- Processing: EnergyPlus simulation engine with cross-year support
- Output: Energy consumption results (heating/cooling by zone)

### 4. **Results Processing**
- Input: EnergyPlus CSV outputs
- Processing: Parse zone-level energy data and timeseries with timestamp normalization
- Output: Structured data stored in database

## Cross-Year Simulation Support

### Problem Addressed
EnergyPlus 9.4 has limitations when simulation periods span multiple calendar years:
- RunPeriod settings only accept month/day (not year) values
- Output CSV timestamps lack year information
- Cannot directly simulate periods like "2024-09-03 to 2025-11-07"

### Solution: Split-Run Algorithm
The pipeline automatically detects cross-year requests and implements a split-run approach:

#### Algorithm Overview (A1-A4)
1. **A1: Subperiod Splitting**
   - Split date range at year boundaries
   - Example: "2024-09-03 to 2025-11-07" becomes:
     - Period 1: 2024-09-03 to 2024-12-31
     - Period 2: 2025-01-01 to 2025-11-07

2. **A2: Individual Simulations with Weather Generation**
   - **A2.1**: Generate appropriate weather file for each subperiod
   - **A2.2**: Configure BIM2SIM RunPeriod for each subperiod
   - **A2.3**: Run separate EnergyPlus simulation for each period
   - Uses period-specific weather data with automatic download

3. **A3: Timestamp Normalization**
   - Add correct year to CSV timestamps
   - Handle edge cases (24:00:00 → next day 00:00:00)
   - Validate leap year dates (Feb 29)

4. **A4: Result Merging**
   - Concatenate all CSV results
   - Verify timestamp monotonicity
   - Generate unified output file

### Implementation Components

#### Core Modules
- **`ece/utils/split_run.py`**: Split-run algorithm implementation
- **`ece/pipeline_eplus_wrapper.py`**: Integration facade with automatic detection

#### Key Functions
- `split_into_subperiods()`: Date range splitting logic
- `generate_weather_for_subperiod()`: Weather file generation per subperiod
- `configure_runperiod()`: BIM2SIM RunPeriod configuration
- `normalize_timestamp_add_year()`: CSV timestamp processing
- `merge_runs()`: Result consolidation with validation
- `process_cross_year()`: Main orchestration function
- `run_user_request()`: Automatic single/cross-year detection

#### Error Handling
- Invalid date format validation
- Leap year boundary handling
- Timestamp monotonicity verification
- Partial simulation failure recovery
- Weather generation fallback mechanisms
- Comprehensive logging throughout

### Usage Examples

#### Single-Year Simulation
```python
# Automatically uses standard pipeline
result = run_user_request(
    ifc_file_path=Path("model.ifc"),
    weather_file_path=Path("weather.epw"),
    sensor_id="sensor_123",
    start_date="2024-06-01",
    end_date="2024-08-31"
)
```

#### Cross-Year Simulation
```python
# Automatically uses split-run approach
result = run_user_request(
    ifc_file_path=Path("model.ifc"),
    weather_file_path=Path("weather.epw"),
    sensor_id="sensor_123",
    start_date="2024-11-15",
    end_date="2025-03-20"
)
```

#### Result Structure
```python
{
    "success": True,
    "split_run_used": True,  # Indicates cross-year processing
    "merged_csv_file": "/path/to/merged_results.csv",
    "total_records": 4152,
    "date_range": {
        "start_date": "2024-11-15",
        "end_date": "2025-03-20",
        "spans_years": True
    },
    "metadata": {
        "subperiods": [
            {"year": 2024, "start_date": "2024-11-15", "end_date": "2024-12-31"},
            {"year": 2025, "start_date": "2025-01-01", "end_date": "2025-03-20"}
        ],
        "weather_handling": "Per-subperiod weather data generation"
    }
}
```

## Database Integration

### Tables Created
- **energy_buildings**: Building-level totals and metadata
- **energy_spaces**: Zone-level energy breakdown
- **energy_timeseries**: Hourly energy consumption data

### Data Flow
1. Simulation results → CSV parsing (with cross-year support)
2. Energy data extraction → Database storage
3. Sensor linking → Space energy attribution
4. Timestamped data → Visualization ready

## Key Features
- **Multi-zone Support**: Handles complex buildings with multiple thermal zones
- **Cross-Year Simulation**: Automatic handling of date ranges spanning multiple years
- **Smart Weather Generation**: Period-specific weather data with automatic download
- **Temporal Resolution**: Hourly energy consumption tracking
- **Sensor Integration**: Links energy data to comfort sensor locations
- **Robust Error Handling**: Comprehensive validation and logging
- **Transparent Operation**: Automatic single vs. cross-year detection
- **Visualization Ready**: Structured data for dashboard display

## Testing
Comprehensive test suite covers:
- Date range splitting edge cases
- Timestamp normalization scenarios
- Leap year handling
- Result merging validation
- Error condition handling

Test file: `tests/test_eplus_splitrun.py`

## Usage
The pipeline is integrated into the main dashboard application and runs automatically when building simulations are requested. Cross-year functionality is transparent to the user interface - users simply select their desired date range and the system automatically handles single vs. cross-year detection and processing.

### GUI Integration
The Streamlit dashboard automatically uses the enhanced cross-year pipeline:
- User selects start and end dates in the Energy tab
- System detects if simulation spans multiple years
- Appropriate weather data is generated for each subperiod
- Results are merged and displayed seamlessly
- No change to user interface - fully transparent operation