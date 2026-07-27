"""
EnergyPlus Cross-Year Split-Run Support

Handles splitting user date ranges across multiple years and merging results
to work around EnergyPlus 9.4 RunPeriod year limitations.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

import pandas as pd

from ece.utils.logging import init_logger

logger = init_logger(__name__)


def split_into_subperiods(start_date: str, end_date: str) -> List[dict]:
    """
    Split a date range into per-year sub-periods.
    
    Args:
        start_date: Start date string in format 'YYYY-MM-DD' (inclusive)
        end_date: End date string in format 'YYYY-MM-DD' (inclusive)
        
    Returns:
        List of dictionaries with keys: 'start_date', 'end_date', 'year'
        
    Example:
        split_into_subperiods('2024-09-03', '2025-11-07')
        → [{'start_date': '2024-09-03', 'end_date': '2024-12-31', 'year': 2024}, 
           {'start_date': '2025-01-01', 'end_date': '2025-11-07', 'year': 2025}]
    """
    # Parse string dates to date objects
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError as e:
        raise ValueError(f"Invalid date format. Expected YYYY-MM-DD. Error: {e}")
    
    if start > end:
        raise ValueError(f"End date must be after start date. Got: {start_date} to {end_date}")
    
    subperiods = []
    current_start = start
    
    while current_start <= end:
        # End of current year or user's end date, whichever is earlier
        year_end = date(current_start.year, 12, 31)
        current_end = min(year_end, end)
        
        # Add to subperiods as dictionary
        subperiods.append({
            'start_date': current_start.strftime('%Y-%m-%d'),
            'end_date': current_end.strftime('%Y-%m-%d'),
            'year': current_start.year
        })
        logger.info(f"Split subperiod: {current_start} → {current_end}")
        
        # Move to start of next year
        if current_end == year_end and current_end < end:
            current_start = date(current_start.year + 1, 1, 1)
        else:
            break
    
    logger.info(f"Split {start_date} → {end_date} into {len(subperiods)} subperiods")
    return subperiods


def configure_runperiod(project_object, start: date, end: date) -> None:
    """
    Configure BIM2SIM RunPeriod settings for a sub-run.
    
    Args:
        project_object: BIM2SIM project object with sim_settings
        start: RunPeriod start date
        end: RunPeriod end date
    """
    logger.info(f"Configuring RunPeriod: {start} → {end}")
    
    # Set basic RunPeriod configuration
    project_object.sim_settings.run_full_simulation = False
    project_object.sim_settings.set_run_period = True
    project_object.sim_settings.run_period_start_month = start.month
    project_object.sim_settings.run_period_start_day = start.day
    project_object.sim_settings.run_period_end_month = end.month
    project_object.sim_settings.run_period_end_day = end.day
    
    # Attempt to set start day of week if available
    try:
        weekday_name = start.strftime("%A")  # Monday, Tuesday, etc.
        if hasattr(project_object.sim_settings, 'run_period_start_day_of_week'):
            project_object.sim_settings.run_period_start_day_of_week = weekday_name
            logger.info(f"Set start day of week: {weekday_name}")
        else:
            logger.warning(
                f"Cannot set start day of week ({weekday_name}) - not supported by BIM2SIM version. "
                "HVAC schedules may be misaligned."
            )
    except Exception as e:
        logger.warning(f"Failed to set start day of week: {e}")


def normalize_timestamp_add_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """
    Parse EnergyPlus Date/Time column, fix 24:00:00 edge cases, and add year.
    
    Args:
        df: DataFrame with 'Date/Time' column from EnergyPlus CSV
        year: Year to assign to all timestamps
        
    Returns:
        DataFrame with 'timestamp' column containing ISO8601 datetime
    """
    if df.empty:
        logger.warning(f"Empty DataFrame for year {year}")
        return df
    
    if 'Date/Time' not in df.columns:
        raise ValueError("DataFrame must contain 'Date/Time' column")
    
    df_copy = df.copy()
    timestamps = []
    
    for dt_str in df_copy['Date/Time']:
        try:
            # EnergyPlus format: "MM/DD  HH:MM:SS" or "MM/DD HH:MM:SS"
            dt_str = dt_str.strip()
            
            # Handle 24:00:00 → next day 00:00:00
            if '24:00:00' in dt_str:
                # Replace 24:00:00 with 00:00:00 and add one day
                dt_str = dt_str.replace('24:00:00', '00:00:00')
                dt = datetime.strptime(f"{year}/{dt_str}", "%Y/%m/%d %H:%M:%S")
                dt += timedelta(days=1)
            else:
                dt = datetime.strptime(f"{year}/{dt_str}", "%Y/%m/%d %H:%M:%S")
            
            timestamps.append(dt)
            
        except ValueError as e:
            logger.error(f"Failed to parse timestamp '{dt_str}': {e}")
            raise
    
    df_copy['timestamp'] = timestamps
    
    # Sort by timestamp to ensure monotonicity
    df_copy = df_copy.sort_values('timestamp').reset_index(drop=True)
    
    # Validate no duplicates
    duplicates = df_copy['timestamp'].duplicated().sum()
    if duplicates > 0:
        logger.warning(f"Found {duplicates} duplicate timestamps after normalization")
    
    logger.info(f"Normalized {len(df_copy)} timestamps for year {year}")
    return df_copy


def merge_runs(csv_paths: List[Path], years: List[int]) -> pd.DataFrame:
    """
    Merge multiple EnergyPlus CSV outputs into a single DataFrame.
    
    Args:
        csv_paths: Paths to EnergyPlus CSV files
        years: Years corresponding to each CSV file
        
    Returns:
        Merged DataFrame with normalized timestamps
    """
    if len(csv_paths) != len(years):
        raise ValueError("csv_paths and years must have same length")
    
    if not csv_paths:
        raise ValueError("At least one CSV path required")
    
    logger.info(f"Merging {len(csv_paths)} CSV files")
    
    dfs = []
    for csv_path, year in zip(csv_paths, years):
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        
        logger.info(f"Loading {csv_path} for year {year}")
        df = pd.read_csv(csv_path)
        
        # Normalize timestamps for this year
        df = normalize_timestamp_add_year(df, year)
        dfs.append(df)
    
    # Concatenate all DataFrames
    merged_df = pd.concat(dfs, ignore_index=True)
    
    # Sort by timestamp
    merged_df = merged_df.sort_values('timestamp').reset_index(drop=True)
    
    # Validate monotonicity (allowing equal timestamps for same time)
    timestamps = merged_df['timestamp'].values
    if len(timestamps) > 1:
        non_monotonic = (timestamps[1:] < timestamps[:-1]).sum()
        if non_monotonic > 0:
            raise ValueError(f"Non-monotonic timestamps found: {non_monotonic} violations")
    
    # Check for overlaps (same timestamp with different data)
    duplicate_times = merged_df['timestamp'].duplicated(keep=False)
    if duplicate_times.any():
        logger.warning(f"Found {duplicate_times.sum()} potentially overlapping timestamps")
    
    logger.info(f"Merged DataFrame: {len(merged_df)} rows, {merged_df['timestamp'].min()} → {merged_df['timestamp'].max()}")
    return merged_df


def run_bim2sim(project_object, epw_path: Path) -> Path:
    """
    Run BIM2SIM simulation and return path to output CSV.
    
    Args:
        project_object: Configured BIM2SIM project
        epw_path: Path to EPW weather file
        
    Returns:
        Path to generated eplusout.csv file
    """
    # This is a placeholder - actual implementation would invoke the existing
    # BIM2SIM pipeline. For now, we'll delegate to the existing wrapper.
    logger.info(f"Running BIM2SIM simulation with EPW: {epw_path}")
    
    # Import here to avoid circular dependencies
    from bim2sim import run_project
    
    # Run the simulation
    run_project(project_object)
    
    # Find the output CSV - this path structure matches existing pipeline
    export_dir = project_object.project_path / "export" / "EnergyPlus" / "SimResults"
    csv_files = list(export_dir.glob("*/eplusout.csv"))
    
    if not csv_files:
        raise FileNotFoundError("No eplusout.csv found after simulation")
    
    # Use most recent CSV if multiple found
    csv_path = max(csv_files, key=lambda p: p.stat().st_mtime)
    logger.info(f"Found simulation output: {csv_path}")
    
    return csv_path


def generate_weather_for_subperiod(
    sensor_id: str,
    period_start: str,
    period_end: str,
    year: int,
    base_weather_file: Path,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None
) -> Path:
    """
    Generate weather file for a specific subperiod.
    
    Args:
        sensor_id: Sensor identifier
        period_start: Start date in format 'YYYY-MM-DD'
        period_end: End date in format 'YYYY-MM-DD'  
        year: Year for this subperiod
        base_weather_file: Base weather file path (for location info if needed)
        latitude: Location latitude (if known)
        longitude: Location longitude (if known)
        
    Returns:
        Path to generated weather file for this subperiod
    """
    from ece.pipeline_weather import generate_epw_for_location
    from datetime import datetime
    
    logger.info(f"Generating weather file for subperiod {period_start} → {period_end}")
    
    # If lat/lon not provided, try to extract from base weather file or use defaults
    if latitude is None or longitude is None:
        # For now, use default coordinates (Thessaloniki, Greece)
        # In a real implementation, this could be extracted from the existing EPW header
        latitude = latitude or 40.6401
        longitude = longitude or 22.9444
        logger.warning(f"Using default coordinates: {latitude}, {longitude}")
    
    # Convert date strings to datetime objects
    start_dt = datetime.strptime(period_start, '%Y-%m-%d')
    end_dt = datetime.strptime(period_end, '%Y-%m-%d')
    
    # Generate unique sensor ID for this subperiod to avoid filename conflicts
    subperiod_sensor_id = f"{sensor_id}_y{year}"
    
    try:
        # Generate EPW file using the existing weather pipeline
        # Use full_year=False to generate only for the specific period
        epw_path = generate_epw_for_location(
            space_id=subperiod_sensor_id,
            latitude=latitude,
            longitude=longitude,
            start=start_dt,
            end=end_dt,
            full_year=False  # Generate only for the specific period
        )
        
        logger.info(f"Generated weather file for subperiod: {epw_path}")
        return epw_path
        
    except Exception as e:
        logger.error(f"Failed to generate weather file for subperiod {period_start} → {period_end}: {e}")
        # Fallback to base weather file
        logger.warning(f"Falling back to base weather file: {base_weather_file}")
        return base_weather_file


def process_cross_year(
    ifc_file_path: Path,
    weather_file_path: Path,
    sensor_id: str,
    start_date: str,
    end_date: str,
    project_base_dir: Optional[Path] = None,
    ep_install_path: str = '/usr/local/EnergyPlus-9-4-0',
    conda_env_name: str = 'base',
    eplus_wrapper_func=None
) -> Dict[str, Any]:
    """
    Orchestrate cross-year simulation with weather data generation per subperiod.
    
    This function:
    1. Splits the date range into per-year subperiods  
    2. Generates appropriate weather file for each subperiod
    3. Runs EnergyPlus simulation for each subperiod
    4. Merges and validates the results
    
    Args:
        ifc_file_path: Path to IFC building model file
        weather_file_path: Path to base EPW weather file (used as template/fallback)
        sensor_id: Sensor identifier for organizing simulation results
        start_date: Start date in format 'YYYY-MM-DD'
        end_date: End date in format 'YYYY-MM-DD'
        project_base_dir: Base directory for simulation project
        ep_install_path: Path to EnergyPlus installation directory
        conda_env_name: Name of the conda environment containing bim2sim
        eplus_wrapper_func: Function to call for individual EnergyPlus runs
        
    Returns:
        Dictionary containing merged simulation results and metadata
    """
    from datetime import datetime
    
    logger.info(f"Processing cross-year simulation: {start_date} → {end_date}")
    
    try:
        # A1: Split into subperiods
        subperiods = split_into_subperiods(start_date, end_date)
        logger.info(f"Split into {len(subperiods)} subperiods")
        
        run_results = []
        
        # A2: Process each subperiod with weather data generation
        for i, period in enumerate(subperiods):
            period_start = period['start_date']
            period_end = period['end_date'] 
            year = period['year']
            
            logger.info(f"Processing subperiod {i+1}/{len(subperiods)}: {period_start} → {period_end} (Year {year})")
            
            # A2.1: Generate weather file for this subperiod
            # This ensures each subperiod has appropriate weather data
            try:
                subperiod_weather_file = generate_weather_for_subperiod(
                    sensor_id=sensor_id,
                    period_start=period_start,
                    period_end=period_end,
                    year=year,
                    base_weather_file=weather_file_path,
                    latitude=None,  # Will use defaults for now
                    longitude=None  # Will use defaults for now
                )
                logger.info(f"Using weather file for subperiod: {subperiod_weather_file}")
            except Exception as e:
                logger.warning(f"Weather generation failed for subperiod {period_start} → {period_end}: {e}")
                logger.warning("Falling back to base weather file - may contain incorrect data for cross-year simulation")
                subperiod_weather_file = weather_file_path
            
            # A2.2: Configure RunPeriod for this subperiod
            start_dt = datetime.strptime(period_start, '%Y-%m-%d').date()
            end_dt = datetime.strptime(period_end, '%Y-%m-%d').date()
            
            # For cross-year simulations, we need to ensure weather data covers the subperiod
            # The existing weather pipeline should handle this, but we'll pass the specific dates
            
            # A2.3: Run EnergyPlus simulation for this subperiod
            logger.info(f"Running EnergyPlus simulation for subperiod {period_start} → {period_end}")
            
            # Generate unique project directory for this subperiod to avoid conflicts
            if project_base_dir:
                subperiod_project_dir = project_base_dir / f"subperiod_{year}_{start_dt.month:02d}{start_dt.day:02d}_{end_dt.month:02d}{end_dt.day:02d}"
            else:
                subperiod_project_dir = None
            
            # Call the EnergyPlus wrapper for this subperiod with appropriate weather file
            result = eplus_wrapper_func(
                ifc_file_path=ifc_file_path,
                weather_file_path=subperiod_weather_file,  # Use subperiod-specific weather file
                sensor_id=f"{sensor_id}_subperiod_{year}",
                project_base_dir=subperiod_project_dir,
                ep_install_path=ep_install_path,
                conda_env_name=conda_env_name
            )
            
            # Add metadata about this subperiod
            if isinstance(result, dict):
                result["metadata"] = {
                    "year": year,
                    "start_date": period_start,
                    "end_date": period_end,
                    "subperiod_index": i + 1,
                    "total_subperiods": len(subperiods)
                }
            
            run_results.append(result)
            
            # Check if this subperiod failed
            if not result.get("success", False):
                logger.error(f"Subperiod {period_start} → {period_end} failed: {result.get('error', 'Unknown error')}")
                # Continue with other subperiods but note the failure
        
        # A3 & A4: Merge results
        logger.info("Merging all subperiod results")
        merged_result = merge_runs(run_results, sensor_id)
        
        # Add cross-year metadata
        if merged_result.get("success", False):
            merged_result.update({
                "split_run_used": True,
                "date_range": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "spans_years": True
                },
                "metadata": {
                    "subperiods": subperiods,
                    "algorithm": "A1-A4 Cross-Year Split-Run",
                    "weather_handling": "Per-subperiod weather data generation"
                }
            })
        
        # Log completion with warnings about limitations
        logger.info("Cross-year simulation complete")
        logger.warning(
            "Cross-year simulation complete. Note: No thermal state carry-over between years. "
            "Initial conditions reset at each year boundary."
        )
        
        return merged_result
        
    except Exception as e:
        error_msg = f"Cross-year processing failed: {str(e)}"
        logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "message": "Cross-year simulation failed",
            "split_run_used": True
        }
