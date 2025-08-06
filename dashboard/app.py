# -*- coding: utf-8 -*-
"""Streamlit dashboard for the Energy Comfortness Tool (ECT)."""

from __future__ import annotations

# versioning
_VERSION = "0.0.4"
_VERDATE = "04 Aug 2025"

import os, sys, math, logging, importlib.util, shutil
from pathlib import Path
from datetime import datetime, timedelta, date, timezone
from typing import Optional

import altair as alt

# ------------------- altair optimizations --------------
alt.renderers.enable("default", embed_options={"renderer": "canvas"})
alt.data_transformers.disable_max_rows()
# Fix altair deprecation warning - use theme instead of themes
try:
    alt.theme.enable('default')
except AttributeError:
    # Fallback for older altair versions
    alt.themes.enable('default')

import pandas as pd
import numpy as np
import streamlit as st
import joblib
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

from db.session import SessionLocal  # type: ignore
from db.models import Measurement, Weather, Prediction, TrainedModel, EnergyBuilding, EnergySpace, EnergyTimeSeries  # type: ignore[attr-defined]
from ece.pipeline_ml import main_train_all_targets  # type: ignore
from ece.feature_map import MAP as FEATURE_MAP, TIME_DRIVERS
from ece.weather_api import fetch_open_meteo
from ece.pipeline_weather import generate_epw_for_location  # type: ignore
from ece.pipeline_eplus_wrapper import run_eplus_simulation_async, test_bim2sim_environment  # type: ignore


def _convert_decimal_to_float(value):
    """
    Utility function to convert Decimal objects to float to avoid PyArrow serialization issues.
    
    Args:
        value: Any value that might be a Decimal
        
    Returns:
        float if value was Decimal, otherwise the original value
    """
    from decimal import Decimal
    if isinstance(value, Decimal):
        return float(value)
    return value


def _store_energy_simulation_results(simulation_results: dict, sensor_id: str, 
                                   ifc_file_path: str, epw_file_path: str) -> bool:
    """
    Store energy simulation results in the database with timestamped energy data.
    
    Args:
        simulation_results: Dictionary containing simulation results from EnergyPlus
        sensor_id: Sensor identifier that triggered the simulation
        ifc_file_path: Path to the IFC file used
        epw_file_path: Path to the EPW weather file used
        
    Returns:
        bool: True if storage was successful, False otherwise
    """
    logger.info(f"Storing energy simulation results for sensor: {sensor_id}")
    logger.debug(f"Simulation results keys: {list(simulation_results.keys())}")
    logger.debug(f"Simulation results structure: {simulation_results}")
    
    try:
        with SessionLocal() as session:
            # Parse energy data from simulation results
            # The simulation results structure might vary, so we need to handle different key names
            if 'eplus_results_path' in simulation_results:
                actual_results_dir = Path(simulation_results['eplus_results_path'])
            elif 'project_path' in simulation_results:
                # Construct the results path from project_path
                project_path = Path(simulation_results['project_path'])
                # Results are typically in: project_path/export/EnergyPlus/SimResults/{sensor_timestamp}/
                export_dir = project_path / "export" / "EnergyPlus" / "SimResults"
                if export_dir.exists():
                    # Find the actual results directory (usually the first subdirectory)
                    result_dirs = [d for d in export_dir.iterdir() if d.is_dir()]
                    if result_dirs:
                        actual_results_dir = result_dirs[0]
                        logger.info(f"Found EnergyPlus results directory: {actual_results_dir}")
                    else:
                        logger.error(f"No result directories found in: {export_dir}")
                        return False
                else:
                    logger.error(f"Export directory not found: {export_dir}")
                    return False
            else:
                logger.error(f"Neither 'eplus_results_path' nor 'project_path' found in simulation_results. Available keys: {list(simulation_results.keys())}")
                return False
            
            energy_data = _parse_energyplus_outputs(actual_results_dir)
            
            if not energy_data or ('heating' not in energy_data and 'cooling' not in energy_data):
                logger.warning("No energy data available to store")
                return False
            
            # Extract simulation metadata
            simulation_timestamp = datetime.now()
            
            # Always extract the simulation year from the EPW file, not from session state
            # The session state dates are for filtering/viewing, not for the actual simulation period
            simulation_year = _get_simulation_year_from_epw(actual_results_dir)
            if simulation_year:
                simulation_start = datetime(simulation_year, 1, 1)
                simulation_end = datetime(simulation_year, 12, 31)
                logger.info(f"Using EPW file simulation period: {simulation_start} to {simulation_end}")
            else:
                # Fallback to 2024 if EPW year extraction fails
                simulation_year = 2024
                simulation_start = datetime(simulation_year, 1, 1) 
                simulation_end = datetime(simulation_year, 12, 31)
                logger.warning(f"Could not extract year from EPW, using default 2024: {simulation_start} to {simulation_end}")
            
            # Calculate building-level totals
            total_heating_kwh = energy_data.get('heating', {}).get('total_energy_kwh', 0)
            total_cooling_kwh = energy_data.get('cooling', {}).get('total_energy_kwh', 0)
            total_energy_kwh = total_heating_kwh + total_cooling_kwh
            
            peak_heating_w = energy_data.get('heating', {}).get('peak_rate_w', 0)
            peak_cooling_w = energy_data.get('cooling', {}).get('peak_rate_w', 0)
            
            # Get zone count
            zone_energy = energy_data.get('zone_energy', {})
            zones_count = len(zone_energy)
            
            logger.info(f"📊 Energy data parsing summary:")
            logger.info(f"   - Heating data: {'✅' if 'heating' in energy_data else '❌'}")
            logger.info(f"   - Cooling data: {'✅' if 'cooling' in energy_data else '❌'}")
            logger.info(f"   - Zone energy data: {'✅' if zone_energy else '❌'} ({zones_count} zones)")
            logger.info(f"   - Space names: {'✅' if energy_data.get('space_names') else '❌'} ({len(energy_data.get('space_names', {}))} names)")
            
            if zone_energy:
                logger.info(f"   - Zone IDs found: {list(zone_energy.keys())}")
                for zone_id, zone_data in zone_energy.items():
                    has_heating_ts = bool(zone_data.get('heating_timeseries'))
                    has_cooling_ts = bool(zone_data.get('cooling_timeseries'))
                    logger.info(f"     Zone '{zone_id}': heating_ts={has_heating_ts}, cooling_ts={has_cooling_ts}")
            else:
                logger.warning("   ⚠️ No zone energy data means EnergySpace and EnergyTimeSeries records will NOT be created!")
            
            # Prepare time series data (limit to reasonable size for database storage)
            heating_timeseries = energy_data.get('heating', {}).get('hourly_data', [])[:8760]  # Max 1 year
            cooling_timeseries = energy_data.get('cooling', {}).get('hourly_data', [])[:8760]  # Max 1 year
            
            # Get file paths from simulation results or use the function parameters as fallback
            weather_file_path = simulation_results.get('weather_file', epw_file_path)
            ifc_file_path_from_results = simulation_results.get('ifc_file', ifc_file_path)
            
            # Create EnergyBuilding record
            energy_building = EnergyBuilding(
                simulation_timestamp=simulation_timestamp,
                simulation_start_date=simulation_start,
                simulation_end_date=simulation_end,
                weather_file_path=str(weather_file_path),
                ifc_file_path=str(ifc_file_path_from_results),
                eplus_results_path=str(actual_results_dir),
                total_heating_kwh=total_heating_kwh,
                total_cooling_kwh=total_cooling_kwh,
                total_energy_kwh=total_energy_kwh,
                peak_heating_w=peak_heating_w,
                peak_cooling_w=peak_cooling_w,
                zones_count=zones_count,
                heating_timeseries=heating_timeseries,
                cooling_timeseries=cooling_timeseries
            )
            
            session.add(energy_building)
            session.flush()  # Get the building_id
            
            logger.info(f"Created EnergyBuilding record with ID: {energy_building.building_id}")
            
            # Create EnergySpace records and timestamped data for each zone
            space_names = energy_data.get('space_names', {})
            spaces_created = 0
            timeseries_points_created = 0
            
            # Create datetime range for the time series data
            num_data_points = max(len(heating_timeseries), len(cooling_timeseries))
            if num_data_points > 0:
                # Create hourly timestamps from simulation start (EnergyPlus generates hourly data)
                timestamps = [simulation_start + timedelta(hours=i) for i in range(num_data_points)]
                logger.info(f"Creating {num_data_points} hourly timestamped data points from {timestamps[0]} to {timestamps[-1]}")
            else:
                timestamps = []
                logger.warning("No time series data available for timestamp creation")
            
            for zone_id, zone_data in zone_energy.items():
                # Get zone name from space mapping (case-insensitive lookup)
                zone_name = space_names.get(zone_id.upper(), zone_id)
                
                logger.info(f"🏠 Processing zone: '{zone_id}' -> '{zone_name}'")
                
                # Extract zone-level energy data  
                heating_kwh = float(zone_data.get('heating_kwh', 0))
                cooling_kwh = float(zone_data.get('cooling_kwh', 0))
                total_kwh = heating_kwh + cooling_kwh
                
                logger.debug(f"   Energy totals: heating={heating_kwh:.2f}kWh, cooling={cooling_kwh:.2f}kWh, total={total_kwh:.2f}kWh")
                
                # Calculate percentages
                heating_percentage = float((heating_kwh / total_heating_kwh * 100) if total_heating_kwh > 0 else 0)
                cooling_percentage = float((cooling_kwh / total_cooling_kwh * 100) if total_cooling_kwh > 0 else 0)
                
                # Get floor area if available
                floor_area_m2 = zone_data.get('floor_area_m2')
                volume_m3 = zone_data.get('volume_m3')
                
                # Calculate intensity metrics
                heating_intensity_kwh_m2 = float(heating_kwh / floor_area_m2) if floor_area_m2 and floor_area_m2 > 0 else None
                cooling_intensity_kwh_m2 = float(cooling_kwh / floor_area_m2) if floor_area_m2 and floor_area_m2 > 0 else None
                
                # Create EnergySpace record
                energy_space = EnergySpace(
                    building_id=energy_building.building_id,
                    sensor_id=zone_name,  # Use zone_name as sensor_id to match measurements tab naming
                    zone_id=zone_id,
                    zone_name=zone_name,
                    zone_type=zone_data.get('zone_type'),
                    heating_kwh=heating_kwh,
                    cooling_kwh=cooling_kwh,
                    total_kwh=total_kwh,
                    heating_percentage=heating_percentage,
                    cooling_percentage=cooling_percentage,
                    floor_area_m2=floor_area_m2,
                    volume_m3=volume_m3,
                    heating_intensity_kwh_m2=heating_intensity_kwh_m2,
                    cooling_intensity_kwh_m2=cooling_intensity_kwh_m2
                )
                
                session.add(energy_space)
                session.flush()  # Get the space_id
                spaces_created += 1
                
                logger.info(f"   ✅ Created EnergySpace record with ID: {energy_space.space_id}")
                
                # Create timestamped energy data for this zone
                heating_series = zone_data.get('heating_timeseries', [])
                cooling_series = zone_data.get('cooling_timeseries', [])
                
                logger.info(f"   🕐 Timeseries check: heating={len(heating_series)} points, cooling={len(cooling_series)} points, timestamps={len(timestamps)}")
                
                if timestamps and heating_series and cooling_series:
                    # Ensure we have data to work with
                    max_points = min(len(timestamps), len(heating_series), len(cooling_series))
                    logger.info(f"   📊 Creating {max_points} time series points for zone {zone_id}")
                    
                    # Batch insert time series data
                    timeseries_data = []
                    cumulative_heating = 0
                    cumulative_cooling = 0
                    
                    for i in range(max_points):
                        # Calculate power (W) and cumulative energy (kWh)
                        heating_power = heating_series[i] if i < len(heating_series) else 0
                        cooling_power = cooling_series[i] if i < len(cooling_series) else 0
                        
                        # Convert power to energy increment (assuming 1-hour timesteps)
                        heating_energy_increment = heating_power / 1000.0  # W to kWh for 1 hour
                        cooling_energy_increment = cooling_power / 1000.0  # W to kWh for 1 hour
                        
                        cumulative_heating += heating_energy_increment
                        cumulative_cooling += cooling_energy_increment
                        
                        timeseries_data.append({
                            'space_id': energy_space.space_id,
                            'timestamp': timestamps[i],
                            'heating_power_w': heating_power,
                            'cooling_power_w': cooling_power,
                            'heating_energy_kwh': cumulative_heating,
                            'cooling_energy_kwh': cumulative_cooling
                        })
                    
                    # Bulk insert time series data
                    if timeseries_data:
                        session.bulk_insert_mappings(EnergyTimeSeries, timeseries_data)
                        timeseries_points_created += len(timeseries_data)
                        logger.info(f"   SUCCESS Stored {len(timeseries_data)} time series points for zone {zone_id}")
                    else:
                        logger.warning(f"   ERROR No timeseries data to store for zone {zone_id}")
                else:
                    reasons = []
                    if not timestamps:
                        reasons.append("no timestamps")
                    if not heating_series:
                        reasons.append("no heating timeseries")
                    if not cooling_series:
                        reasons.append("no cooling timeseries")
                    logger.warning(f"   ERROR No time series data will be stored for zone {zone_id}: {', '.join(reasons)}")
            
            # Commit the transaction
            session.commit()
            
            logger.info(f"SUCCESS Successfully stored energy simulation results:")
            logger.info(f"   - Building record ID: {energy_building.building_id}")
            logger.info(f"   - Total energy: {total_energy_kwh:.1f} kWh")
            logger.info(f"   - Zones stored: {spaces_created}")
            logger.info(f"   - Time series points stored: {timeseries_points_created}")
            logger.info(f"   - Results path: {actual_results_dir}")
            
            return True
            
    except Exception as e:
        logger.error(f"ERROR Error storing energy simulation results: {str(e)}", exc_info=True)
        return False


def _load_space_names_from_csv(eplus_results_path: str) -> dict:
    """
    Load space names mapping from space.csv file for the given simulation results.
    
    Args:
        eplus_results_path: Path to the EnergyPlus results directory
        
    Returns:
        Dictionary mapping zone IDs (uppercase) to space names, or empty dict if not found
    """
    try:
        # Navigate to the space.csv file location
        results_dir = Path(eplus_results_path)
        export_dir = results_dir.parent.parent.parent  # Go up from SimResults/{uuid} to export/
        space_csv_path = export_dir / "space.csv"
        
        logger.debug(f"Looking for space.csv at: {space_csv_path}")
        
        if not space_csv_path.exists():
            logger.warning(f"No space.csv file found at: {space_csv_path}")
            return {}
        
        logger.info(f"Loading space names from: {space_csv_path}")
        space_df = pd.read_csv(space_csv_path)
        
        if len(space_df.columns) < 3:
            logger.warning(f"Space CSV has insufficient columns: {len(space_df.columns)} (need at least 3)")
            return {}
        
        # Use 2nd column as zone ID and 3rd column as space name
        zone_id_col = space_df.columns[1]  # 2nd column: ID
        space_name_col = space_df.columns[2]  # 3rd column: long_name
        
        # Filter out rows with missing values
        valid_rows = space_df.dropna(subset=[zone_id_col, space_name_col])
        
        if len(valid_rows) == 0:
            logger.warning("No valid space mapping rows found in space.csv")
            return {}
        
        # Create case-insensitive mapping by converting zone IDs to uppercase
        zone_ids_upper = valid_rows[zone_id_col].astype(str).str.upper()
        space_names = valid_rows[space_name_col].astype(str)
        
        space_mapping = dict(zip(zone_ids_upper, space_names))
        logger.info(f"SUCCESS Loaded {len(space_mapping)} space names from space.csv")
        logger.debug(f"Space IDs from CSV: {list(space_mapping.keys())}")
        
        return space_mapping
        
    except Exception as e:
        logger.error(f"Error loading space names from CSV: {e}", exc_info=True)
        return {}


def _get_energy_data_from_database(sensor_id: Optional[str] = None, limit: int = 1) -> Optional[dict]:
    """
    Retrieve energy simulation data from the database.
    
    Args:
        sensor_id: Optional sensor ID to filter by (if None, gets latest for any sensor)
        limit: Number of records to retrieve (default 1 for latest)
        
    Returns:
        Dictionary containing energy data in visualization format, or None
    """
    logger.info(f"Retrieving energy data from database for sensor: {sensor_id or 'any'}")
    
    try:
        with SessionLocal() as session:
            # Get date range from session state if available
            start_dt = st.session_state.get('start_dt')
            end_dt = st.session_state.get('end_dt')
            
            # Query for energy buildings - try to find one that matches the date range
            buildings_query = session.query(EnergyBuilding).order_by(EnergyBuilding.simulation_timestamp.desc())
            buildings = buildings_query.all()
            
            if not buildings:
                logger.info("No energy simulation data found in database")
                return None
            
            # Find the building that has data in the selected date range
            selected_building = None
            for building in buildings:
                # Get spaces for this building
                spaces = session.query(EnergySpace).filter_by(building_id=building.building_id).all()
                if spaces:
                    space_ids = [space.space_id for space in spaces]
                    
                    # Check if this building has data in the selected date range
                    if start_dt and end_dt:
                        # Convert dates to datetime if needed
                        filter_start_dt = start_dt
                        filter_end_dt = end_dt
                        if hasattr(start_dt, 'date'):
                            filter_start_dt = datetime.combine(start_dt, datetime.min.time())
                        if hasattr(end_dt, 'date'):
                            filter_end_dt = datetime.combine(end_dt, datetime.min.time())
                        
                        # Check if building has data in this range
                        data_count = session.query(EnergyTimeSeries).filter(
                            EnergyTimeSeries.space_id.in_(space_ids),
                            EnergyTimeSeries.timestamp >= filter_start_dt,
                            EnergyTimeSeries.timestamp <= filter_end_dt
                        ).count()
                        
                        if data_count > 0:
                            selected_building = building
                            logger.info(f"Found building {building.building_id} with {data_count} records in date range {filter_start_dt.date()} to {filter_end_dt.date()}")
                            break
                    else:
                        # No date filter - use the most recent building
                        selected_building = building
                        break
            
            # Fallback to most recent building if no match found
            if not selected_building:
                selected_building = buildings[0]
                logger.warning(f"No building found with data in selected date range, using most recent building {selected_building.building_id}")
            
            building = selected_building
            logger.info(f"Retrieved energy building record ID: {building.building_id}")
            logger.info(f"Simulation from: {building.simulation_timestamp}")
            
            # Get associated spaces
            spaces_query = session.query(EnergySpace).filter(
                EnergySpace.building_id == building.building_id
            )
            
            # If a specific sensor_id is selected (not "latest"), filter to only that space
            if sensor_id and sensor_id != "latest":
                spaces_query = spaces_query.filter(EnergySpace.sensor_id == sensor_id)
                logger.info(f"Filtering to space(s) for specific sensor: {sensor_id}")
            
            spaces = spaces_query.all()
            logger.info(f"Found {len(spaces)} energy spaces for building {building.building_id}")
            
            # Load space names from space.csv to filter only valid spaces
            space_names_from_csv = _load_space_names_from_csv(building.eplus_results_path)
            logger.info(f"Loaded {len(space_names_from_csv)} space names from space.csv")
            
            # Filter spaces to only include those found in space.csv
            valid_spaces = []
            for space in spaces:
                zone_id_upper = space.zone_id.upper()
                if zone_id_upper in space_names_from_csv:
                    valid_spaces.append(space)
                    logger.debug(f"Including space: {space.zone_id} -> {space_names_from_csv[zone_id_upper]}")
                else:
                    logger.debug(f"Excluding space not found in space.csv: {space.zone_id}")
            
            logger.info(f"Filtered to {len(valid_spaces)} valid spaces (found in space.csv)")
            
            # Log the filtering context for clarity
            if sensor_id and sensor_id != "latest":
                if len(valid_spaces) == 1:
                    space_name = space_names_from_csv.get(valid_spaces[0].zone_id.upper(), valid_spaces[0].zone_id)
                    logger.info(f"📍 Showing energy data for specific space: '{space_name}' (sensor: {sensor_id})")
                elif len(valid_spaces) == 0:
                    logger.warning(f"ERROR No spaces found for sensor {sensor_id}")
                else:
                    logger.info(f"📍 Showing energy data for {len(valid_spaces)} spaces matching sensor: {sensor_id}")
            else:
                logger.info(f"DATA Showing energy data for all {len(valid_spaces)} spaces in building")
            
            # Initialize filtered totals - will be recalculated from space data if date filtering is applied
            # For specific sensor selection, start with 0 and accumulate only from selected spaces
            if sensor_id and sensor_id != "latest":
                # For space-specific view, start with 0 and accumulate from selected spaces only
                filtered_total_heating_kwh = 0.0
                filtered_total_cooling_kwh = 0.0
                filtered_peak_heating_w = 0.0
                filtered_peak_cooling_w = 0.0
                is_space_specific = True
                logger.info("📍 Space-specific mode: Will calculate totals from selected space(s) only")
            else:
                # For building-wide view, use building totals as baseline
                filtered_total_heating_kwh = float(building.total_heating_kwh)
                filtered_total_cooling_kwh = float(building.total_cooling_kwh)
                filtered_peak_heating_w = float(building.peak_heating_w) if building.peak_heating_w else 0
                filtered_peak_cooling_w = float(building.peak_cooling_w) if building.peak_cooling_w else 0
                is_space_specific = False
                logger.info("🏢 Building-wide mode: Using building totals as baseline")
            
            # Check if date filtering is applied
            start_dt = st.session_state.get('start_dt')
            end_dt = st.session_state.get('end_dt')
            is_date_filtered = start_dt is not None and end_dt is not None
            
            if is_date_filtered or is_space_specific:
                if is_date_filtered:
                    logger.info(f"Date filtering detected: {start_dt} to {end_dt} - will recalculate totals from filtered time series data")
                if is_space_specific:
                    logger.info("Space filtering detected - will recalculate totals from selected space(s) only")
                    
                # Reset totals to be recalculated
                filtered_total_heating_kwh = 0.0
                filtered_total_cooling_kwh = 0.0
                filtered_peak_heating_w = 0.0
                filtered_peak_cooling_w = 0.0
            
            # Format data to match the structure expected by visualization functions
            # For space-specific view, we'll populate hourly_data from the space timeseries later
            # For building-wide view, use building-level timeseries
            if is_space_specific:
                # Start with empty arrays - will be populated from space timeseries
                heating_hourly_data = []
                cooling_hourly_data = []
                building_timestamps = []  # Will be populated from space data
            else:
                # Use building-level timeseries for all-spaces view
                heating_hourly_data = building.heating_timeseries or []
                cooling_hourly_data = building.cooling_timeseries or []
                
                # Get REAL timestamps from database for building-wide view
                building_timestamps = []
                if heating_hourly_data:  # Only query if we have data
                    timestamps_query = session.query(EnergyTimeSeries.timestamp).filter(
                        EnergyTimeSeries.building_id == building_id
                    ).order_by(EnergyTimeSeries.timestamp)
                    
                    # Apply date filtering if provided
                    if start_dt and end_dt:
                        filter_start_dt = start_dt
                        filter_end_dt = end_dt
                        if hasattr(start_dt, 'date'):
                            filter_start_dt = datetime.combine(start_dt, datetime.min.time())
                        if hasattr(end_dt, 'date'):
                            filter_end_dt = datetime.combine(end_dt, datetime.min.time())
                        timestamps_query = timestamps_query.filter(
                            EnergyTimeSeries.timestamp >= filter_start_dt,
                            EnergyTimeSeries.timestamp <= filter_end_dt
                        )
                    
                    building_timestamps = [ts[0] for ts in timestamps_query.distinct().all()]
            
            energy_data = {
                'heating': {
                    'total_energy_kwh': filtered_total_heating_kwh,
                    'peak_rate_w': filtered_peak_heating_w,
                    'hourly_data': heating_hourly_data,
                    'zones_detected': len(valid_spaces)  # Add zones count for visualization
                },
                'cooling': {
                    'total_energy_kwh': filtered_total_cooling_kwh,
                    'peak_rate_w': filtered_peak_cooling_w,
                    'hourly_data': cooling_hourly_data,
                    'zones_detected': len(valid_spaces)  # Add zones count for visualization
                },
                'zone_energy': {},
                'space_names': space_names_from_csv,  # Use space names from CSV
                'timestamps': building_timestamps,  # Use REAL database timestamps
                'building_metadata': {
                    'building_id': building.building_id,
                    'simulation_timestamp': building.simulation_timestamp,
                    'simulation_start_date': building.simulation_start_date,
                    'simulation_end_date': building.simulation_end_date,
                    'weather_file_path': building.weather_file_path,
                    'ifc_file_path': building.ifc_file_path,
                    'eplus_results_path': building.eplus_results_path,
                    'zones_count': building.zones_count,
                    'is_space_specific': is_space_specific,  # Add flag for visualization
                    'selected_sensor_id': sensor_id if is_space_specific else None
                }
            }
            
            # Add space-level data (only for valid spaces)
            space_heating_timeseries = []  # Accumulate heating timeseries for space-specific view
            space_cooling_timeseries = []  # Accumulate cooling timeseries for space-specific view
            
            for space in valid_spaces:
                zone_id = space.zone_id
                
                # Get timestamped data for this space
                timeseries_query = session.query(EnergyTimeSeries).filter(
                    EnergyTimeSeries.space_id == space.space_id
                ).order_by(EnergyTimeSeries.timestamp)
                
                # Apply date filtering if start_dt and end_dt are available in session state
                if is_date_filtered:
                    # Convert to datetime if they are dates
                    filter_start_dt = start_dt
                    filter_end_dt = end_dt
                    
                    if hasattr(start_dt, 'date'):
                        filter_start_dt = datetime.combine(start_dt, datetime.min.time())
                    if hasattr(end_dt, 'date'):
                        filter_end_dt = datetime.combine(end_dt, datetime.min.time())
                    
                    timeseries_query = timeseries_query.filter(
                        EnergyTimeSeries.timestamp >= filter_start_dt,
                        EnergyTimeSeries.timestamp <= filter_end_dt
                    )
                    logger.debug(f"Applied date filtering for space {zone_id}: {filter_start_dt} to {filter_end_dt}")
                
                timeseries_records = timeseries_query.all()
                logger.debug(f"Retrieved {len(timeseries_records)} timestamped data points for space {zone_id}")
                
                # Extract time series arrays for this zone with REAL timestamps from database
                heating_timeseries = [float(record.heating_power_w) for record in timeseries_records]
                cooling_timeseries = [float(record.cooling_power_w) for record in timeseries_records]
                space_timestamps = [record.timestamp for record in timeseries_records]
                
                # For space-specific view, accumulate timeseries data
                if is_space_specific:
                    if not space_heating_timeseries:
                        # Initialize with first space's data
                        space_heating_timeseries = heating_timeseries.copy()
                        space_cooling_timeseries = cooling_timeseries.copy()
                    else:
                        # Add subsequent spaces' data (element-wise addition)
                        min_len = min(len(space_heating_timeseries), len(heating_timeseries))
                        space_heating_timeseries = [space_heating_timeseries[i] + heating_timeseries[i] 
                                                  for i in range(min_len)]
                        space_cooling_timeseries = [space_cooling_timeseries[i] + cooling_timeseries[i] 
                                                  for i in range(min(len(space_cooling_timeseries), len(cooling_timeseries)))]
                
                # Calculate filtered energy totals if date filtering is applied or space-specific mode
                if (is_date_filtered or is_space_specific) and heating_timeseries and cooling_timeseries:
                    # Calculate energy from power data (assuming hourly intervals)
                    filtered_heating_kwh = float(sum(heating_timeseries)) / 1000.0  # W to kWh for hourly data
                    filtered_cooling_kwh = float(sum(cooling_timeseries)) / 1000.0  # W to kWh for hourly data
                    filtered_total_kwh = filtered_heating_kwh + filtered_cooling_kwh
                    
                    # Find peak power values for this zone in the filtered period
                    zone_peak_heating_w = float(max(heating_timeseries)) if heating_timeseries else 0
                    zone_peak_cooling_w = float(max(cooling_timeseries)) if cooling_timeseries else 0
                    
                    # Accumulate building-level filtered totals
                    filtered_total_heating_kwh += filtered_heating_kwh
                    filtered_total_cooling_kwh += filtered_cooling_kwh
                    filtered_peak_heating_w = max(filtered_peak_heating_w, zone_peak_heating_w)
                    filtered_peak_cooling_w = max(filtered_peak_cooling_w, zone_peak_cooling_w)
                    
                    logger.debug(f"Zone {zone_id} filtered energy: {filtered_heating_kwh:.2f} kWh heating, {filtered_cooling_kwh:.2f} kWh cooling")
                else:
                    # Use full simulation totals
                    filtered_heating_kwh = float(space.heating_kwh)
                    filtered_cooling_kwh = float(space.cooling_kwh)
                    filtered_total_kwh = float(space.total_kwh)
                
                # Calculate percentages based on filtered totals (will be recalculated later)
                space_heating_percentage = float(space.heating_percentage) if space.heating_percentage else 0
                space_cooling_percentage = float(space.cooling_percentage) if space.cooling_percentage else 0
                
                energy_data['zone_energy'][zone_id] = {
                    'heating_kwh': filtered_heating_kwh,
                    'cooling_kwh': filtered_cooling_kwh,
                    'total_kwh': filtered_total_kwh,
                    'heating_percentage': space_heating_percentage,  # Will be recalculated below
                    'cooling_percentage': space_cooling_percentage,  # Will be recalculated below
                    'floor_area_m2': float(space.floor_area_m2) if space.floor_area_m2 else None,
                    'volume_m3': float(space.volume_m3) if space.volume_m3 else None,
                    'heating_intensity_kwh_m2': float(space.heating_intensity_kwh_m2) if space.heating_intensity_kwh_m2 else None,
                    'cooling_intensity_kwh_m2': float(space.cooling_intensity_kwh_m2) if space.cooling_intensity_kwh_m2 else None,
                    'zone_type': space.zone_type,
                    'sensor_id': space.sensor_id,  # Include sensor association
                    'heating_timeseries': heating_timeseries,  # Add timestamped data
                    'cooling_timeseries': cooling_timeseries   # Add timestamped data
                }
            
            # Update hourly data for space-specific view
            if is_space_specific and space_heating_timeseries:
                energy_data['heating']['hourly_data'] = space_heating_timeseries
                energy_data['cooling']['hourly_data'] = space_cooling_timeseries
                energy_data['timestamps'] = space_timestamps  # Use REAL database timestamps
                logger.info(f"DATA Using space-specific timeseries data: {len(space_heating_timeseries)} heating points, {len(space_cooling_timeseries)} cooling points with {len(space_timestamps)} real timestamps")
            
            # Update the energy_data with filtered totals if date filtering was applied or space-specific mode
            if is_date_filtered or is_space_specific:
                energy_data['heating']['total_energy_kwh'] = filtered_total_heating_kwh
                energy_data['cooling']['total_energy_kwh'] = filtered_total_cooling_kwh
                energy_data['heating']['peak_rate_w'] = filtered_peak_heating_w
                energy_data['cooling']['peak_rate_w'] = filtered_peak_cooling_w
                
                mode_text = []
                if is_date_filtered:
                    mode_text.append("filtered data")
                if is_space_specific:
                    mode_text.append("space-specific data")
                
                logger.info(f"Updated totals with {' and '.join(mode_text)}:")
                logger.info(f"  - Heating: {filtered_total_heating_kwh:.1f} kWh (peak: {filtered_peak_heating_w:.0f} W)")
                logger.info(f"  - Cooling: {filtered_total_cooling_kwh:.1f} kWh (peak: {filtered_peak_cooling_w:.0f} W)")
                
                # Check if date filtering resulted in no data
                if is_date_filtered and (filtered_total_heating_kwh == 0 and filtered_total_cooling_kwh == 0):
                    # Get actual date range of energy data to suggest to user
                    from sqlalchemy import func
                    space_ids = [space.space_id for space in spaces]
                    if space_ids:
                        date_range = session.query(
                            func.min(EnergyTimeSeries.timestamp).label('min_date'),
                            func.max(EnergyTimeSeries.timestamp).label('max_date')
                        ).filter(EnergyTimeSeries.space_id.in_(space_ids)).first()
                        
                        if date_range and date_range.min_date:
                            logger.warning(f"WARNING Date filtering resulted in no data. Available data range: {date_range.min_date.date()} to {date_range.max_date.date()}")
                            energy_data['date_filter_warning'] = {
                                'min_date': date_range.min_date,
                                'max_date': date_range.max_date,
                                'filtered_start': start_dt,
                                'filtered_end': end_dt
                            }
                
                # Recalculate zone percentages based on filtered totals
                for zone_id, zone_data in energy_data['zone_energy'].items():
                    if filtered_total_heating_kwh > 0:
                        zone_data['heating_percentage'] = (zone_data['heating_kwh'] / filtered_total_heating_kwh) * 100
                    else:
                        zone_data['heating_percentage'] = 0
                        
                    if filtered_total_cooling_kwh > 0:
                        zone_data['cooling_percentage'] = (zone_data['cooling_kwh'] / filtered_total_cooling_kwh) * 100
                    else:
                        zone_data['cooling_percentage'] = 0
                    
                    logger.debug(f"Updated percentages for {zone_id}: heating={zone_data['heating_percentage']:.1f}%, cooling={zone_data['cooling_percentage']:.1f}%")
            
            logger.info(f"SUCCESS Successfully retrieved energy data from database:")
            logger.info(f"   - Total energy: {energy_data['heating']['total_energy_kwh'] + energy_data['cooling']['total_energy_kwh']:.1f} kWh")
            logger.info(f"   - Valid zones (from space.csv): {len(energy_data['zone_energy'])}")
            logger.info(f"   - Space names loaded: {len(energy_data['space_names'])}")
            logger.info(f"   - Simulation date: {building.simulation_timestamp}")
            logger.info(f"   - Date filtered: {'Yes' if is_date_filtered else 'No'}")
            logger.info(f"   - Space-specific: {'Yes' if is_space_specific else 'No'}")
            if is_space_specific:
                logger.info(f"   - Selected sensor: {sensor_id}")
            
            return energy_data
            
    except Exception as e:
        logger.error(f"ERROR Error retrieving energy data from database: {str(e)}", exc_info=True)
        return None


def _get_latest_simulation_results() -> Optional[dict]:
    """
    Find and load the latest simulation results from the eplus_sim/results directory.
    
    Returns:
        Dictionary containing latest simulation results or None if not found
    """
    try:
        results_base_dir = Path("./eplus_sim/results")
        logger.debug(f"Looking for simulation results in: {results_base_dir}")
        
        if not results_base_dir.exists():
            logger.info("Results directory does not exist: %s", results_base_dir)
            return None
        
        # Find all simulation directories
        sim_dirs = [d for d in results_base_dir.glob("sim_*") if d.is_dir()]
        logger.debug(f"Found {len(sim_dirs)} simulation directories: {[d.name for d in sim_dirs]}")
        
        if not sim_dirs:
            logger.info("No simulation directories found in results directory")
            return None
        
        # Sort by modification time to get the latest
        latest_sim_dir = max(sim_dirs, key=lambda x: x.stat().st_mtime)
        logger.info(f"Latest simulation directory: {latest_sim_dir.name}")
        
        # Look for EnergyPlus results
        eplus_results_path = latest_sim_dir / "export" / "EnergyPlus" / "SimResults"
        logger.debug(f"Looking for EnergyPlus results in: {eplus_results_path}")
        
        if not eplus_results_path.exists():
            logger.warning(f"EnergyPlus results path does not exist: {eplus_results_path}")
            return None
        
        # Find the actual results directory
        result_dirs = list(eplus_results_path.glob("*"))
        logger.debug(f"Found {len(result_dirs)} result directories: {[d.name for d in result_dirs]}")
        
        if not result_dirs:
            logger.warning("No result directories found in EnergyPlus SimResults")
            return None
        
        actual_results_dir = result_dirs[0]
        logger.info(f"Using results directory: {actual_results_dir}")
        
        # Create a simulation results dictionary
        simulation_results = {
            'success': True,
            'project_path': str(latest_sim_dir),
            'eplus_results_path': str(actual_results_dir),
            'timestamp': latest_sim_dir.name.split('_')[-1] if '_' in latest_sim_dir.name else 'unknown'
        }
        
        logger.info(f"Successfully loaded latest simulation results from {latest_sim_dir.name}")
        return simulation_results
        
    except Exception as e:
        logger.error(f"Error loading latest simulation results: {e}", exc_info=True)
        return None


def _display_energy_results(simulation_results: dict, sensor_id: str) -> None:
    """
    Display energy consumption results from EnergyPlus simulation.
    Only uses data from database - no CSV fallback.
    
    Args:
        simulation_results: Dictionary containing simulation results
        sensor_id: Sensor identifier for the simulation
    """
    logger.info(f"Displaying energy results for sensor: {sensor_id}")
    logger.debug(f"Simulation results keys: {list(simulation_results.keys())}")
    
    st.subheader("📊 Energy Analysis Results")
    
    try:
        # Get energy data from database only
        logger.info("Attempting to retrieve energy data from database")
        energy_data = _get_energy_data_from_database(sensor_id=sensor_id if sensor_id != "latest" else None)
        
        if energy_data:
            logger.info("SUCCESS Successfully retrieved energy data from database")
            
            # Show data source info more concisely
            building_metadata = energy_data.get('building_metadata', {})
            simulation_timestamp = building_metadata.get('simulation_timestamp')
            
            if simulation_timestamp:
                st.caption(f"📊 Simulation data from {simulation_timestamp.strftime('%Y-%m-%d %H:%M')}")
            else:
                st.caption("📊 Database data")
                
            # **Add warning about partial data issue**
            from db.session import SessionLocal
            from db.models import EnergyTimeSeries, EnergySpace, EnergyBuilding
            session = SessionLocal()
            try:
                # Get the latest building and check data completeness
                latest_building = session.query(EnergyBuilding).order_by(EnergyBuilding.simulation_timestamp.desc()).first()
                if latest_building:
                    # Get actual date range from database
                    first_ts = session.query(EnergyTimeSeries.timestamp).order_by(EnergyTimeSeries.timestamp.asc()).first()
                    last_ts = session.query(EnergyTimeSeries.timestamp).order_by(EnergyTimeSeries.timestamp.desc()).first()
                    total_records = session.query(EnergyTimeSeries).count()
                    total_spaces = session.query(EnergySpace).filter(EnergySpace.building_id == latest_building.building_id).count()
                    
                    if first_ts and last_ts and total_spaces > 0:
                        records_per_space = total_records // total_spaces
                        expected_full_year = 8760  # Hours in a year
                        
                        if records_per_space < expected_full_year:
                            # Show warning about partial data
                            days_of_data = records_per_space / 24
                            st.warning(f"⚠️ **Partial simulation data detected!** Only {records_per_space:,} hours ({days_of_data:.1f} days) of data available from {first_ts[0].strftime('%Y-%m-%d')} to {last_ts[0].strftime('%Y-%m-%d')}. Full year simulation would have {expected_full_year:,} hours.")
                            st.info("💡 The charts below show only the available data period, not a full year. To get complete data, re-run the simulation without date filtering.")
            finally:
                session.close()
            
            # Get time range from session state for filtering
            start_dt = st.session_state.get('start_dt', None)
            end_dt = st.session_state.get('end_dt', None)
            
            # Create visualizations using database data
            _create_energy_visualizations(energy_data, sensor_id, start_dt, end_dt)
        else:
            logger.info("No energy data found in database")
            st.info("📊 No energy simulation data available in database.")
            st.info("💡 Run an energy simulation to generate and store energy data.")
    except Exception as e:
        logger.error(f"Error processing energy results: {str(e)}", exc_info=True)
        st.error(f"❌ Error processing energy results: {str(e)}")


def _parse_energyplus_outputs(results_dir: Path) -> dict:
    """
    Parse EnergyPlus output files to extract energy consumption data.
    
    Args:
        results_dir: Directory containing EnergyPlus output files
        
    Returns:
        Dictionary containing parsed energy data
    """
    # Convert to Path object if it's a string
    if isinstance(results_dir, str):
        results_dir = Path(results_dir)
    
    logger.info(f"Parsing EnergyPlus outputs from directory: {results_dir}")
    energy_data = {}
    
    try:
        # First, get space names mapping from space.csv file for filtering
        # This file should be in: eplus_sim/{sim_dir}/export/space.csv
        # Current path structure: results_dir = .../SimResults/{uuid}
        # So we need to go: results_dir -> parent (SimResults) -> parent (EnergyPlus) -> parent (export) -> space.csv
        
        logger.debug(f"Current results_dir: {results_dir}")
        export_dir = results_dir.parent.parent.parent  # Go up from SimResults/{uuid} to export/
        space_csv_path = export_dir / "space.csv"
        logger.info(f"Looking for space mapping file at: {space_csv_path}")
        logger.debug(f"Export directory exists: {export_dir.exists()}")
        
        # Log directory structure for debugging
        if export_dir.exists():
            logger.debug(f"Contents of export directory: {list(export_dir.iterdir())}")
        
        if space_csv_path.exists():
            logger.info(f"SUCCESS Found space mapping file: {space_csv_path}")
            try:
                import pandas as pd
                space_df = pd.read_csv(space_csv_path)
                logger.info(f"Space CSV loaded successfully: {space_df.shape}")
                logger.debug(f"Space CSV columns: {list(space_df.columns)}")
                
                # Show first few rows for debugging
                logger.debug(f"First 3 rows of space CSV:\n{space_df.head(3).to_string()}")
                
                # Create mapping from zone ID (2nd column) to space name (3rd column)
                # Assuming columns are 0-indexed: 1st col=0, 2nd col=1, 3rd col=2
                if len(space_df.columns) >= 3:
                    zone_id_col = space_df.columns[1]  # 2nd column: ID
                    space_name_col = space_df.columns[2]  # 3rd column: long_name
                    
                    logger.info(f"Using zone ID column: '{zone_id_col}', space name column: '{space_name_col}'")
                    
                    # Filter out any rows with missing values in key columns
                    valid_rows = space_df.dropna(subset=[zone_id_col, space_name_col])
                    logger.info(f"Valid rows with both zone ID and space name: {len(valid_rows)} out of {len(space_df)}")
                    
                    if len(valid_rows) > 0:
                        # Create case-insensitive mapping by converting all zone IDs to uppercase
                        zone_ids_original = valid_rows[zone_id_col].astype(str)
                        zone_ids_upper = zone_ids_original.str.upper()
                        space_names = valid_rows[space_name_col].astype(str)
                        
                        space_mapping = dict(zip(zone_ids_upper, space_names))
                        energy_data['space_names'] = space_mapping
                        logger.info(f"SUCCESS Successfully loaded space names for {len(space_mapping)} zones")
                        logger.info(f"Zone IDs found (uppercase): {list(space_mapping.keys())}")
                        logger.info(f"Sample space mappings: {dict(list(space_mapping.items())[:3])}")
                        
                        # Log the original case for debugging
                        logger.debug(f"Original zone IDs from space.csv: {zone_ids_original.tolist()}")
                        logger.debug(f"Converted to uppercase for matching: {zone_ids_upper.tolist()}")
                    else:
                        logger.warning("ERROR No valid space mapping rows found in space.csv")
                else:
                    logger.warning(f"ERROR Space CSV file has insufficient columns: {len(space_df.columns)} (need at least 3)")
                    logger.debug(f"Available columns: {list(space_df.columns)}")
                    
            except Exception as e:
                logger.error(f"ERROR Error reading space.csv file: {e}", exc_info=True)
        else:
            logger.warning(f"ERROR No space.csv file found at expected location: {space_csv_path}")
            # Try alternative locations for debugging
            alt_paths = [
                results_dir.parent.parent / "space.csv",  # Original location
                results_dir.parent / "space.csv",         # One level up
                results_dir / "space.csv",                # Same directory
            ]
            logger.debug("Checking alternative locations:")
            for alt_path in alt_paths:
                logger.debug(f"  - {alt_path}: {'EXISTS' if alt_path.exists() else 'NOT FOUND'}")
                if alt_path.exists():
                    logger.info(f"Found space.csv at alternative location: {alt_path}")
                    # Could try to read from alternative location here if needed
        
        # Now parse EnergyPlus CSV output file (with space.csv data available for filtering)
        csv_file = results_dir / "eplusout.csv"
        logger.debug(f"Looking for CSV file: {csv_file}")
        
        if csv_file.exists():
            logger.info(f"Found EnergyPlus CSV file: {csv_file}")
            file_size = csv_file.stat().st_size
            logger.debug(f"CSV file size: {file_size} bytes")
            
            # **FIXED: Do NOT apply date filtering when storing simulation results**
            # Date filtering should only happen during visualization, not storage
            # Always parse and store the complete simulation data
            logger.info("Parsing complete simulation data (no date filtering applied)")
            
            energy_data.update(_parse_csv_file(csv_file, start_dt=None, end_dt=None))
        else:
            logger.warning(f"EnergyPlus CSV file not found: {csv_file}")
            
        # Get zone information if available
        zone_file = results_dir / "zone_dict.json"
        logger.debug(f"Looking for zone file: {zone_file}")
        
        if zone_file.exists():
            logger.info(f"Found zone dictionary file: {zone_file}")
            import json
            with open(zone_file, 'r') as f:
                zones = json.load(f)
                energy_data['zones'] = zones
                logger.debug(f"Loaded {len(zones)} zone definitions: {list(zones.keys())}")
        else:
            logger.info("No zone dictionary file found")
            
        logger.info(f"Completed parsing EnergyPlus outputs. Data sections: {list(energy_data.keys())}")
                
    except Exception as e:
        logger.error(f"Error parsing EnergyPlus outputs: {e}", exc_info=True)
        
    return energy_data


def _get_simulation_year_from_epw(results_dir: Path) -> Optional[int]:
    """
    Extract the simulation year from the EPW weather file used in the EnergyPlus simulation.
    
    Args:
        results_dir: Directory containing EnergyPlus output files
        
    Returns:
        Simulation year as integer, or None if not found
    """
    try:
        # Look for EPW files in the weather directory
        weather_dir = Path("./eplus_sim/weather")
        logger.debug(f"Looking for EPW files in: {weather_dir}")
        
        if weather_dir.exists():
            epw_files = list(weather_dir.glob("*.epw"))
            logger.debug(f"Found {len(epw_files)} EPW files: {[f.name for f in epw_files]}")
            
            if epw_files:
                # Use the most recently modified EPW file
                latest_epw = max(epw_files, key=lambda x: x.stat().st_mtime)
                logger.info(f"Using EPW file for year extraction: {latest_epw.name}")
                
                # Read the first few lines to find the data section
                with open(latest_epw, 'r') as f:
                    for line_num, line in enumerate(f):
                        if line_num > 20:  # Don't read too many lines
                            break
                        
                        # Look for data lines that start with year,month,day,hour
                        parts = line.strip().split(',')
                        if len(parts) >= 4:
                            try:
                                # Check if first part is a 4-digit year
                                year = int(parts[0])
                                if 1900 <= year <= 2100:  # Reasonable year range
                                    logger.info(f"SUCCESS Extracted simulation year from EPW: {year}")
                                    return year
                            except ValueError:
                                continue
                
                logger.warning("ERROR Could not extract year from EPW file")
        else:
            logger.warning(f"ERROR Weather directory not found: {weather_dir}")
            
    except Exception as e:
        logger.error(f"ERROR Error extracting year from EPW file: {e}", exc_info=True)
    
    return None


def _parse_csv_file(csv_file: Path, start_dt=None, end_dt=None) -> dict:
    """Parse EnergyPlus CSV output file for energy data."""
    logger.info(f"Starting to parse CSV file: {csv_file}")
    data = {}
    
    try:
        # Read the CSV file
        logger.debug("Reading CSV file with pandas")
        df = pd.read_csv(csv_file)
        logger.info(f"CSV loaded successfully: {len(df)} rows, {len(df.columns)} columns")
        
        # Filter by time range if provided
        if start_dt is not None and end_dt is not None:
            logger.warning(f"⚠️ DATE FILTERING APPLIED during CSV parsing: {start_dt} to {end_dt}")
            logger.warning("⚠️ This should ONLY happen during visualization, NOT during simulation storage!")
            # Check if there's a Date/Time column in the CSV
            time_cols = [col for col in df.columns if any(word in col.lower() for word in ['date', 'time', 'hour', 'timestamp'])]
            logger.debug(f"Found potential time columns: {time_cols}")
            
            if time_cols:
                # Try to parse the first time column found
                time_col = time_cols[0]
                try:
                    # EnergyPlus CSV files often have complex datetime formats
                    # Common formats: "01/01  01:00:00", "MM/DD  HH:MM:SS" (without year)
                    if 'Date/Time' in time_col:
                        # Handle EnergyPlus Date/Time format
                        # Get the actual simulation year from the EPW weather file
                        simulation_year = _get_simulation_year_from_epw(csv_file.parent)
                        
                        if simulation_year is None:
                            # Fallback to user's selected year if EPW extraction fails
                            simulation_year = start_dt.year
                            logger.warning(f"WARNING Could not extract year from EPW, using selected year: {simulation_year}")
                        else:
                            logger.info(f"SUCCESS Using simulation year from EPW: {simulation_year}")
                        
                        # Try to add year to EnergyPlus format
                        df_temp = df[time_col].copy()
                        
                        # Handle formats like " 01/01  01:00:00" (with leading space) by adding year
                        try:
                            # Clean and add year to EnergyPlus datetime format
                            def fix_eplus_datetime(date_str):
                                if isinstance(date_str, str) and '/' in date_str:
                                    # Remove leading/trailing whitespace and handle double spaces
                                    cleaned = date_str.strip()
                                    if '  ' in cleaned:  # Double space format
                                        date_part, time_part = cleaned.split('  ', 1)
                                        # Add year and join with single space
                                        return f"{simulation_year}/{date_part.strip()} {time_part.strip()}"
                                    elif ' ' in cleaned:  # Single space format
                                        date_part, time_part = cleaned.split(' ', 1)
                                        return f"{simulation_year}/{date_part.strip()} {time_part.strip()}"
                                return date_str
                            
                            # Apply the cleaning and year addition
                            df_cleaned = df_temp.apply(fix_eplus_datetime)
                            logger.debug(f"Sample cleaned datetime strings: {df_cleaned.head(3).tolist()}")
                            
                            # Try parsing with the expected format
                            df[time_col] = pd.to_datetime(df_cleaned, format='%Y/%m/%d %H:%M:%S', errors='coerce')
                            
                            # Check if parsing worked
                            if not df[time_col].isna().all():
                                parsed_count = df[time_col].notna().sum()
                                logger.info(f"SUCCESS Successfully parsed {parsed_count}/{len(df)} EnergyPlus dates with year {simulation_year}")
                            else:
                                # Fallback to pandas auto-detection
                                df[time_col] = pd.to_datetime(df_cleaned, errors='coerce')
                                parsed_count = df[time_col].notna().sum()
                                if parsed_count > 0:
                                    logger.info(f"SUCCESS Parsed {parsed_count}/{len(df)} dates using pandas auto-detection")
                                else:
                                    logger.warning("ERROR All EnergyPlus date parsing attempts failed, using fallback parsing")
                                    df[time_col] = pd.to_datetime(df_temp, errors='coerce')
                        except Exception as e:
                            # Fallback to standard parsing
                            df[time_col] = pd.to_datetime(df_temp, errors='coerce')
                            logger.warning(f"EnergyPlus date parsing failed: {e}, using fallback parsing")
                    else:
                        df[time_col] = pd.to_datetime(df[time_col], errors='coerce')
                    
                    # Only filter if we successfully parsed datetime
                    if not df[time_col].isna().all():
                        # Convert start_dt and end_dt to timezone-naive for comparison with EnergyPlus data
                        start_compare = start_dt.replace(tzinfo=None) if hasattr(start_dt, 'tzinfo') else start_dt
                        end_compare = end_dt.replace(tzinfo=None) if hasattr(end_dt, 'tzinfo') else end_dt
                        
                        # Log date ranges for debugging
                        logger.info(f"Filtering data: requested range {start_compare} to {end_compare}")
                        if len(df) > 0:
                            logger.info(f"CSV date range: {df[time_col].min()} to {df[time_col].max()}")
                        
                        # Filter data by time range
                        mask = (df[time_col] >= start_compare) & (df[time_col] <= end_compare)
                        df_filtered = df[mask].copy()
                        logger.info(f"Time filtering applied: {len(df)} -> {len(df_filtered)} rows (range: {start_compare} to {end_compare})")
                        
                        if len(df_filtered) > 0:
                            df = df_filtered
                            logger.info(f"SUCCESS Successfully filtered to {len(df)} rows for the requested time period")
                        else:
                            logger.warning("ERROR Time filtering resulted in empty dataset. Using all data.")
                            logger.warning(f"Check if simulation year {simulation_year} matches requested dates {start_compare.year}")
                    else:
                        logger.warning(f"Could not parse any dates in column '{time_col}'. Using all data.")
                        
                except Exception as e:
                    logger.warning(f"Could not parse time column '{time_col}': {e}. Using all data.")
            else:
                logger.info("No recognizable time columns found in CSV. EnergyPlus simulations should have Date/Time data.")
        else:
            logger.info("✅ No date filtering applied - parsing complete simulation data")
            logger.debug("This is correct behavior when storing simulation results")
        
        # Find heating and cooling energy columns
        heating_cols = [col for col in df.columns if 'Heating Energy [J]' in col]
        cooling_cols = [col for col in df.columns if 'Cooling Energy [J]' in col]
        
        logger.info(f"Found {len(heating_cols)} heating energy columns")
        logger.info(f"Found {len(cooling_cols)} cooling energy columns")
        logger.debug(f"Heating columns: {heating_cols[:3]}{'...' if len(heating_cols) > 3 else ''}")
        logger.debug(f"Cooling columns: {cooling_cols[:3]}{'...' if len(cooling_cols) > 3 else ''}")
        
        # Process heating data
        if heating_cols:
            logger.debug("Processing heating data")
            logger.info(f"HEATING Processing heating data from {len(df)} filtered rows")
            heating_data = []
            for col in heating_cols:
                col_data = df[col].fillna(0).tolist()
                heating_data.extend(col_data)
                logger.debug(f"Added {len(col_data)} values from column: {col}")
            
            # Remove zeros and calculate statistics
            heating_nonzero = [x for x in heating_data if x > 0]
            logger.info(f"Heating data: {len(heating_data)} total values, {len(heating_nonzero)} non-zero values")
            
            if heating_nonzero:
                total_j = sum(heating_nonzero)
                total_kwh = total_j / 3600000
                peak_w = max(heating_nonzero)
                
                # Log detailed calculation info
                logger.info(f"DATA Heating calculation from {len(df)} filtered rows: {total_kwh:.1f} kWh total, {peak_w:.0f} W peak")
                
                data['heating'] = {
                    'total_energy_j': total_j,
                    'total_energy_kwh': total_kwh,
                    'peak_rate_w': peak_w,
                    'hourly_data': heating_nonzero[:8760],  # Limit to one year
                    'zones_detected': len(heating_cols)
                }
                logger.info(f"Heating summary: {total_kwh:.1f} kWh total, {peak_w:.0f} W peak, {len(heating_cols)} zones")
        
        # Process cooling data  
        if cooling_cols:
            logger.debug("Processing cooling data")
            logger.info(f"COOLING Processing cooling data from {len(df)} filtered rows")
            cooling_data = []
            for col in cooling_cols:
                col_data = df[col].fillna(0).tolist()
                cooling_data.extend(col_data)
                logger.debug(f"Added {len(col_data)} values from column: {col}")
            
            # Remove zeros and calculate statistics
            cooling_nonzero = [x for x in cooling_data if x > 0]
            logger.info(f"Cooling data: {len(cooling_data)} total values, {len(cooling_nonzero)} non-zero values")
            
            if cooling_nonzero:
                total_j = sum(cooling_nonzero)
                total_kwh = total_j / 3600000
                peak_w = max(cooling_nonzero)
                
                # Log detailed calculation info
                logger.info(f"DATA Cooling calculation from {len(df)} filtered rows: {total_kwh:.1f} kWh total, {peak_w:.0f} W peak")
                
                data['cooling'] = {
                    'total_energy_j': total_j,
                    'total_energy_kwh': total_kwh,
                    'peak_rate_w': peak_w,
                    'hourly_data': cooling_nonzero[:8760],  # Limit to one year
                    'zones_detected': len(cooling_cols)
                }
                logger.info(f"Cooling summary: {total_kwh:.1f} kWh total, {peak_w:.0f} W peak, {len(cooling_cols)} zones")
                
        # Extract zone-specific data (filter by space.csv)
        logger.info("SEARCH Extracting zone-specific energy data from CSV columns")
        
        # Load space names from space.csv for filtering
        # Determine the space.csv path from the CSV file location
        csv_dir = csv_file.parent  # This should be SimResults/{uuid}/
        export_dir = csv_dir.parent.parent.parent  # Go up to export/
        space_names_from_csv = {}
        
        space_csv_path = export_dir / "space.csv"
        logger.debug(f"Looking for space.csv at: {space_csv_path}")
        
        if space_csv_path.exists():
            try:
                logger.info(f"Loading space names from: {space_csv_path}")
                space_df = pd.read_csv(space_csv_path)
                
                if len(space_df.columns) >= 3:
                    # Use 2nd column as zone ID and 3rd column as space name
                    zone_id_col = space_df.columns[1]  # 2nd column: ID
                    space_name_col = space_df.columns[2]  # 3rd column: long_name
                    
                    # Filter out rows with missing values
                    valid_rows = space_df.dropna(subset=[zone_id_col, space_name_col])
                    
                    if len(valid_rows) > 0:
                        # Create case-insensitive mapping by converting zone IDs to uppercase
                        zone_ids_upper = valid_rows[zone_id_col].astype(str).str.upper()
                        space_names = valid_rows[space_name_col].astype(str)
                        
                        space_names_from_csv = dict(zip(zone_ids_upper, space_names))
                        logger.info(f"SUCCESS Loaded {len(space_names_from_csv)} space names from space.csv")
                        logger.debug(f"Space IDs from CSV: {list(space_names_from_csv.keys())}")
                    else:
                        logger.warning("ERROR No valid space mapping rows found in space.csv")
                else:
                    logger.warning(f"ERROR Space CSV file has insufficient columns: {len(space_df.columns)} (need at least 3)")
                    
            except Exception as e:
                logger.error(f"ERROR Error reading space.csv file: {e}", exc_info=True)
        else:
            logger.warning(f"ERROR No space.csv file found at expected location: {space_csv_path}")
            
        logger.info(f"Filtering zones using {len(space_names_from_csv)} space names from space.csv")
        
        # Log all available column names for debugging
        logger.debug(f"All CSV columns ({len(df.columns)}): {list(df.columns)}")
        
        # Log space names for debugging
        if space_names_from_csv:
            logger.debug(f"Space names from CSV: {list(space_names_from_csv.keys())}")
        else:
            logger.warning("ERROR No space names loaded from space.csv - this will prevent zone filtering")
        
        zone_data = {}
        
        # First, log all columns that contain zone information
        zone_columns = [col for col in df.columns if ':Zone' in col and ('Heating Energy' in col or 'Cooling Energy' in col)]
        logger.info(f"Found {len(zone_columns)} zone energy columns in CSV")
        
        if zone_columns:
            logger.debug(f"Zone energy columns: {zone_columns[:10]}{'...' if len(zone_columns) > 10 else ''}")
            
            # Log unique zone prefixes found in column names
            zone_prefixes = set()
            for col in zone_columns:
                zone_prefix = col.split(':')[0]
                zone_prefixes.add(zone_prefix)
            logger.info(f"Unique zone prefixes in CSV columns: {sorted(list(zone_prefixes))}")
        else:
            logger.warning("ERROR No zone energy columns found in CSV - checking alternative patterns")
            
            # Check for alternative column patterns
            heating_pattern_cols = [col for col in df.columns if 'Heating' in col and 'Energy' in col]
            cooling_pattern_cols = [col for col in df.columns if 'Cooling' in col and 'Energy' in col]
            logger.info(f"Alternative heating columns found: {len(heating_pattern_cols)}")
            logger.info(f"Alternative cooling columns found: {len(cooling_pattern_cols)}")
            
            if heating_pattern_cols or cooling_pattern_cols:
                logger.debug(f"Sample heating columns: {heating_pattern_cols[:5]}")
                logger.debug(f"Sample cooling columns: {cooling_pattern_cols[:5]}")
        
        for col in zone_columns:
            # Extract zone identifier (everything before the first colon)
            zone_full_prefix = col.split(':')[0]
            
            # Extract just the zone ID by removing system names like "IDEAL LOADS AIR SYSTEM"
            # Zone ID is typically the first part before any space-separated system identifiers
            zone_parts = zone_full_prefix.split()
            if len(zone_parts) > 1 and 'IDEAL LOADS AIR SYSTEM' in zone_full_prefix:
                # For "0LT8GR_E9ESEGH5UY_G9E9 IDEAL LOADS AIR SYSTEM", take only the first part
                zone_id = zone_parts[0]
            else:
                # For other formats, use the full prefix
                zone_id = zone_full_prefix
            
            zone_id_upper = zone_id.upper()
            
            logger.debug(f"Processing column: '{col}' -> Full prefix: '{zone_full_prefix}' -> Zone ID: '{zone_id}' -> Uppercase: '{zone_id_upper}'")
            
            # Check if this zone is in space.csv
            if zone_id_upper not in space_names_from_csv:
                logger.debug(f"ERROR Skipping zone not found in space.csv: '{zone_id}' (uppercase: '{zone_id_upper}')")
                logger.debug(f"   Available space names: {list(space_names_from_csv.keys())}")
                continue
                
            logger.info(f"SUCCESS Processing column: '{col}' -> Zone ID: '{zone_id}' (found in space.csv)")
            
            if zone_id not in zone_data:
                zone_data[zone_id] = {}
                space_name = space_names_from_csv[zone_id_upper]
                logger.info(f" Initialized zone data for: '{zone_id}' -> '{space_name}'")
            
            if 'Heating Energy' in col:
                zone_heating_j = df[col].fillna(0)
                zone_heating_kwh = zone_heating_j.sum() / 3600000
                zone_data[zone_id]['heating_kwh'] = zone_heating_kwh
                # Store time series data for this zone (convert J to kWh, assuming hourly data)
                zone_data[zone_id]['heating_timeseries'] = zone_heating_j.tolist()
                logger.info(f"   HEATING Zone '{zone_id}' heating: {zone_heating_kwh:.2f} kWh, {len(zone_heating_j)} time points")
                logger.debug(f"      Sample heating values: {zone_heating_j.head().tolist()}")
                
            elif 'Cooling Energy' in col:
                zone_cooling_j = df[col].fillna(0)
                zone_cooling_kwh = zone_cooling_j.sum() / 3600000
                zone_data[zone_id]['cooling_kwh'] = zone_cooling_kwh
                # Store time series data for this zone (convert J to kWh, assuming hourly data)
                zone_data[zone_id]['cooling_timeseries'] = zone_cooling_j.tolist()
                logger.info(f"   COOLING Zone '{zone_id}' cooling: {zone_cooling_kwh:.2f} kWh, {len(zone_cooling_j)} time points")
                logger.debug(f"      Sample cooling values: {zone_cooling_j.head().tolist()}")
        
        if zone_data:
            data['zone_energy'] = zone_data
            logger.info(f"SUCCESS Successfully extracted zone energy data for {len(zone_data)} zones (filtered by space.csv)")
            logger.info(f"   Valid zone IDs: {list(zone_data.keys())}")
            
            # Log summary of zone data
            for zone_id, zone_info in zone_data.items():
                heating_kwh = zone_info.get('heating_kwh', 0)
                cooling_kwh = zone_info.get('cooling_kwh', 0)
                heating_points = len(zone_info.get('heating_timeseries', []))
                cooling_points = len(zone_info.get('cooling_timeseries', []))
                logger.info(f"   Zone '{zone_id}': H={heating_kwh:.2f}kWh({heating_points}pts), C={cooling_kwh:.2f}kWh({cooling_points}pts)")
        else:
            logger.error("ERROR No zone-specific energy data found in CSV (after space.csv filtering)")
            logger.error("   This means EnergySpace and EnergyTimeSeries records will NOT be created")
            
            # Debug information to help identify the issue
            if not space_names_from_csv:
                logger.error("   Root cause: No space.csv data loaded")
            elif not zone_columns:
                logger.error("   Root cause: No zone energy columns found in CSV")
            else:
                logger.error("   Root cause: Zone ID mismatch between CSV columns and space.csv")
                logger.error(f"   Zone prefixes from CSV: {sorted(set(col.split(':')[0].upper() for col in zone_columns))}")
                logger.error(f"   Space IDs from space.csv: {sorted(list(space_names_from_csv.keys()))}")
            
        logger.info(f"CSV parsing completed successfully. Data sections: {list(data.keys())}")
            
    except Exception as e:
        logger.error(f"Error parsing CSV file: {e}", exc_info=True)
        
    return data


def _create_energy_visualizations(energy_data: dict, sensor_id: str, start_dt=None, end_dt=None) -> None:
    """
    Create visualizations for energy consumption data.
    
    Args:
        energy_data: Parsed energy data from EnergyPlus
        sensor_id: Sensor identifier
        start_dt: Start datetime for filtering (optional)
        end_dt: End datetime for filtering (optional)
    """
    logger.info(f"Creating energy visualizations for sensor: {sensor_id}")
    if start_dt and end_dt:
        logger.info(f"Time range filtering: {start_dt} to {end_dt}")
    logger.debug(f"Energy data sections available: {list(energy_data.keys())}")
    
    # Check if this is space-specific view
    building_metadata = energy_data.get('building_metadata', {})
    is_space_specific = building_metadata.get('is_space_specific', False)
    selected_sensor_id = building_metadata.get('selected_sensor_id')
    
    # Get space name for space-specific view
    space_name = None
    if is_space_specific and sensor_id and sensor_id != "latest":
        # Find the space name for the selected sensor
        zone_energy = energy_data.get('zone_energy', {})
        space_names = energy_data.get('space_names', {})
        
        for zone_id, zone_data in zone_energy.items():
            if zone_data.get('sensor_id') == sensor_id:
                zone_id_upper = zone_id.upper()
                space_name = space_names.get(zone_id_upper, zone_id)
                break
    
    # Create columns for layout
    col1, col2 = st.columns(2)
    
    # Show context info more concisely
    if is_space_specific and space_name:
        st.caption(f" Showing '{space_name}' energy data")
    elif is_space_specific:
        st.caption(f" Showing space-specific energy data")
    else:
        st.caption(f"🏢 Showing building-wide energy data")
    
    # Show time range info more concisely if filtering is applied
    if start_dt and end_dt:
        st.caption(f"📅 Period: {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}")
    
    # Check for date filter warning
    if 'date_filter_warning' in energy_data:
        warning_info = energy_data['date_filter_warning'] 
        st.warning(
            f"⚠️ **No data found in selected date range** ({warning_info['filtered_start'].strftime('%Y-%m-%d')} to {warning_info['filtered_end'].strftime('%Y-%m-%d')})\n\n"
            f"📊 **Available energy data covers:** {warning_info['min_date'].strftime('%Y-%m-%d')} to {warning_info['max_date'].strftime('%Y-%m-%d')}\n\n"
            f"💡 **Tip:** Adjust the date range in the sidebar to match the available data period."
        )
    
    # Heating Energy Analysis
    with col1:
        heating_title = "HEATING Heating Energy"
        if is_space_specific and space_name:
            heating_title += f" - {space_name}"
        elif is_space_specific:
            heating_title += f" - Sensor {sensor_id}"
        st.markdown(f"### {heating_title}")
        
        if 'heating' in energy_data:
            heating = energy_data['heating']
            logger.info(f"Displaying heating data: {heating['total_energy_kwh']:.1f} kWh total, {heating['zones_detected']} zones")
            
            # Display key metrics
            context_text = "for this space" if is_space_specific else "for all spaces"
            if start_dt and end_dt:
                period_text = f"{context_text} in selected time period ({start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')})"
            else:
                period_text = f"{context_text} from simulation"
            
            st.metric(
                label="Total Heating Energy",
                value=f"{heating['total_energy_kwh']:,.1f} kWh",
                help=f"Total heating energy consumption {period_text}"
            )
            
            st.metric(
                label="Peak Heating Rate", 
                value=f"{heating['peak_rate_w']:,.0f} W",
                help=f"Maximum instantaneous heating power {period_text}"
            )
            
            # Create hourly heating chart if data available
            if heating.get('hourly_data'):
                hourly_heating = heating['hourly_data'][:8760]  # One year of data
                logger.debug(f"Creating heating chart with {len(hourly_heating)} hourly data points")
                
                # Create datetime range for the chart using REAL database timestamps
                if energy_data.get('timestamps'):
                    # Use the REAL timestamps from the database that we already retrieved
                    real_timestamps = energy_data['timestamps']
                    logger.info(f"📅 Using REAL database timestamps: {len(real_timestamps)} timestamps from {real_timestamps[0] if real_timestamps else 'N/A'} to {real_timestamps[-1] if real_timestamps else 'N/A'}")
                    
                    # Sample data to daily averages for visualization
                    if len(hourly_heating) >= 24:
                        # Calculate daily averages from hourly data
                        daily_avg = [np.mean(hourly_heating[i:i+24]) for i in range(0, len(hourly_heating), 24)]
                        # Sample timestamps to daily (every 24th timestamp)
                        date_range = [real_timestamps[i] for i in range(0, len(real_timestamps), 24)][:len(daily_avg)]
                    else:
                        # Use hourly data as-is for shorter periods
                        daily_avg = hourly_heating
                        date_range = real_timestamps[:len(daily_avg)]
                else:
                    # Fallback if no timestamps available (should not happen)
                    logger.error("❌ NO REAL TIMESTAMPS AVAILABLE - This should never happen!")
                    st.error("No timestamp data available for visualization")
                    daily_avg = []
                    date_range = []
                
                logger.debug(f"Created {len(daily_avg)} daily averages for heating chart with date range {date_range[0]} to {date_range[-1]}")
                
                # Create DataFrame for plotting with proper datetime
                heating_df = pd.DataFrame({
                    'Timestamp': date_range,
                    'Heating_Power_W': [float(x) for x in daily_avg]  # Ensure values are float
                })
                
                # Create Altair chart with datetime x-axis
                chart_title = f"Daily Average Heating Power"
                if is_space_specific and space_name:
                    chart_title += f" - {space_name}"
                elif is_space_specific:
                    chart_title += f" - Sensor {sensor_id}"
                if start_dt and end_dt:
                    chart_title += " (Filtered Period)"
                heating_chart = alt.Chart(heating_df).mark_line(
                    point=True, color='red', strokeWidth=2
                ).add_params(
                    alt.selection_interval(bind='scales')
                ).encode(
                    x=alt.X('Timestamp:T', title='Date', axis=alt.Axis(format='%d %b %Y', labelAngle=-45)),
                    y=alt.Y('Heating_Power_W:Q', title='Heating Power (W)'),
                    tooltip=[
                        alt.Tooltip('Timestamp:T', title='Date', format='%d %b %Y'),
                        alt.Tooltip('Heating_Power_W:Q', title='Heating Power (W)', format='.1f')
                    ]
                ).properties(
                    width=400,
                    height=300,
                    title=chart_title
                )
                
                st.altair_chart(heating_chart, use_container_width=True)
                logger.debug("Heating chart displayed successfully")
        else:
            logger.info("No heating data found in energy results")
            st.info("ℹ️ No heating data found in simulation results")
    
    # Cooling Energy Analysis  
    with col2:
        cooling_title = "COOLING Cooling Energy"
        if is_space_specific and space_name:
            cooling_title += f" - {space_name}"
        elif is_space_specific:
            cooling_title += f" - Sensor {sensor_id}"
        st.markdown(f"### {cooling_title}")
        
        if 'cooling' in energy_data:
            cooling = energy_data['cooling']
            logger.info(f"Displaying cooling data: {cooling['total_energy_kwh']:.1f} kWh total, {cooling['zones_detected']} zones")
            
            # Display key metrics
            context_text = "for this space" if is_space_specific else "for all spaces"
            if start_dt and end_dt:
                period_text = f"{context_text} in selected time period ({start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')})"
            else:
                period_text = f"{context_text} from simulation"
            
            st.metric(
                label="Total Cooling Energy",
                value=f"{cooling['total_energy_kwh']:,.1f} kWh", 
                help=f"Total cooling energy consumption {period_text}"
            )
            
            st.metric(
                label="Peak Cooling Rate",
                value=f"{cooling['peak_rate_w']:,.0f} W",
                help=f"Maximum instantaneous cooling power {period_text}"
            )
            
            # Create hourly cooling chart if data available
            if cooling.get('hourly_data'):
                hourly_cooling = cooling['hourly_data'][:8760]  # One year of data
                logger.debug(f"Creating cooling chart with {len(hourly_cooling)} hourly data points")
                
                # Create datetime range for the chart using REAL database timestamps
                if energy_data.get('timestamps'):
                    # Use the REAL timestamps from the database that we already retrieved
                    real_timestamps = energy_data['timestamps']
                    logger.info(f"📅 Using REAL database timestamps for cooling: {len(real_timestamps)} timestamps from {real_timestamps[0] if real_timestamps else 'N/A'} to {real_timestamps[-1] if real_timestamps else 'N/A'}")
                    
                    # Sample data to daily averages for visualization
                    if len(hourly_cooling) >= 24:
                        # Calculate daily averages from hourly data
                        daily_avg = [np.mean(hourly_cooling[i:i+24]) for i in range(0, len(hourly_cooling), 24)]
                        # Sample timestamps to daily (every 24th timestamp)
                        date_range = [real_timestamps[i] for i in range(0, len(real_timestamps), 24)][:len(daily_avg)]
                    else:
                        # Use hourly data as-is for shorter periods
                        daily_avg = hourly_cooling
                        date_range = real_timestamps[:len(daily_avg)]
                else:
                    # Fallback if no timestamps available (should not happen)
                    logger.error("❌ NO REAL TIMESTAMPS AVAILABLE FOR COOLING - This should never happen!")
                    st.error("No timestamp data available for cooling visualization")
                    daily_avg = []
                    date_range = []
                
                logger.debug(f"Created {len(daily_avg)} daily averages for cooling chart with date range {date_range[0]} to {date_range[-1]}")
                
                # Create DataFrame for plotting with proper datetime
                cooling_df = pd.DataFrame({
                    'Timestamp': date_range,
                    'Cooling_Power_W': [float(x) for x in daily_avg]  # Ensure values are float
                })
                
                # Create Altair chart with datetime x-axis
                chart_title = f"Daily Average Cooling Power"
                if is_space_specific and space_name:
                    chart_title += f" - {space_name}"
                elif is_space_specific:
                    chart_title += f" - Sensor {sensor_id}"
                if start_dt and end_dt:
                    chart_title += " (Filtered Period)"
                cooling_chart = alt.Chart(cooling_df).mark_line(
                    point=True, color='blue', strokeWidth=2
                ).add_params(
                    alt.selection_interval(bind='scales')
                ).encode(
                    x=alt.X('Timestamp:T', title='Date', axis=alt.Axis(format='%d %b %Y', labelAngle=-45)),
                    y=alt.Y('Cooling_Power_W:Q', title='Cooling Power (W)'),
                    tooltip=[
                        alt.Tooltip('Timestamp:T', title='Date', format='%d %b %Y'),
                        alt.Tooltip('Cooling_Power_W:Q', title='Cooling Power (W)', format='.1f')
                    ]
                ).properties(
                    width=400,
                    height=300,
                    title=chart_title
                )
                
                st.altair_chart(cooling_chart, use_container_width=True)
                logger.debug("Cooling chart displayed successfully")
        else:
            logger.info("No cooling data found in energy results")
            st.info("ℹ️ No cooling data found in simulation results")
    
    # Combined Energy Summary
    st.markdown("### 📈 Energy Summary")
    
    # Create summary metrics
    col1, col2, col3 = st.columns(3)
    
    total_heating = energy_data.get('heating', {}).get('total_energy_kwh', 0)
    total_cooling = energy_data.get('cooling', {}).get('total_energy_kwh', 0)
    total_energy = total_heating + total_cooling
    
    with col1:
        st.metric("⚡ Total Energy", f"{total_energy:,.1f} kWh")
    with col2:
        st.metric("🔥 Heating Share", f"{(total_heating/total_energy*100):.1f}%" if total_energy > 0 else "0%")
    with col3:
        st.metric("❄️ Cooling Share", f"{(total_cooling/total_energy*100):.1f}%" if total_energy > 0 else "0%")
    
    # Zone Energy Contribution Pie Chart (only show for building-wide view)
    if 'zone_energy' in energy_data and energy_data['zone_energy'] and not is_space_specific:
        st.markdown("### 🏠 Space Energy Contribution")
        
        # Prepare data for pie chart
        zone_energy = energy_data['zone_energy']
        space_names = energy_data.get('space_names', {})
        
        pie_data = []
        for zone_id, zone_data in zone_energy.items():
            heating = zone_data.get('heating_kwh', 0)
            cooling = zone_data.get('cooling_kwh', 0)
            total_zone = heating + cooling
            
            if total_zone > 0:
                # Get space name with fallback
                zone_id_upper = zone_id.upper()
                if zone_id_upper in space_names:
                    zone_name = space_names[zone_id_upper]
                    logger.debug(f"Pie chart: Zone {zone_id} -> Space '{zone_name}' ({total_zone:.1f} kWh)")
                else:
                    zone_name = zone_id
                    logger.debug(f"Pie chart: Zone {zone_id} (no space name) -> {total_zone:.1f} kWh")
                
                pie_data.append({
                    'Space': zone_name,
                    'Energy_kWh': total_zone,
                    'Heating_kWh': heating,
                    'Cooling_kWh': cooling,
                    'Percentage': (total_zone / total_energy * 100) if total_energy > 0 else 0
                })
        
        if pie_data:
            pie_df = pd.DataFrame(pie_data)
            logger.info(f"Creating pie chart with {len(pie_df)} spaces, total: {pie_df['Energy_kWh'].sum():.1f} kWh")
            
            # Create two columns for pie chart and data table
            pie_col1, pie_col2 = st.columns([2, 1])
            
            with pie_col1:
                # Create pie chart using Altair
                pie_chart = alt.Chart(pie_df).mark_arc(
                    innerRadius=50,
                    outerRadius=120,
                    stroke='white',
                    strokeWidth=2
                ).encode(
                    theta=alt.Theta('Energy_kWh:Q', scale=alt.Scale(type='linear')),
                    color=alt.Color('Space:N', 
                                    scale=alt.Scale(scheme='category20'),
                                    legend=alt.Legend(title="Spaces", orient="right", labelLimit=150)),
                    tooltip=[
                        alt.Tooltip('Space:N', title='Space Name'),
                        alt.Tooltip('Energy_kWh:Q', title='Total Energy (kWh)', format='.1f'),
                        alt.Tooltip('Heating_kWh:Q', title='Heating (kWh)', format='.1f'),
                        alt.Tooltip('Cooling_kWh:Q', title='Cooling (kWh)', format='.1f'),
                        alt.Tooltip('Percentage:Q', title='Share (%)', format='.1f')
                    ]
                ).properties(
                    width=350,
                    height=350,
                    title=f"Energy Consumption by Space{' (Filtered Period)' if start_dt and end_dt else ''}"
                )
                
                st.altair_chart(pie_chart, use_container_width=True)
            
            with pie_col2:
                st.markdown("**📊 Space Breakdown:**")
                # Sort by energy consumption for better display
                pie_df_sorted = pie_df.sort_values('Energy_kWh', ascending=False)
                for _, row in pie_df_sorted.head(10).iterrows():  # Show top 10 spaces
                    st.metric(
                        label=row['Space'][:30] + "..." if len(row['Space']) > 30 else row['Space'],
                        value=f"{row['Energy_kWh']:,.1f} kWh",
                        delta=f"{row['Percentage']:.1f}% of total"
                    )
                
                if len(pie_df_sorted) > 10:
                    remaining = len(pie_df_sorted) - 10
                    remaining_energy = pie_df_sorted.tail(remaining)['Energy_kWh'].sum()
                    st.metric(
                        label=f"+ {remaining} other spaces",
                        value=f"{remaining_energy:,.1f} kWh",
                        delta=f"{remaining_energy/total_energy*100:.1f}% of total"
                    )
        else:
            st.info("ℹ️ No zone energy data available for pie chart")
    
    # Zone-level data if available
    if 'zone_energy' in energy_data:
        if is_space_specific:
            st.markdown("###  Selected Space Details")
        else:
            st.markdown("###  Thermal Zone Energy Breakdown")
        
        zone_energy = energy_data['zone_energy']
        zone_info = energy_data.get('zones', {})
        space_names = energy_data.get('space_names', {})
        
        logger.info(f"Displaying zone energy breakdown for {len(zone_energy)} zones")
        logger.debug(f"Available zone_energy keys: {list(zone_energy.keys())}")
        logger.debug(f"Available zone_info keys: {list(zone_info.keys()) if zone_info else 'None'}")
        logger.debug(f"Available space_names keys: {list(space_names.keys()) if space_names else 'None'}")
        
        # For space-specific view, show more details in a single column
        # For building-wide view, use multiple columns as before
        if is_space_specific and len(zone_energy) == 1:
            # Single space detailed view
            zone_id, zone_data = next(iter(zone_energy.items()))
            
            # Get space name
            zone_id_upper = zone_id.upper()
            if zone_id_upper in space_names:
                zone_name = space_names[zone_id_upper]
                logger.info(f"SUCCESS Using space name for zone {zone_id} (matched as {zone_id_upper}): '{zone_name}'")
            elif zone_id in zone_info:
                zone_name = zone_info[zone_id]
                logger.info(f"WARNING Using zone_dict name for zone {zone_id}: '{zone_name}'")
            else:
                zone_name = zone_id
                logger.warning(f"ERROR No mapping found for zone {zone_id} (tried {zone_id_upper}), using zone ID as display name")
            
            st.markdown(f"** Space: {zone_name}**")
            
            # Create metrics in columns
            col1, col2, col3 = st.columns(3)
            
            heating = zone_data.get('heating_kwh', 0)
            cooling = zone_data.get('cooling_kwh', 0)
            total_zone = heating + cooling
            
            with col1:
                if heating > 0:
                    st.metric("🔥 Heating Energy", f"{heating:,.1f} kWh")
                else:
                    st.metric("🔥 Heating Energy", "0 kWh")
            
            with col2:
                if cooling > 0:
                    st.metric("❄️ Cooling Energy", f"{cooling:,.1f} kWh")
                else:
                    st.metric("❄️ Cooling Energy", "0 kWh")
            
            with col3:
                st.metric("⚡ Total Energy", f"{total_zone:,.1f} kWh")
            
            # Additional space details if available
            floor_area = zone_data.get('floor_area_m2')
            volume = zone_data.get('volume_m3')
            zone_type = zone_data.get('zone_type')
            
            if floor_area or volume or zone_type:
                st.markdown("**📐 Space Characteristics:**")
                details_col1, details_col2, details_col3 = st.columns(3)
                
                with details_col1:
                    if floor_area:
                        st.metric("Floor Area", f"{floor_area:,.1f} m²")
                
                with details_col2:
                    if volume:
                        st.metric("Volume", f"{volume:,.1f} m³")
                
                with details_col3:
                    if zone_type:
                        st.metric("Zone Type", zone_type)
            
            # Energy intensity metrics if available
            heating_intensity = zone_data.get('heating_intensity_kwh_m2')
            cooling_intensity = zone_data.get('cooling_intensity_kwh_m2')
            
            if heating_intensity is not None or cooling_intensity is not None:
                st.markdown("**⚡ Energy Intensity:**")
                intensity_col1, intensity_col2 = st.columns(2)
                
                with intensity_col1:
                    if heating_intensity is not None:
                        st.metric("Heating Intensity", f"{heating_intensity:.2f} kWh/m²")
                
                with intensity_col2:
                    if cooling_intensity is not None:
                        st.metric("Cooling Intensity", f"{cooling_intensity:.2f} kWh/m²")
        else:
            # Multiple zones view (building-wide or multiple spaces for one sensor)
            # Create columns for zone data
            if len(zone_energy) <= 3:
                cols = st.columns(len(zone_energy))
            else:
                cols = st.columns(3)
                
            for i, (zone_id, zone_data) in enumerate(zone_energy.items()):
                col_idx = i % len(cols)
                
                with cols[col_idx]:
                    # Get space name from space.csv mapping, fallback to zone_dict, then zone_id
                    logger.debug(f"Processing zone: {zone_id}")
                    
                    # Try case-insensitive lookup for space names
                    zone_id_upper = zone_id.upper()
                    if zone_id_upper in space_names:
                        zone_name = space_names[zone_id_upper]
                        logger.info(f"SUCCESS Using space name for zone {zone_id} (matched as {zone_id_upper}): '{zone_name}'")
                    elif zone_id in zone_info:
                        zone_name = zone_info[zone_id]
                        logger.info(f"WARNING Using zone_dict name for zone {zone_id}: '{zone_name}'")
                    else:
                        zone_name = zone_id
                        logger.warning(f"ERROR No mapping found for zone {zone_id} (tried {zone_id_upper}), using zone ID as display name")
                    
                    st.markdown(f"** {zone_name}**")
                    
                    heating = zone_data.get('heating_kwh', 0)
                    cooling = zone_data.get('cooling_kwh', 0)
                    
                    if heating > 0:
                        st.metric("Heating", f"{heating:,.1f} kWh")
                    if cooling > 0:
                        st.metric("Cooling", f"{cooling:,.1f} kWh")
                    
                    total_zone = heating + cooling
                    if total_zone > 0:
                        st.metric("Total", f"{total_zone:,.1f} kWh")
    
    elif 'zones' in energy_data or 'space_names' in energy_data:
        with st.expander(" Thermal Zone Details"):
            zones = energy_data.get('zones', {})
            space_names = energy_data.get('space_names', {})
            zone_energy = energy_data.get('zone_energy', {})
            
            if space_names:
                st.markdown("**🗺️ Space Names Mapping:**")
                for zone_id, space_name in space_names.items():
                    # Check if this zone ID exists in the energy data (case-insensitive)
                    energy_matches = [z for z in zone_energy.keys() if z.upper() == zone_id]
                    energy_status = f"SUCCESS Matches: {energy_matches}" if energy_matches else "ERROR No energy data"
                    st.text(f" {zone_id}: {space_name} ({energy_status})")
                st.markdown("---")
            else:
                st.warning("⚠️ No space names mapping found - displaying zone UIDs")
                
            # Show zone energy IDs for debugging
            if zone_energy:
                st.markdown("**🔧 Debug Info - Zone IDs from Energy Data:**")
                for zone_id in zone_energy.keys():
                    zone_id_upper = zone_id.upper()
                    mapping_status = "SUCCESS Mapped" if zone_id_upper in space_names else "ERROR Not mapped"
                    st.text(f"Zone ID: '{zone_id}' -> '{zone_id_upper}' ({mapping_status})")
                st.markdown("---")
            
            if zones:
                st.markdown("**🔧 Zone Technical Details:**")
                st.json(zones)


def _find_existing_epw_file(sensor_id: str, start_date: date, end_date: date) -> Optional[Path]:
    """
    Check if an EPW file already exists for the given sensor and date range.
    Prioritizes full-year EPW files over partial period files.
    
    Parameters
    ----------
    sensor_id : str
        Sensor identifier
    start_date : date
        Start date for the simulation period
    end_date : date
        End date for the simulation period
        
    Returns
    -------
    Optional[Path]
        Path to existing EPW file if found, None otherwise
    """
    weather_dir = Path("./eplus_sim/weather")
    if not weather_dir.exists():
        return None
    
    # First, check for full-year EPW file (preferred for EnergyPlus)
    year = start_date.year
    full_year_filename = f"weather_{sensor_id}_{year}_full_year.epw"
    full_year_path = weather_dir / full_year_filename
    
    if full_year_path.exists():
        return full_year_path
    
    # Fallback: check for specific date range file
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    expected_filename = f"weather_{sensor_id}_{start_str}_{end_str}.epw"
    expected_path = weather_dir / expected_filename
    
    if expected_path.exists():
        return expected_path
    
    # Also check for files with similar date ranges (within a few days)
    pattern = f"weather_{sensor_id}_*.epw"
    for epw_file in weather_dir.glob(pattern):
        try:
            # Check if it's a full-year file
            if "_full_year.epw" in epw_file.name:
                # Extract year from full-year filename
                parts = epw_file.stem.split('_')
                if len(parts) >= 3 and parts[-2].isdigit():
                    file_year = int(parts[-2])
                    if file_year == year:
                        return epw_file
            else:
                # Extract dates from filename for partial period files
                parts = epw_file.stem.split('_')
                if len(parts) >= 4:
                    file_start = datetime.strptime(parts[2], "%Y%m%d").date()
                    file_end = datetime.strptime(parts[3], "%Y%m%d").date()
                    
                    # Check if existing file covers the requested period (with some tolerance)
                    if (file_start <= start_date <= file_end and 
                        file_start <= end_date <= file_end):
                        return epw_file
        except (ValueError, IndexError):
            continue
    
    return None
from ece.helpers import (                                   # noqa: E402
    pmv_ppd, yong_score, annoyance_level as calculate_annoynance_level,
    classify_thermal_category, classify_visual_category, classify_acoustic_category,
    classify_co_category, classify_co2_category, classify_tvoc_category,
    classify_pm25_category, classify_pm10_category,
    get_human_surf_area, basal_metabolic_rate,
    metabolic_rate_fanger, wm2_to_met,
)

# ------------------- project logger -------------------
try:
    from ece.utils.logging import get_logger  # type: ignore[attr-defined]
    logger = get_logger(__name__)
except Exception:  # fallback
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s – %(message)s")
    logger = logging.getLogger(__name__)

# --------------------- FILE LOCATIONS -------------------------
LOGO = Path("./dashboard/assets/images/logo.png")
ECT_LOGO = Path("./dashboard/assets/images/ect_logo.png")
FAVICON = Path("./dashboard/assets/images/favicon.ico")
PROFILES  = Path("./dashboard/assets/config/occupant_profiles.csv")

DUMMY_TEXT = "  " \
"Lorem ipsum dolor sit amet, consectetur adipiscing elit. Nullam vel odio a sem ullamcorper vehicula. Nulla eu porttitor dui. Aliquam commodo a lacus in tincidunt. Phasellus malesuada leo ac ullamcorper dictum. Vestibulum et orci magna. Suspendisse quis fringilla dui, ullamcorper elementum erat. Quisque luctus sem ipsum, at luctus nisi pretium ultricies. Mauris semper vehicula nisl in tristique. Etiam nec mi.  " \
""
_LIMITS = {
    # --- THERMAL -----------------------------------------------------------
    "thermal_class": {
        "A": "|PMV| ≤ 0.20  &  PPD ≤ 6 %",
        "B": "|PMV| ≤ 0.50  &  PPD ≤ 10 %",
        "C": "|PMV| ≤ 0.70  &  PPD ≤ 15 %",
        "NC": "Not classified",
    },
    "thermal_comfort_class": {  # Database column name
        "A": "|PMV| ≤ 0.20  &  PPD ≤ 6 %",
        "B": "|PMV| ≤ 0.50  &  PPD ≤ 10 %",
        "C": "|PMV| ≤ 0.70  &  PPD ≤ 15 %",
        "NC": "Not classified",
    },
    # --- VISUAL (lux) ------------------------------------------------------
    "visual_class": {
        "A": "300 – 500 lx",
        "B": "200 – 300 / 500 – 700 lx",
        "C": "< 200 or ≥ 700 lx",
        "NC": "Not classified",
    },
    "visual_comfort_class": {  # Database column name
        "A": "300 – 500 lx",
        "B": "200 – 300 / 500 – 700 lx",
        "C": "< 200 or ≥ 700 lx",
        "NC": "Not classified",
    },
    # --- ACOUSTIC (LAeq) ---------------------------------------------------
    "acoustic_class": {
        "A": "< 35 dB",
        "B": "35 – 45 dB",
        "C": "45 – 65 dB",
        "D": "≥ 65 dB",
        "NC": "Not classified",
    },
    "acoustic_comfort_class": {  # Database column name
        "A": "< 35 dB",
        "B": "35 – 45 dB",
        "C": "45 – 65 dB",
        "D": "≥ 65 dB",
        "NC": "Not classified",
    },
    # --- OVERALL COMFORT ---------------------------------------------------
    "overall_comfort_class": {
        "A": "≥ 3.5 (Excellent)",
        "B": "2.5 – 3.5 (Good)",
        "C": "1.5 – 2.5 (Acceptable)",
        "D": "0.5 – 1.5 (Poor)",
        "NC": "< 0.5 or No data",
    },
    # --- IAQ sub-metrics ---------------------------------------------------
    "co2_ppm_class":  {"A": "< 550 ppm",  "B": "550 – 800 ppm",  "C": "800 – 1350 ppm", "D": "> 1350 ppm", "NC": "NC"},
    "co2_comfort_class": {"A": "< 550 ppm",  "B": "550 – 800 ppm",  "C": "800 – 1350 ppm", "D": "> 1350 ppm", "NC": "NC"},  # Database column name
    "co_ppm_class":   {"A": "< 35 ppm",   "B": "≥ 35 ppm",                       "NC": "NC"},
    "co_comfort_class": {"A": "< 35 ppm",   "B": "≥ 35 ppm",                     "NC": "NC"},  # Database column name
    "tvoc_ppb_class": {"A": "< 100 ppb",  "B": "≥ 100 ppb",                      "NC": "NC"},
    "tvoc_comfort_class": {"A": "< 100 ppb",  "B": "≥ 100 ppb",                  "NC": "NC"},  # Database column name
    "pm10_ugm3_class":{"A": "< 2.083 μg/m³","B": "≥ 2.083 μg/m³",               "NC": "NC"},
    "pm10_comfort_class":{"A": "< 2.083 μg/m³","B": "≥ 2.083 μg/m³",             "NC": "NC"},  # Database column name
    "pm2_5_ugm3_class":{"A": "< 0.003 μg/m³","B": "≥ 0.003 μg/m³",              "NC": "NC"},
    "pm25_comfort_class":{"A": "< 0.003 μg/m³","B": "≥ 0.003 μg/m³",             "NC": "NC"},  # Database column name
}

# -------------------------------------------------------------------
# Colour palette  (A, B, C, D, NC)
# -------------------------------------------------------------------
_COLOURS = [
    "#2ecc71",  # A – green
    "#f1c40f",  # B – yellow
    "#e67e22",  # C – orange
    "#e74c3c",  # D – red
    "#ffffff",  # NC – white (fallback)
]

# -------------------------------------------------------------------
# Canonical order for classes – keeps colours, legends, and y-axes
# consistent everywhere in the UI
# -------------------------------------------------------------------
_CLASS_ORDER = ["A", "B", "C", "D", "NC"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300)
def _get_sensor_ids() -> list[str]:
    """Return all distinct sensor_id values (sorted) from the DB."""
    with SessionLocal() as ses:
        rows = (
            ses.query(Measurement.sensor_id)
               .filter(Measurement.sensor_id != None)  # noqa: E711
               .distinct()
               .all()
        )
    return sorted(r[0] for r in rows if r[0])

def _clear_cache():
    """Clear all Streamlit caches to free up memory and force fresh data loading."""
    logger.info("User initiated cache clear")
    
    try:
        # Clear all Streamlit caches
        st.cache_data.clear()
        st.cache_resource.clear()
        
        # Clear any cached functions in the app
        if hasattr(st, 'legacy_caching'):
            st.legacy_caching.clear_cache()
            
        logger.info("Successfully cleared all Streamlit caches")
        st.sidebar.success("🧹 Cache cleared successfully!")
        
    except Exception as exc:
        logger.exception("Cache clear failed")
        st.sidebar.error(f"Cache clear failed: {exc}")

def _reset_all():
    logger.warning("User initiated FULL RESET")

    with st.spinner("Resetting database and folders …"):
        try:
            with SessionLocal() as ses:
                deleted = (
                    ses.query(Prediction).delete(synchronize_session=False) +
                    ses.query(Measurement).delete(synchronize_session=False) +
                    ses.query(TrainedModel).delete(synchronize_session=False) +
                    ses.query(Weather).delete(synchronize_session=False) +
                    ses.query(EnergyTimeSeries).delete(synchronize_session=False) +
                    ses.query(EnergySpace).delete(synchronize_session=False) +
                    ses.query(EnergyBuilding).delete(synchronize_session=False)
                )
                ses.commit()
                logger.info("Deleted %d total DB rows", deleted)
        except Exception as exc:
            logger.exception("DB reset failed")
            st.sidebar.error(f"Database reset failed: {exc}")
            return

        # wipe folders including EnergyPlus simulation results and weather files
        folders_to_reset = [
            "./models", 
            "./model_reports", 
            "./uploads",
            "./eplus_sim/results",
            "./eplus_sim/weather",
            "./eplus_sim/models",
            "./eplus_sim/logs",
            "./etc/weather",
            "./logs"
        ]
        
        for folder in folders_to_reset:
            try:
                shutil.rmtree(folder, ignore_errors=True)
                Path(folder).mkdir(parents=True, exist_ok=True)
                logger.info("Reset folder %s", folder)
            except Exception as exc:
                logger.exception("Could not reset folder %s", folder)
                st.sidebar.error(f"Folder reset failed for {folder}: {exc}")
                return

    # clear Streamlit session including energy simulation state
    energy_keys_to_clear = [
        'latest_epw_path', 'latest_sensor_id', 'simulation_running', 
        'prevent_rerun', 'latest_simulation_results'
    ]
    for key in energy_keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
            logger.debug(f"Cleared session state key: {key}")
    
    st.session_state.clear()
    st.sidebar.success("Workspace reset – fresh start!")

# ---------------------------------------------------------------------------
# Sidebar – uploads, training, prediction
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Energy Comfortness Tool", 
    layout="wide",
    page_icon=str(FAVICON) if FAVICON.exists() else "",
    initial_sidebar_state="expanded"
)

# *** PERFORMANCE OPTIMIZATIONS ***
# Configure Streamlit for better performance with large datasets
if 'performance_optimizations_applied' not in st.session_state:
    # Disable some heavy features for better performance
    st.session_state['performance_optimizations_applied'] = True
    logger.info("Applied Streamlit performance optimizations for large datasets")

# ECT Logo at top of sidebar
if ECT_LOGO.exists():
    st.sidebar.image(str(ECT_LOGO), width=120)
else:
    st.sidebar.markdown("###  Energy Comfortness Tool")

lat = st.sidebar.number_input("Latitude",  -90.0, 90.0,  40.6401, format="%.4f")
lon = st.sidebar.number_input("Longitude", -180.0, 180.0, 22.9444, format="%.4f")

# dashboard/app.py  – in _insert_csv()
def _insert_csv(file: bytes, dtype: str, lat: float | None = None, lon: float | None = None):
    try:
        df = pd.read_csv(file, parse_dates=["time_end", "time_stored"])
    except Exception as exc:
        st.sidebar.error(f"Could not read CSV: {exc}")
        logger.exception("CSV read failed")
        return

    # -------------------------------------------
    # keep only columns that really exist on measurements table
    # and let PG fill defaults (time_stored, window_seconds, …)
    # -------------------------------------------
    allowed_cols = {
        "time_end", "sensor_id", "data_type","time_stored", "window_seconds",
        "temperature_c", "energy_kwh", "co2_ppm", "rh_percent",
        "luminance_lux", "average_noise_db", "pm2_5_ugm3", "tvoc_ppb",
        "peak_db", "co_ppm", "pm10_ugm3",
    }
    df = df.reindex(columns=sorted(allowed_cols & set(df.columns)))         # drop the rest
    df["data_type"] = dtype   
    
    # assign the datetime NOW
    df["time_stored"] = datetime.now(tz=timezone.utc)

    # NaN / NaT  ➜  None   (so they become SQL NULL)
    df = df.where(pd.notna(df), None)

    try:
        with SessionLocal() as ses:
            ses.bulk_insert_mappings(
                Measurement,
                df.to_dict("records"),
                render_nulls=True          # keep NULLs, don’t omit keys
            )
            ses.commit()
        st.sidebar.success(f"Inserted {len(df)} {dtype} rows")
        logger.info("Inserted %d %s rows", len(df), dtype)
    except IntegrityError as ie:
        if "unique" in str(ie.orig).lower():
            st.sidebar.warning("Some rows already existed; duplicates ignored.")
            logger.warning("Duplicate rows skipped during %s insert", dtype)
        else:
            st.sidebar.error(f"DB insert failed: {ie}")
            logger.exception("Insert failed")

    # now fetch weather data and add them to the Weather table
    if lat is not None and lon is not None:
        # fetch weather data for the last 6 months
        start = df["time_end"].min()
        end = df["time_end"].max()
        logger.info("Fetching weather data for %s to %s", start, end)
        weather_df = fetch_open_meteo(lat=lat, lon=lon, start=start, end=end)
        weather_df['fetched_at'] = datetime.now(tz=timezone.utc)
        # minor rename 'temperature_2m' to 'outdoor_temperature_2m'
        # and          'relative_humidity_2m' to 'outdoor_relative_humidity_2m'
        weather_df.rename(columns={
            "temperature_2m": "outdoor_temperature_2m",
            "relative_humidity_2m": "outdoor_relative_humidity_2m"
        }, inplace=True)
        logger.info("Weather data fetched: %s" % str(weather_df.shape))
        logger.info("Fetched columns: %s" % str(weather_df.columns))
        try:
            with SessionLocal() as ses:
                # iterate over all unique `sensor_id` values in the dataframe
                # and store weather data for each of them
                for sensor_id in df["sensor_id"].unique():
                    if sensor_id is None:
                        continue
                    # filter weather_df for this sensor_id
                    weather_df_sensor = weather_df.copy()
                    weather_df_sensor["sensor_id"] = sensor_id
                    # keep only the columns that match the Weather model
                    # weather_df_sensor = weather_df_sensor[Weather.__table__.columns.keys()]
                    # weather_df_sensor.drop('weather_id', axis=1, inplace=True, errors='ignore')
                    
                    # if empty, skip this sensor_id
                    if not weather_df.empty:
                        # insert dataframe with session bulk insert mappings
                        ses.bulk_insert_mappings(
                            Weather,
                            weather_df_sensor.to_dict("records"),
                            render_nulls=True  # keep NULLs, don’t omit keys
                        )
                        ses.commit()
                        logger.info("Inserted %d weather rows", len(weather_df))
        except Exception as exc:
            st.sidebar.error(f"Weather data insert failed: {exc}")
            logger.exception("Weather data insert failed")

# _insert_csv(train_csv, "train", lat=lat, lon=lon)
train_csv = st.sidebar.file_uploader("Training Data CSV", type="csv")
if train_csv and st.sidebar.button("Insert training rows"):
    _insert_csv(train_csv,  "train", lat=lat, lon=lon)
    st.cache_data.clear()

# date-range button
TODAY = datetime.now(tz=timezone.utc)
TIME_BEFORE_API = timedelta(days=365 * 2)
TIME_AFTER_API = timedelta(days=15)

min_limit   = TODAY - TIME_BEFORE_API          # earliest selectable
max_limit   = TODAY + TIME_AFTER_API          # latest selectable

DEFAULT_START = date(2025, 6, 15)
DEFAULT_END   = date(2025, 7, 15)

st.sidebar.markdown("### Time window")

start = st.sidebar.date_input(
    "Start",
    value=DEFAULT_START,
    min_value=min_limit.date(),
    max_value=max_limit.date()
)

end = st.sidebar.date_input(
    "End",
    value=DEFAULT_END,
    min_value=min_limit.date(),
    max_value=max_limit.date()
)

start_dt = pd.to_datetime(start)
end_dt = pd.to_datetime(end)

# Store in session state for global access
st.session_state['start_dt'] = start_dt
st.session_state['end_dt'] = end_dt

# # Inference data - DEPRECATED
# infer_csv = st.sidebar.file_uploader("Inference CSV", type="csv")
# if infer_csv and st.sidebar.button("Insert inference rows"):
#     _insert_csv(infer_csv, "inference")
#     st.cache_data.clear()

    
sensor_ids = _get_sensor_ids()
if sensor_ids:
    selected_sensor = st.sidebar.selectbox(
        "Selected space", sensor_ids, key="sensor_filter"
    )
else:
    st.sidebar.warning("⚠️ No spaces available. Please upload training data first.")
    selected_sensor = None

# occupant profile ----------------------------------------------------------
profiles = pd.read_csv(PROFILES)
prof_id = st.sidebar.selectbox("Occupant profile", profiles["occupant_profile_id"])
prof    = profiles.set_index("occupant_profile_id").loc[prof_id]

A_m2   = get_human_surf_area(prof["weight_kg"], prof["height_cm"])
BMR_W  = basal_metabolic_rate(prof)
BMR_kcal = BMR_W / 0.048425
M_Wm2  = metabolic_rate_fanger(BMR_W, A_m2)
M_met  = wm2_to_met(M_Wm2)


st.sidebar.markdown(
    f"""**Profile details**  
• Age: **{prof['age']}**  
• Gender: {prof['gender']}  
• Weight: **{prof['weight_kg']} kg**  
• Height: **{prof['height_cm']} cm**  
• *BMR*: **{BMR_kcal:,.0f} kcal/day**  
• *M*: **{M_Wm2:.1f} W m⁻²**  ≈  **{M_met:.2f} met**  
• *Visual Impairment*: **{prof['visual_impairment']}**"""
)

# st.sidebar.markdown("---")

if "training" not in st.session_state:
    st.session_state["training"] = False
if "predicted" not in st.session_state:
    st.session_state["predicted"] = False


def _train():
    st.session_state["training"] = True
    with st.spinner("Training models …"):
        main_train_all_targets()
    st.session_state["training"] = False
    st.sidebar.success("Training complete")


def _calculate_comfort_on_the_fly(comfort_data: pd.DataFrame, selected_profile: str, age: int = None) -> pd.DataFrame:
    """
    Calculate comfort metrics on-the-fly for a specific occupant profile.
    
    Args:
        comfort_data: DataFrame with prediction data
        selected_profile: Selected occupant profile name
        age: Age of the occupant (if not provided, uses default age mapping)
        
    Returns:
        DataFrame with updated comfort metrics for the profile
    """
    
    # Use provided age or default age mapping
    if age is None:
        profile_ages = {
            "young": 25,
            "middle_aged": 45, 
            "elderly": 65,
            "default": 35
        }
        age = profile_ages.get(selected_profile, 35)
    
    # Import comfort calculation functions
    from ece.helpers import (
        pmv_ppd, classify_thermal_category, classify_acoustic_category,
        annoyance_level
    )
    
    comfort_data_updated = comfort_data.copy()
    
    try:
        # Recalculate age-dependent acoustic comfort metrics
        if 'predicted_average_noise_db' in comfort_data.columns:
            # Calculate age-dependent annoyance levels
            noise_values = comfort_data['predicted_average_noise_db'].dropna()
            if len(noise_values) > 0:
                annoyance_levels = []
                for noise_db in noise_values:
                    annoy_level = calculate_annoynance_level(noise_db, age)
                    annoyance_levels.append(annoy_level if annoy_level is not None else 0)
                
                # Update the acoustic annoyance level column
                comfort_data_updated.loc[noise_values.index, 'acoustic_annoyance_level'] = annoyance_levels
        
        # Update occupant profile column
        comfort_data_updated['occupant_profile'] = selected_profile
        
        logger.info(f"Recalculated comfort metrics for profile '{selected_profile}' (age {age})")
        
    except Exception as e:
        logger.error(f"Error calculating comfort on-the-fly for profile {selected_profile}: {e}")
    
    return comfort_data_updated


def _calculate_comfort_for_profile(prediction_data: dict, profile: dict) -> dict:
    """
    Calculate comfort metrics for a specific occupant profile.
    
    Args:
        prediction_data: Dictionary with predicted environmental values
        profile: Dictionary with profile info (name, age, description)
        
    Returns:
        Dictionary with comfort metrics for the profile
    """
    from ece.helpers import (
        pmv_ppd, classify_thermal_category, classify_visual_category,
        classify_acoustic_category, classify_co2_category, classify_co_category,
        classify_tvoc_category, classify_pm25_category, classify_pm10_category,
        yong_score, annoyance_level
    )
    
    comfort_data = {}
    
    # Thermal comfort (PMV/PPD) - independent of age
    if prediction_data.get('temperature_c') is not None and prediction_data.get('rh_percent') is not None:
        try:
            temperature = float(prediction_data['temperature_c'])
            rh = float(prediction_data['rh_percent'])
            
            # Calculate PMV/PPD using typical office conditions
            pmv_val, ppd_val = pmv_ppd(tdb=temperature, rh=rh, vr=0.1, met=1.1, clo=0.7)
            
            # Handle array vs scalar results
            if hasattr(pmv_val, '__len__'):
                pmv_val = pmv_val[0] if len(pmv_val) > 0 else None
                ppd_val = ppd_val[0] if len(ppd_val) > 0 else None
            
            if pmv_val is not None and ppd_val is not None:
                comfort_data['pmv'] = float(pmv_val)
                comfort_data['ppd'] = float(ppd_val)
                
                # Classify thermal comfort category
                thermal_class = classify_thermal_category([pmv_val], [ppd_val])
                comfort_data['thermal_comfort_class'] = str(thermal_class[0])
                
        except Exception as e:
            logger.warning(f"Error calculating thermal comfort for profile {profile['name']}: {e}")
    
    # Visual comfort - independent of age
    if prediction_data.get('luminance_lux') is not None:
        try:
            lux = float(prediction_data['luminance_lux'])
            
            # Visual comfort score
            vis_score = yong_score(lux)
            if not np.isnan(vis_score):
                comfort_data['visual_comfort_score'] = float(vis_score)
            
            # Visual comfort class
            visual_class = classify_visual_category([lux])
            comfort_data['visual_comfort_class'] = str(visual_class[0])
            
        except Exception as e:
            logger.warning(f"Error calculating visual comfort for profile {profile['name']}: {e}")
    
    # Acoustic comfort - age-dependent
    if prediction_data.get('average_noise_db') is not None:
        try:
            noise_db = float(prediction_data['average_noise_db'])
            age = profile.get('age', 35)
            
            # Age-dependent annoyance level
            annoy_level = calculate_annoynance_level(noise_db, age)
            if annoy_level is not None:
                comfort_data['acoustic_annoyance_level'] = float(annoy_level)
            
            # Acoustic comfort class
            acoustic_class = classify_acoustic_category([noise_db])
            comfort_data['acoustic_comfort_class'] = str(acoustic_class[0])
            
        except Exception as e:
            logger.warning(f"Error calculating acoustic comfort for profile {profile['name']}: {e}")
    
    # Air quality comfort classes - independent of age
    comfort_mappings = [
        ('co2_ppm', 'co2_comfort_class', classify_co2_category),
        ('co_ppm', 'co_comfort_class', classify_co_category), 
        ('tvoc_ppb', 'tvoc_comfort_class', classify_tvoc_category),
        ('pm2_5_ugm3', 'pm25_comfort_class', classify_pm25_category),
        ('pm10_ugm3', 'pm10_comfort_class', classify_pm10_category)
    ]
    
    for pred_key, comfort_key, classify_func in comfort_mappings:
        if prediction_data.get(pred_key) is not None:
            try:
                value = float(prediction_data[pred_key])
                comfort_class = classify_func([value])
                comfort_data[comfort_key] = str(comfort_class[0])
                
                # Store the predicted value used for calculation
                comfort_data[f'predicted_{pred_key}'] = value
                
            except Exception as e:
                logger.warning(f"Error calculating {comfort_key} for profile {profile['name']}: {e}")
    
    # Calculate overall comfort score (weighted average)
    # This is a simplified approach - you might want to implement a more sophisticated weighting
    try:
        comfort_scores = []
        weights = []
        
        # Map comfort classes to numeric scores (A=4, B=3, C=2, D=1, NC=0)
        class_to_score = {'A': 4, 'B': 3, 'C': 2, 'D': 1, 'NC': 0}
        
        comfort_classes = [
            ('thermal_comfort_class', 0.3),  # 30% weight
            ('visual_comfort_class', 0.2),   # 20% weight
            ('acoustic_comfort_class', 0.2), # 20% weight
            ('co2_comfort_class', 0.15),     # 15% weight
            ('tvoc_comfort_class', 0.1),     # 10% weight
            ('pm25_comfort_class', 0.05)     # 5% weight
        ]
        
        for class_key, weight in comfort_classes:
            if class_key in comfort_data:
                score = class_to_score.get(comfort_data[class_key], 0)
                comfort_scores.append(score)
                weights.append(weight)
        
        if comfort_scores:
            # Calculate weighted average
            overall_score = np.average(comfort_scores, weights=weights)
            comfort_data['overall_comfort'] = float(overall_score)
            
            # Convert to overall class
            if overall_score >= 3.5:
                overall_class = 'A'
            elif overall_score >= 2.5:
                overall_class = 'B'
            elif overall_score >= 1.5:
                overall_class = 'C'
            elif overall_score >= 0.5:
                overall_class = 'D'
            else:
                overall_class = 'NC'
            
            comfort_data['overall_comfort_class'] = overall_class
            
    except Exception as e:
        logger.warning(f"Error calculating overall comfort for profile {profile['name']}: {e}")
    
    return comfort_data


def _predict():
    """Run latest models on inference rows, store results with comfort data in DB, update session."""
    st.session_state["predicted"] = False
    logger.info("Prediction trigger clicked")

    import re

    _DERIV_RE = re.compile(r"^(?P<base>.+)_(?P<agg>mean|std|max|min)_(?P<win>\d+)h$")
    _AGG_FUN = {"mean": "mean", "std": "std", "max": "max", "min": "min"}

    with SessionLocal() as ses:
        # ---- load models + resolve model_id per target ----
        models: dict[str, tuple[dict,int]] = {}
        for row in (
            ses.query(TrainedModel)
               .order_by(TrainedModel.target, TrainedModel.train_finished.desc())
               .all()
        ):
            if row.target not in models:  # keep latest per target
                p = Path(row.model_path)
                if p.exists():
                    models[row.target] = (joblib.load(p), row.model_id)
        logger.info("Loaded models for targets: %s", ", ".join(models.keys()))
        if not models:
            st.sidebar.warning("No trained models in DB; train first.")
            return

        # ---- Generate expected timestamps for the date range ----
        # Create hourly timestamps between start_dt and end_dt
        expected_timestamps = pd.date_range(
            start=start_dt,
            end=end_dt,
            freq='h'  # Use lowercase 'h' instead of deprecated 'H'
        )
        
        # ---- Check which weather data is missing ----
        existing_weather_times = set()
        if selected_sensor:
            for sensor_id in [selected_sensor]:
                existing_rows = (
                    ses.query(Weather.time_end)
                    .filter(
                        Weather.time_end.between(start_dt, end_dt),
                        Weather.sensor_id == sensor_id
                    )
                    .all()
                )
                existing_weather_times.update(row[0] for row in existing_rows)
        
        missing_timestamps = set(expected_timestamps) - existing_weather_times
        
        if missing_timestamps:
            logger.info("Missing weather data for %d timestamps. Fetching...", len(missing_timestamps))
            with st.spinner("Fetching missing weather data for predictions..."):
                # Fetch weather data for the entire date range
                # Convert to timezone-aware timestamps for the API call
                start_utc = pd.Timestamp(start_dt).tz_localize('UTC')
                end_utc = pd.Timestamp(end_dt).tz_localize('UTC')
                
                weather_df = fetch_open_meteo(lat=lat, lon=lon, start=start_utc, end=end_utc)
                weather_df['fetched_at'] = datetime.now(tz=timezone.utc)
                weather_df.rename(columns={
                    "temperature_2m": "outdoor_temperature_2m",
                    "relative_humidity_2m": "outdoor_relative_humidity_2m"
                }, inplace=True)
                
                # Insert weather data for selected sensor(s)
                if selected_sensor:
                    sensor_list = [selected_sensor]
                    for sensor_id in sensor_list:
                        # Filter weather data to only missing timestamps
                        weather_df_filtered = weather_df[
                            weather_df['time_end'].isin(missing_timestamps)
                        ].copy()
                        
                        if not weather_df_filtered.empty:
                            weather_df_filtered["sensor_id"] = sensor_id
                            ses.bulk_insert_mappings(
                                Weather,
                                weather_df_filtered.to_dict("records"),
                                render_nulls=True
                            )
                            logger.info("Inserted %d weather rows for sensor %s", 
                                      len(weather_df_filtered), sensor_id)
                
                ses.commit()
                logger.info("Completed fetching missing weather data")

        # ---- fetch inference measurements (now should have complete weather data) ----
        rows = (
                ses.query(Weather)
            .filter(Weather.time_end.between(start_dt, end_dt))
            .all()
        )
        if not rows:
            st.sidebar.warning("No inference rows.")
            return

        # Convert Decimal objects to float to avoid PyArrow serialization issues
        df = pd.DataFrame([{c.name: _convert_decimal_to_float(getattr(r, c.name)) for c in r.__table__.columns} for r in rows])
        # coerce numeric but keep sensor_id untouched
        obj_cols = df.select_dtypes("object").columns.difference(["sensor_id"])        
        for col in obj_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if st.session_state.get("sensor_filter") is not None:
            df = df[df["sensor_id"] == st.session_state["sensor_filter"]]
            logger.info("Filtered data for space '%s' ", st.session_state["sensor_filter"])

        # time drivers
        doy = df["time_end"].dt.dayofyear
        hod = df["time_end"].dt.hour + df["time_end"].dt.minute / 60
        df["doy_sin"] = np.sin(2 * math.pi * doy / 365)
        df["doy_cos"] = np.cos(2 * math.pi * doy / 365)
        df["hour_sin"] = np.sin(2 * math.pi * hod / 24)
        df["hour_cos"] = np.cos(2 * math.pi * hod / 24)

        roll_cache: dict[tuple[str,int,str], pd.Series] = {}
        target_predictions: dict[int, dict] = {}  # weather_id -> prediction data
        skipped: list[str] = []
        done: list[str] = []

        now = datetime.now(tz=timezone.utc)  # Fix deprecated datetime.utcnow()
        
        # Initialize prediction records for each weather_id
        for weather_id in df["weather_id"]:
            target_predictions[int(weather_id)] = {
                "model_id": None,  # Will use the first model's ID
                "weather_id": int(weather_id),
                "predicted_at": now,
                "occupant_profile": prof_id,  # Add occupant profile to predictions
            }
        
        for tgt, (bundle, model_id) in models.items():
            model, feats = bundle["model"], bundle["features"]
            
            # Set model_id for all predictions (use first model encountered)
            if all(pred["model_id"] is None for pred in target_predictions.values()):
                for pred in target_predictions.values():
                    pred["model_id"] = model_id
            
            # derive missing rolling feats
            for f in feats:
                if f in df.columns or f in TIME_DRIVERS:
                    continue
                m = _DERIV_RE.match(f)
                if not m:
                    continue
                base, agg, win = m.group("base"), m.group("agg"), int(m.group("win"))
                if base not in df.columns:
                    continue
                key = (base, win, agg)
                if key not in roll_cache:
                    try:
                        rolled = (
                            df.set_index("time_end").groupby("sensor_id")[base]
                            .rolling(f"{win}h", min_periods=1).agg(_AGG_FUN[agg])
                            .reset_index(level=0, drop=True)
                        )
                        roll_cache[key] = rolled
                    except ValueError:
                        roll_cache[key] = pd.Series([float("nan")] * len(df))
                df[f] = roll_cache[key].values

            if any(f not in df.columns for f in feats):
                skipped.append(tgt)
                continue
            preds = model.predict(df[feats])
            df[f"pred_{tgt}"] = preds
            done.append(tgt)

            # Add predictions to the consolidated prediction records
            col_db = f"predicted_{tgt}"
            for weather_id, pred_val in zip(df["weather_id"], preds):
                target_predictions[int(weather_id)][col_db] = round(float(pred_val), 6)

        # ---- Add comfort calculations to the DataFrame ----
        logger.info("Adding comfort calculations to DataFrame")
        if done and not df.empty:
            df = _add_comfort_cols(df, prof)  # Add comfort columns directly to df
            logger.info("Comfort calculations completed")
            
            # Map comfort columns from DataFrame to database prediction records
            for idx, row in df.iterrows():
                weather_id = int(row["weather_id"])
                if weather_id in target_predictions:
                    pred_data = target_predictions[weather_id]
                    
                    # Add PMV/PPD values if available
                    if 'PMV_pred' in row and pd.notna(row['PMV_pred']):
                        pred_data['pmv'] = float(row['PMV_pred'])
                    if 'PPD_pred' in row and pd.notna(row['PPD_pred']):
                        pred_data['ppd'] = float(row['PPD_pred'])
                    
                    # Add comfort classes
                    if 'thermal_class' in row and pd.notna(row['thermal_class']):
                        pred_data['thermal_comfort_class'] = str(row['thermal_class'])
                    if 'visual_class' in row and pd.notna(row['visual_class']):
                        pred_data['visual_comfort_class'] = str(row['visual_class'])
                    if 'acoustic_class' in row and pd.notna(row['acoustic_class']):
                        pred_data['acoustic_comfort_class'] = str(row['acoustic_class'])
                    
                    # Add comfort scores
                    if 'vis_score_pred' in row and pd.notna(row['vis_score_pred']):
                        pred_data['visual_comfort_score'] = float(row['vis_score_pred'])
                    if 'annoy_pred' in row and pd.notna(row['annoy_pred']):
                        pred_data['acoustic_annoyance_level'] = float(row['annoy_pred'])
                    
                    # Add IAQ comfort classes
                    if 'co2_ppm_class' in row and pd.notna(row['co2_ppm_class']):
                        pred_data['co2_comfort_class'] = str(row['co2_ppm_class'])
                    if 'co_ppm_class' in row and pd.notna(row['co_ppm_class']):
                        pred_data['co_comfort_class'] = str(row['co_ppm_class'])
                    if 'tvoc_ppb_class' in row and pd.notna(row['tvoc_ppb_class']):
                        pred_data['tvoc_comfort_class'] = str(row['tvoc_ppb_class'])
                    if 'pm2_5_ugm3_class' in row and pd.notna(row['pm2_5_ugm3_class']):
                        pred_data['pm25_comfort_class'] = str(row['pm2_5_ugm3_class'])
                    if 'pm10_ugm3_class' in row and pd.notna(row['pm10_ugm3_class']):
                        pred_data['pm10_comfort_class'] = str(row['pm10_ugm3_class'])
                    
                    # Add overall comfort
                    if 'overall_comfort' in row and pd.notna(row['overall_comfort']):
                        pred_data['overall_comfort'] = float(row['overall_comfort'])
                    if 'overall_comfort_class' in row and pd.notna(row['overall_comfort_class']):
                        pred_data['overall_comfort_class'] = str(row['overall_comfort_class'])
            
            logger.info("Comfort data mapped to prediction records")

        # Convert to list for bulk insert
        predictions_bulk = list(target_predictions.values())
        
        if predictions_bulk:
            try:
                ses.bulk_insert_mappings(Prediction, predictions_bulk)
                ses.commit()
                logger.info("Inserted %d prediction rows with %d targets and comfort data for profile '%s'", 
                          len(predictions_bulk), len(done), prof_id)
            except IntegrityError as ie:
                logger.warning("Prediction insert duplicates ignored: %s", ie)
                ses.rollback()
                
                # For existing predictions, we might want to update them with comfort data
                # But for now, we'll just skip and use existing data
                logger.info("Using existing prediction data")

        if skipped:
            st.sidebar.warning("🎯 Skipped targets: " + ", ".join(skipped))
        st.session_state["pred_df"] = df
        st.session_state["predicted"] = True

    st.sidebar.success("Prediction complete")

col1, col2 = st.sidebar.columns(2)
col1.button("🚀 Train models", on_click=_train, disabled=st.session_state["training"])
col2.button("🔮 Predict", on_click=_predict)

# DEBUG: Add test button to check database state
def _test_database_state():
    """Test function to check what's actually in the database."""
    with SessionLocal() as ses:
        # Check predictions
        prediction_count = ses.query(Prediction).count()
        logger.info(f"🔍 Database Test - Predictions in DB: {prediction_count}")
        
        # Check predictions with comfort data
        comfort_predictions = ses.query(Prediction).filter(Prediction.occupant_profile.is_not(None)).count()
        logger.info(f"🔍 Database Test - Predictions with comfort data: {comfort_predictions}")
        
        # Check latest predictions
        latest_predictions = ses.query(Prediction).order_by(Prediction.predicted_at.desc()).limit(5).all()
        logger.info(f"🔍 Database Test - Latest 5 predictions:")
        for pred in latest_predictions:
            logger.info(f"  - Prediction {pred.prediction_id}: profile={pred.occupant_profile}, overall_comfort={pred.overall_comfort}")
            
        # Show summary in UI
        st.sidebar.info(f"📊 DB State: {prediction_count} predictions, {comfort_predictions} with comfort data")

if st.sidebar.button("🔍 Test DB State"):
    _test_database_state()

# Reset and cache management buttons
reset_cache_col1, reset_cache_col2 = st.sidebar.columns(2)

# Clear Cache button
if reset_cache_col1.button("🧹 Clear Cache", help="Clear Streamlit's cache to free memory and force fresh data loading"):
    _clear_cache()

# Reset ALL button with confirmation
if reset_cache_col2.button("⚠ Reset ALL", type="primary", help="WARNING WARNING: This will delete ALL data and reset the workspace"):
    # Initialize confirmation state
    if 'reset_confirmation' not in st.session_state:
        st.session_state.reset_confirmation = False
    
    # Show confirmation dialog
    st.session_state.reset_confirmation = True

# Handle confirmation dialog
if st.session_state.get('reset_confirmation', False):
    with st.sidebar.container():
        st.warning("⚠️ **CONFIRM RESET**")
        st.write("This will permanently delete:")
        st.write("• All measurements, predictions, and models")
        st.write("• All energy simulation results")
        st.write("• All uploaded files and weather data")
        st.write("• All logs and reports")
        
        confirm_col1, confirm_col2 = st.columns(2)
        
        if confirm_col1.button("✅ Yes, Reset", type="primary"):
            st.session_state.reset_confirmation = False
            _reset_all()
            st.rerun()
            
        if confirm_col2.button("❌ Cancel"):
            st.session_state.reset_confirmation = False
            st.rerun()

# logo bottom
st.sidebar.markdown("---")
st.sidebar.image(LOGO, width=140)

# ---------------------------------------------------------------------------
# Display name helpers
# ---------------------------------------------------------------------------
DISPLAY = {
    "time_end": "Timestamp",

    # ---- Measurement labels
    "temperature_c": "Temperature °C",
    "rh_percent": "Relative Humidity %",
    "luminance_lux": "Luminance (lux)",
    "average_noise_db": "Avg Noise (dB)",
    "peak_db": "Peak Noise (dB)",
    "co_ppm":  "CO (ppm)",
    "co2_ppm": "CO₂ (ppm)",
    "pm2_5_ugm3": "PM₂.₅ (µg/m³)",
    "pm2_5_ugm3": "PM10 (µg/m³)",
    "tvoc_ppb": "TVOC (ppb)",

    # --- Comfort labels
    "PMV_pred":         "Predicted PMV",
    "PPD_pred":         "Predicted_PPD (%)",
    "vis_score_pred":   "Visual score",
    "annoy_pred":       "Annoyance lvl",
    "overall_comfort":  "Overall Comfort",

    # --- Comfort classes
    "thermal_class":        "Thermal Comfort",
    "visual_class":         "Visual Comfort",
    "acoustic_class":       "Acoustic Comfort",
    "overall_comfort_class": "Overall Comfort",
    "iaq_class":            "IAQ Index",

    # --- IAQ special
    "co_ppm_class":         "CO",
    "co2_ppm_class":        "CO₂",
    "pm2_5_ugm3_class":     "PM₂.₅",
    "pm2_5_ugm3_class":     "PM10",
    "tvoc_ppb_class":       "TVOC",
}

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

MAX_POINTS = 200_000_000

def _decimate(df: pd.DataFrame, key: str = "Timestamp") -> pd.DataFrame:
    """Return df down-sampled to ≤ MAX_POINTS rows (uniform stride)."""
    n = len(df)
    if n <= MAX_POINTS:
        return df
    stride = max(1, n // MAX_POINTS)
    return df.iloc[::stride].copy()

# ---------------------------------------------------------------------------
# Overall Comfort calculation helper
# ---------------------------------------------------------------------------
def _classify_overall_comfort(overall_comfort_score: float) -> str:
    """
    Classify overall comfort score into comfort classes.
    
    Args:
        overall_comfort_score: Overall comfort score (0-4 scale)
        
    Returns:
        Comfort class: A, B, C, D, or NC
    """
    if pd.isna(overall_comfort_score):
        return "NC"
    
    # Define thresholds for overall comfort classification
    # Based on the 0-4 scale where 4 is best comfort
    if overall_comfort_score >= 3.5:
        return "A"  # Excellent overall comfort
    elif overall_comfort_score >= 2.5:
        return "B"  # Good overall comfort
    elif overall_comfort_score >= 1.5:
        return "C"  # Acceptable overall comfort
    elif overall_comfort_score >= 0.5:
        return "D"  # Poor overall comfort
    else:
        return "NC"  # Not classified / Very poor comfort


def _calculate_overall_comfort(df: pd.DataFrame) -> pd.Series:
    """
    Calculate Overall Comfort as weighted average of comfort classes.
    
    Class Values: A=4, B=3, C=2, D=1, NC=0
    Weights: thermal=1.0, acoustic=0.6, visual=0.6, IAQ metrics=0.2 each
    
    OPTIMIZED VERSION: Uses vectorized operations instead of row-by-row processing
    """
    logger.info(f"Calculating overall comfort for {len(df)} records using vectorized operations...")
    
    # Define class-to-number mapping (A is highest comfort)
    class_values = {"A": 4, "B": 3, "C": 2, "D": 1, "NC": 0}
    
    # Define weights for each comfort category
    weights = {
        "thermal_class": 1.0,
        "acoustic_class": 0.6,
        "visual_class": 0.6,
        "co2_ppm_class": 0.2,
        "co_ppm_class": 0.2,
        "tvoc_ppb_class": 0.2,
        "pm2_5_ugm3_class": 0.2,
        "pm10_ugm3_class": 0.2,
    }
    
    # Initialize result series
    overall_comfort = pd.Series(index=df.index, dtype=float)
    
    # Vectorized approach: process all columns at once
    weighted_sum = pd.Series(0.0, index=df.index)
    total_weight = pd.Series(0.0, index=df.index)
    
    logger.info("Processing comfort classes with vectorized operations...")
    for class_col, weight in weights.items():
        if class_col in df.columns:
            # Convert class values to numeric using vectorized mapping
            class_numeric = df[class_col].map(class_values).fillna(0)
            
            # Create mask for non-null values
            valid_mask = df[class_col].notna()
            
            # Add weighted values where valid
            weighted_sum += class_numeric * weight * valid_mask
            total_weight += weight * valid_mask
    
    # Calculate final scores (avoid division by zero)
    overall_comfort = weighted_sum / total_weight.replace(0, np.nan)
    
    logger.info(f"Vectorized overall comfort calculation completed for {len(overall_comfort)} records")
    return overall_comfort

# ---------------------------------------------------------------------------
# Comfort-metrics enrichment
# ---------------------------------------------------------------------------
def _add_comfort_cols(df: pd.DataFrame, profile) -> pd.DataFrame:
    if {"pred_temperature_c", "pred_rh_percent"}.issubset(df.columns):
        df["PMV_pred"], df["PPD_pred"] = pmv_ppd(
            df["pred_temperature_c"], df["pred_rh_percent"],
            met=profile["activity_level"],
            clo=profile["clothing_insulation_clo"],
        )
        df["thermal_class"] = classify_thermal_category(df["PMV_pred"], df["PPD_pred"])

    if "pred_luminance_lux" in df.columns:
        df["vis_score_pred"] = (
            yong_score(df["pred_luminance_lux"])
            if bool(profile.get("visual_impairment")) else None
        )
        df["visual_class"] = classify_visual_category(df["pred_luminance_lux"])

    if "pred_average_noise_db" in df.columns:
        df["annoy_pred"] = calculate_annoynance_level(df["pred_average_noise_db"], profile["age"])
        df["acoustic_class"] = classify_acoustic_category(df["pred_average_noise_db"])

    if "pred_co2_ppm" in df.columns:
        df["co2_ppm_class"] = classify_co2_category(df["pred_co2_ppm"])
    
    if "pred_co_ppm" in df.columns:
        df["co_ppm_class"] = classify_co_category(df["pred_co_ppm"])
    
    if "pred_tvoc_ppb" in df.columns:
        df["tvoc_ppb_class"] = classify_tvoc_category(df["pred_tvoc_ppb"])

    if "pred_pm2_5_ugm3" in df.columns:
        df["pm2_5_ugm3_class"] = classify_pm25_category(df["pred_pm2_5_ugm3"])

    if "pred_pm10_ugm3" in df.columns:
        df["pm10_ugm3_class"] = classify_pm10_category(df["pred_pm10_ugm3"])
    
    # Calculate Overall Comfort as weighted average of comfort classes
    df["overall_comfort"] = _calculate_overall_comfort(df)
    
    # Classify overall comfort into classes
    df["overall_comfort_class"] = df["overall_comfort"].apply(_classify_overall_comfort)
    
    return df

# ---------------------------------------------------------------------------
# Line chart for time-series
# ---------------------------------------------------------------------------
def _line_chart(df: pd.DataFrame, obs: str | None, pred: str):
    """Draw line+marker chart and add a per-chart CSV export button."""
    # assemble columns
    cols = ["time_end", pred] + ([obs] if obs else [])
    tmp = (_decimate(df[cols])
           .rename(columns={"time_end": "Timestamp",
                            pred: "Predicted",
                            **({obs: "Observed"} if obs else {})}))
    if tmp[["Predicted"]].isna().all().values:
        st.info("No data for this parameter."); return
    # sort by Timestamp
    tmp = tmp.sort_values("Timestamp").reset_index(drop=True)
    tidy = tmp.melt("Timestamp", var_name="Series", value_name="value")
    tidy["order"] = tidy["Series"].map({"Observed": 0, "Predicted": 1})

    title = DISPLAY.get(obs or pred, obs or pred)
    line = (
        alt.Chart(tidy, height=260)
        .mark_line(point=True)
        .encode(
            x=alt.X("Timestamp:T", axis=alt.Axis(format="%d %b %Y", labelAngle=-90)),
            y=alt.Y("value:Q", title=title),
            color=alt.Color("Series", scale=alt.Scale(domain=["Observed", "Predicted"])),
            order="order:Q",
            opacity=alt.condition(alt.datum.Series == "Predicted", alt.value(0.7), alt.value(1)),
        )
        .interactive()
    )
    st.altair_chart(line, use_container_width=True)

    # ----- per-chart CSV export -----
    csv_bytes = tmp.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Export CSV",
        data=csv_bytes,
        file_name=f"{pred}_{datetime.now(tz=timezone.utc):%Y%m%dT%H%M%S}.csv",  # Fix here
        mime="text/csv",
        type="secondary",
        key=f"csv_{pred}_{obs}",
    )


# ---------------------------------------------------------------------------
# Comfort class time-series
# ---------------------------------------------------------------------------
def _class_timeseries(df: pd.DataFrame, cols: list[str], *, title: str):
    """Draw a line/step chart of class evolution over time."""
    logger.info(f"Creating class timeseries for {title} with {len(df)} records and columns: {cols}")
    
    if not cols:
        logger.warning(f"No columns available for {title}")
        st.info(f"No {title.lower()} data"); return

    logger.info("Preparing data for timeseries chart...")
    # tidy: Timestamp | Series | Class
    tmp = (df[["time_end"] + cols]
           .rename(columns={"time_end": "Timestamp"})
           .melt("Timestamp", var_name="Series", value_name="Class")
           .dropna())

    if tmp.empty:
        logger.warning(f"No data available after processing for {title}")
        st.info(f"No {title.lower()} data"); return

    logger.info(f"Creating Altair chart for {title} with {len(tmp)} data points...")
    # ensure consistent ordering on the y-axis
    cat_order = ["A", "B", "C", "D", "NC"]
    cats      = [c for c in cat_order if c in tmp["Class"].unique()]
    chart = (
        alt.Chart(tmp, height=200)
           .mark_line(interpolate="step-after", point=True)
           .encode(
               x=alt.X("Timestamp:T",
                       axis=alt.Axis(title=None, format="%d %b %Y", labelAngle=-90)),
               y=alt.Y("Class:N",
                       sort=cats,
                       axis=alt.Axis(title=title)),
               color="Series:N",
           )
           .interactive()
    )
    logger.info(f"Displaying timeseries chart for {title}...")
    st.altair_chart(chart, use_container_width=True)
    logger.info(f"Timeseries chart displayed successfully for {title}")

    logger.info(f"Creating CSV export for {title}...")
    # download button -------------------------------------------------
    csv_bytes = tmp.to_csv(index=False).encode()
    st.download_button(
        f"Export {title} classes CSV",
        csv_bytes,
        file_name=f"{title.replace(' ', '_').lower()}_classes_{datetime.now(tz=timezone.utc):%Y%m%dT%H%M%S}.csv",  # Fix here
        mime="text/csv",
        type="secondary",
        key=f"csv_classes_{title}"
    )

def _pie_chart(df: pd.DataFrame, class_col: str, *, title: str, context: str = "default") -> None:
    """Draw a pie chart of comfort-class distribution."""
    logger.info(f"Starting pie chart generation for {class_col} with {len(df)} records")
    
    if class_col not in df.columns:
        logger.warning(f"Column {class_col} not found in dataframe. Available columns: {list(df.columns)}")
        st.info(f"No {title.lower()} data")
        return

    logger.info(f"Calculating value counts for {class_col}...")
    # --- counts -----------------------------------------------------------
    counts = (df[class_col]
              .dropna()
              .value_counts()
            #   .sort_index()
               .reindex(["A","B","C","D","NC"], fill_value=0)
              .reset_index()
              .rename(columns={class_col: "Class"}))
    counts["Share"] = counts["count"] / counts["count"].sum()
    logger.info(f"Value counts calculated: {len(counts)} classes")

    logger.info(f"Building legend labels for {class_col}...")
    # --- build legend labels "A (limits)" ---------------------------------
    limits = _LIMITS.get(class_col, {})
    counts["Label"] = counts["Class"].apply(
        lambda c: f"{c} ({limits.get(c,'')})" if c in limits else c
    )

    logger.info(f"Creating Altair chart for {class_col}...")
    # stable ordering  A,B,C,D,NC  → keeps colours fixed
    # order = [c for c in ["A", "B", "C", "D", "NC"] if c in counts["Class"].values]
    # order = ["A", "B", "C", "D", "NC"]
    order = list(_LIMITS[class_col].keys())
    palette = _COLOURS[: len(order)]

    chart = (
        alt.Chart(counts, height=300, width=300)
           .mark_arc(innerRadius=0)
           .encode(
                theta="Share:Q",
                color=alt.Color(
                    "Label:N",
                    sort=order,
                    scale=alt.Scale(
                        domain=[f"{c} ({limits.get(c,'')})" for c in order],
                        range=palette,
                    ),
                legend=alt.Legend(
                    title     = title,
                    # orient    = "top-left",    # manual placement!
                    #    legendX   = 160,       # px from left of the chart
                    #    legendY   = 10,        # px from top
                    #    padding   = 0,         # no extra gap
                    #    labelPadding = 2,
                    #    labelLimit   = 80,
                         ),
               ),
               tooltip=[
                   "Label:N",
                   alt.Tooltip("Share:Q", format=".0%")
               ],
            )
    )
    logger.info(f"Displaying Altair chart for {class_col}...")
    st.altair_chart(chart, use_container_width=True)
    logger.info(f"Chart displayed successfully for {class_col}")
    
    # ----- per-chart CSV export -----
    logger.info(f"Creating CSV export button for {class_col}...")
    csv_bytes = counts.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Export CSV",
        data=csv_bytes,
        file_name=f"{class_col}_{datetime.now(tz=timezone.utc):%Y%m%dT%H%M%S}.csv",  # Fix here
        mime="text/csv",
        type="secondary",
        key=f"csv_{context}_{class_col}",
    )
    logger.info(f"Pie chart generation completed for {class_col}")

# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
if st.session_state.get("predicted"):
    df_pred: pd.DataFrame = st.session_state["pred_df"]
    
    # Select based on space
    sel = st.session_state.get("sensor_filter").strip()
    if sel:
        df_pred = df_pred[df_pred["sensor_id"] == sel]
        logger.info("Plotting data for space %s", sel)
    
    # ---- Fetch actual measurements and merge with predictions ----
    with SessionLocal() as ses:
        measurement_rows = (
            ses.query(Measurement)
            .filter(
                Measurement.time_end.between(start_dt, end_dt),
                Measurement.sensor_id.in_(
                    [sel] if sel else _get_sensor_ids()
                )
            )
            .all()
        )
        
        if measurement_rows:
            # Convert Decimal objects to float to avoid PyArrow serialization issues
            df_obs = pd.DataFrame([{c.name: _convert_decimal_to_float(getattr(r, c.name)) for c in r.__table__.columns} for r in measurement_rows])
            # Filter by selected sensor if needed
            if sel:
                df_obs = df_obs[df_obs["sensor_id"] == sel]
            
            # Merge observations with predictions on time_end and sensor_id
            df_pred = pd.merge(
                df_pred, 
                df_obs[["time_end", "sensor_id", "temperature_c", "rh_percent", "luminance_lux", 
                       "average_noise_db", "peak_db", "co2_ppm", "pm2_5_ugm3", "tvoc_ppb", 
                       "co_ppm", "pm10_ugm3"]],
                on=["time_end", "sensor_id"],
                how="left"  # Keep all predictions, add observations where available
            )
            logger.info("Merged %d measurement rows with predictions", len(df_obs))
        else:
            logger.info("No measurement data available for comparison")
    
    # ---- Fetch comfort data and merge with predictions ----
    # Check if comfort data is already in df_pred (from recent predictions)
    has_comfort_in_df = any(col in df_pred.columns for col in ['PMV_pred', 'PPD_pred', 'thermal_class'])
    
    if not has_comfort_in_df:
        logger.info("Comfort data not found in predictions DataFrame, fetching from database")
        try:
            with SessionLocal() as ses:
                # Get the current occupant profile from sidebar (use actual prof_id)
                selected_profile = prof_id
                
                logger.info(f"Fetching comfort data for profile '{selected_profile}' from predictions table")
                
                # Query Prediction data for the current date range and sensor filter
                comfort_query = (ses.query(Prediction, Weather)
                               .join(Weather, Prediction.weather_id == Weather.weather_id)
                               .filter(Prediction.occupant_profile == selected_profile)
                               .filter(Weather.time_end.between(start_dt, end_dt))
                               .filter(Prediction.pmv.isnot(None)))  # Only get predictions with comfort data
                
                if sel:
                    comfort_query = comfort_query.filter(Weather.sensor_id == sel)
                
                comfort_results = comfort_query.all()
                
                if comfort_results:
                    logger.info(f"Found {len(comfort_results)} comfort records to merge")
                    
                    # Create comfort dataframe with standardized column names for line charts
                    comfort_df_data = []
                    for prediction, weather in comfort_results:
                        comfort_df_data.append({
                            'time_end': weather.time_end,
                            'sensor_id': weather.sensor_id,
                            'PMV_pred': _convert_decimal_to_float(prediction.pmv),
                            'PPD_pred': _convert_decimal_to_float(prediction.ppd),
                            'vis_score_pred': _convert_decimal_to_float(prediction.visual_comfort_score),
                            'annoy_pred': _convert_decimal_to_float(prediction.acoustic_annoyance_level),
                            'thermal_class': prediction.thermal_comfort_class,
                            'visual_class': prediction.visual_comfort_class,
                            'acoustic_class': prediction.acoustic_comfort_class,
                            'co2_comfort_class': prediction.co2_comfort_class,
                        })
                    
                    comfort_df = pd.DataFrame(comfort_df_data)
                    
                    # Merge comfort data with predictions on time_end and sensor_id
                    df_pred = pd.merge(
                        df_pred, 
                        comfort_df,
                        on=["time_end", "sensor_id"],
                        how="left"  # Keep all predictions, add comfort where available
                    )
                    logger.info(f"Merged comfort data with predictions. Comfort columns added: {list(comfort_df.columns)}")
                else:
                    logger.info("No comfort data found for the current filters")
                    # Add empty comfort columns so charts don't fail
                    df_pred['PMV_pred'] = None
                    df_pred['PPD_pred'] = None
                    df_pred['vis_score_pred'] = None
                    df_pred['annoy_pred'] = None
                    df_pred['thermal_class'] = None
                    df_pred['visual_class'] = None
                    df_pred['acoustic_class'] = None
                    df_pred['co2_comfort_class'] = None
                    
        except Exception as e:
            logger.error(f"Error fetching comfort data for line charts: {e}", exc_info=True)
            # Add empty comfort columns so charts don't fail
            df_pred['PMV_pred'] = None
            df_pred['PPD_pred'] = None
            df_pred['vis_score_pred'] = None
            df_pred['annoy_pred'] = None
            df_pred['thermal_class'] = None
            df_pred['visual_class'] = None
            df_pred['acoustic_class'] = None
            df_pred['co2_comfort_class'] = None
    else:
        logger.info("Comfort data already present in predictions DataFrame")

    # filter by datetime selector
    mask = (df_pred["time_end"] >= start_dt) & (df_pred["time_end"] <= end_dt)
    df_pred = df_pred.loc[mask].copy()
    
    logger.info(
        "Date-time filter  %s -> %s   rows kept: %d",
        start_dt, end_dt, len(df_pred)
    )

    # setup tabs
    tabs = st.tabs(["Thermal", "Visual", "Acoustic", "IAQ", "Energy", "Energy Comfortness"])
    domain_map = {
        "Thermal": ["temperature_c", "rh_percent", "PMV_pred", "PPD_pred"],
        "Visual": ["luminance_lux", "vis_score_pred"],
        "Acoustic": ["average_noise_db", "peak_db", "annoy_pred"],
        "IAQ": ["co2_ppm", "pm2_5_ugm3", "tvoc_ppb"],
        "Energy": [],  # Will be handled separately
        "Energy Comfortness": [],  # Will be handled separately
    }
    for name, tab in zip(domain_map.keys(), tabs):
        with tab:
            if name == 'Energy':
                # ========== Energy Comfortness Tab ==========
                st.header(" Energy Simulation")
                st.markdown("Generate weather files and run energy simulations for building comfort analysis.")
                
                # Check if we should prevent UI updates during simulation
                if st.session_state.get('prevent_rerun', False):
                    logger.info("UI updates prevented during simulation - showing simulation in progress message")
                    st.info("⚙️ Simulation in progress... Please wait.")
                    st.stop()
                
                # **NEW: Display latest simulation results only if they match the current date filter**
                logger.debug("Checking for latest simulation results to display by default")
                latest_results = _get_latest_simulation_results()
                if latest_results:
                    logger.info(f"Found latest simulation results: {latest_results.get('timestamp', 'unknown timestamp')}")
                    
                    # Extract simulation year and check if it matches the selected date range
                    show_results = False
                    if 'eplus_results_path' in latest_results:
                        actual_results_dir = Path(latest_results['eplus_results_path'])
                        simulation_year = _get_simulation_year_from_epw(actual_results_dir)
                        
                        if simulation_year:
                            logger.info(f"Extracted simulation year: {simulation_year}")
                            # Check if simulation year overlaps with selected date range
                            selected_years = set(range(start.year, end.year + 1))
                            if simulation_year in selected_years:
                                show_results = True
                                logger.info(f"Simulation year {simulation_year} matches selected date range {start.year}-{end.year}")
                            else:
                                logger.info(f"Simulation year {simulation_year} does not match selected date range {start.year}-{end.year}")
                        else:
                            logger.warning("Could not extract simulation year from EPW file")
                    
                    if show_results:
                        with st.expander("📊 Latest Simulation Results", expanded=True):
                            # Energy tab always shows building-wide data regardless of space selection
                            _display_energy_results(latest_results, "latest")
                    else:
                        st.info("💡 Latest simulation results are from a different time period than your current selection. Adjust the date range or run a new simulation.")
                else:
                    logger.info("No latest simulation results found")
                
                # Display current settings from sidebar
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("🌍 Location Settings")
                    st.info(f"**Latitude:** {lat}  \n**Longitude:** {lon}")
                    st.caption("💡 Adjust location in the sidebar")
                
                with col2:
                    st.subheader("📅 Time Range Settings")
                    st.info(f"**Start:** {start}  \n**End:** {end}")
                    st.caption("💡 Adjust time range in the sidebar")
                
                # Check for existing EPW files
                sensor_ids = _get_sensor_ids()
                target_sensor = selected_sensor or (sensor_ids[0] if sensor_ids else None)
                
                existing_epw = None
                if target_sensor:
                    existing_epw = _find_existing_epw_file(target_sensor, start, end)
                
                # Display EPW file status with refresh button
                header_col1, header_col2 = st.columns([3, 1])
                with header_col1:
                    st.subheader("🌤️ Weather File Status")
                with header_col2:
                    if st.button("🔄 Refresh", help="Refresh weather file status"):
                        st.rerun()
                
                if existing_epw:
                    st.success(f"✅ Weather file already exists: `{existing_epw.name}`")
                    file_size = existing_epw.stat().st_size / 1024  # KB
                    col1_status, col2_status = st.columns(2)
                    col1_status.metric("File Size", f"{file_size:.1f} KB")
                    col2_status.metric("Sensor", target_sensor)
                    
                    # Option to download existing file
                    with open(existing_epw, 'rb') as f:
                        st.download_button(
                            label="⬇️ Download Existing EPW File",
                            data=f.read(),
                            file_name=existing_epw.name,
                            mime="application/octet-stream",
                            key="download_existing_epw"
                        )
                else:
                    if target_sensor:
                        st.info(f"ℹ️ No weather file found for sensor `{target_sensor}` and selected time range.")
                        st.caption("You'll need to generate a new weather file before running simulations.")
                    else:
                        st.warning("⚠️ No sensor data available. Please upload training data first.")
                
                # Input form for simulation parameters
                with st.form("energy_simulation_form"):
                    st.subheader("� Building Model")
                    uploaded_file = st.file_uploader(
                        "Upload IFC file", 
                        type=['ifc'], 
                        help="Upload an IFC (Industry Foundation Classes) file for building simulation"
                    )
                    
                    # Check if bim2sim environment is available
                    bim2sim_available = test_bim2sim_environment()
                    if not bim2sim_available:
                        st.warning("⚠️ bim2sim conda environment not detected. EnergyPlus simulation will not be available.")
                        st.info("Make sure you have a conda environment named 'bim2sim' with bim2sim installed.")
                    
                    # Validate date range
                    if start >= end:
                        st.error("❌ Invalid date range. End date must be after start date.")
                        simulate_button_disabled = True
                    else:
                        simulate_button_disabled = False
                    
                    # Determine EPW file existence early for use in requirements display
                    epw_exists = existing_epw is not None
                    
                    # Check and display requirements status with checkmarks
                    st.subheader("📋 Current Status") 
                    st.info("📁 **Note:** IFC file validation will occur when you submit the form.")
                    
                    req_col1, req_col2 = st.columns(2)
                    
                    with req_col1:
                        # Weather file requirement
                        if epw_exists:
                            st.success("✅ Weather file available")
                        else:
                            st.error("❌ Weather file required")
                            # Debug info
                            st.caption(f"🔍 Debug: Sensor='{target_sensor}', EPW={existing_epw}")
                            if target_sensor:
                                from pathlib import Path
                                weather_dir = Path("./eplus_sim/weather")
                                expected_file = f"weather_{target_sensor}_{start.year}_full_year.epw"
                                st.caption(f"🔍 Looking for: {expected_file}")
                                st.caption(f"🔍 Weather dir exists: {weather_dir.exists()}")
                                if weather_dir.exists():
                                    epw_files = list(weather_dir.glob("*.epw"))
                                    st.caption(f"🔍 Found {len(epw_files)} EPW files")
                                    for f in epw_files:
                                        st.caption(f"  📄 {f.name}")
                        
                        # Date range requirement  
                        if not simulate_button_disabled:
                            st.success("✅ Valid date range")
                        else:
                            st.error("❌ Valid date range required")
                    
                    with req_col2:
                        # bim2sim environment requirement
                        if bim2sim_available:
                            st.success("✅ bim2sim environment available")
                        else:
                            st.error("❌ bim2sim environment required")
                    
                    col1, col2 = st.columns(2)
                    
                    # Enable buttons based on requirements we can check before form submission
                    basic_requirements_met = (bim2sim_available and not simulate_button_disabled)
                    
                    # Initialize button variables
                    generate_weather_button = False
                    run_simulation_button = False
                    
                    with col1:
                        # Generate weather file button (always enabled, allow regeneration)
                        button_text = "🌤️ Regenerate Weather File" if epw_exists else "🌤️ Generate Weather File"
                        generate_weather_button = st.form_submit_button(
                            button_text, 
                            type="secondary",
                            help="Generate EPW weather file for the specified location and time range",
                            disabled=simulate_button_disabled
                        )
                    
                    with col2:
                        # Run simulation button - enable if basic requirements met, validate file after submission
                        if epw_exists:
                            button_help = "Upload an IFC file and click to run simulation" if basic_requirements_met else "Fix environment issues first"
                            
                            run_simulation_button = st.form_submit_button(
                                "🏃‍♂️ Run Simulation", 
                                type="primary",
                                help=button_help,
                                disabled=not basic_requirements_met
                            )
                        else:
                            button_help = "Upload an IFC file and click to generate weather + run simulation" if basic_requirements_met else "Fix environment issues first"
                            
                            run_simulation_button = st.form_submit_button(
                                "🏃‍♂️ Generate Weather + Run Simulation", 
                                type="primary",
                                help=button_help,
                                disabled=not basic_requirements_met
                            )
                
                # Handle simulation execution - validate file after form submission
                if generate_weather_button or run_simulation_button:
                    logger.info(f"Simulation button clicked - Generate: {generate_weather_button}, Run: {run_simulation_button}")
                    logger.debug(f"Selected sensor: {selected_sensor}, Target sensor: {target_sensor}")
                    logger.debug(f"Date range: {start} to {end}")
                    logger.debug(f"Location: lat={lat}, lon={lon}")
                    
                    # Now we can properly validate the uploaded file since form was submitted
                    validation_errors = []
                    
                    if start >= end:
                        validation_errors.append("Invalid date range")
                        logger.warning(f"Invalid date range: {start} >= {end}")
                    
                    if run_simulation_button and uploaded_file is None:
                        validation_errors.append("No IFC file uploaded")
                        logger.warning("Run simulation requested but no IFC file uploaded")
                    
                    if run_simulation_button and not bim2sim_available:
                        validation_errors.append("bim2sim environment not available")
                        logger.error("Run simulation requested but bim2sim environment not available")
                    
                    if run_simulation_button and not epw_exists and not generate_weather_button:
                        validation_errors.append("No weather file available")
                        logger.warning("Run simulation requested but no weather file available")
                    
                    logger.debug(f"Validation check complete. Errors: {validation_errors}")
                    
                    # Show post-submission validation results
                    if validation_errors:
                        logger.error(f"Validation failed: {', '.join(validation_errors)}")
                        st.error(f"❌ Cannot proceed: {', '.join(validation_errors)}")
                        
                        # Show detailed requirements status after form submission
                        st.subheader("📋 Detailed Requirements Check")
                        req_col1, req_col2 = st.columns(2)
                        
                        with req_col1:
                            # Weather file requirement
                            if epw_exists:
                                st.success("✅ Weather file available")
                            else:
                                st.error("❌ Weather file required")
                            
                            # IFC file requirement (now we can check uploaded_file after submission)
                            if uploaded_file is not None:
                                st.success("✅ IFC file uploaded")
                                st.info(f"📄 File: {uploaded_file.name} ({uploaded_file.size} bytes)")
                            else:
                                st.error("❌ IFC file required")
                        
                        with req_col2:
                            # bim2sim environment requirement
                            if bim2sim_available:
                                st.success("✅ bim2sim environment available")
                            else:
                                st.error("❌ bim2sim environment required")
                            
                            # Date range requirement
                            if not simulate_button_disabled:
                                st.success("✅ Valid date range")
                            else:
                                st.error("❌ Valid date range required")
                        
                        st.info("💡 **Tip:** Make sure to upload an IFC file before clicking the Run Simulation button.")
                    
                    else:
                        # All validations passed, proceed with simulation
                        logger.info("All validations passed, proceeding with simulation")
                        # Create progress indicators
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        try:
                            # Determine if we need to generate weather file or use existing
                            if existing_epw and run_simulation_button:
                                # Use existing EPW file
                                epw_path = existing_epw
                                logger.info(f"Using existing weather file: {epw_path}")
                                status_text.text("✅ Using existing weather file...")
                                progress_bar.progress(20)
                                st.info(f"📄 Using existing weather file: `{epw_path.name}`")
                            else:
                                # Step 1: Generate weather file
                                logger.info("Starting weather file generation")
                                status_text.text("🌤️ Generating weather file...")
                                progress_bar.progress(20)
                                
                                # Convert dates to datetime for the pipeline
                                start_datetime = datetime.combine(start, datetime.min.time())
                                end_datetime = datetime.combine(end, datetime.min.time())
                                logger.debug(f"Date range for weather generation: {start_datetime} to {end_datetime}")
                                
                                # Use the selected sensor or default to first available sensor
                                sensor_list = _get_sensor_ids()
                                logger.debug(f"Available sensors: {sensor_list}")
                                
                                if not sensor_list:
                                    logger.error("No sensor data available for weather generation")
                                    st.error("❌ No sensor data available. Please upload training data first.")
                                    st.stop()
                                
                                target_sensor = selected_sensor or sensor_list[0]
                                logger.info(f"Using target sensor for weather generation: {target_sensor}")
                                
                                # Call the weather pipeline with full-year option
                                logger.info("Calling generate_epw_for_location function")
                                with st.spinner("WEATHER Generating weather file... This may take a few moments."):
                                    epw_path = generate_epw_for_location(
                                        sensor_id=target_sensor,
                                        latitude=lat,
                                        longitude=lon,
                                        start=start_datetime,
                                        end=end_datetime,
                                        full_year=True  # Generate full-year EPW for EnergyPlus compatibility
                                    )
                                logger.info(f"Weather file generated successfully: {epw_path}")
                                
                                # Store weather file path in session state for potential EnergyPlus simulation
                                st.session_state['latest_epw_path'] = epw_path
                                st.session_state['latest_sensor_id'] = target_sensor
                                logger.debug("Stored weather file path and sensor ID in session state")
                                
                                # Show success message
                                st.success(f"✅ Weather file generated successfully: `{epw_path.name}`")
                                progress_bar.progress(100)
                                status_text.text("✅ Weather file generation completed!")
                                
                                # If this was just weather generation (not full simulation), trigger a rerun to refresh the UI
                                if not run_simulation_button:
                                    logger.info("Weather generation only - triggering UI refresh")
                                    st.rerun()
                            
                            # If this is a full simulation request, continue with EnergyPlus
                            if run_simulation_button and uploaded_file is not None:
                                logger.info("Starting EnergyPlus simulation workflow")
                                
                                # **MAJOR FIX: Wrap the ENTIRE EnergyPlus pipeline in a spinner to prevent UI refresh**
                                st.subheader("🏃‍♂️ Running EnergyPlus Simulation")
                                st.info("⏳ Please wait while the simulation is running. This may take several minutes...")
                                
                                # Create a comprehensive spinner that blocks the entire pipeline
                                with st.spinner("PROCESSING EnergyPlus simulation pipeline in progress... Please do not switch tabs or refresh the page."):
                                    try:
                                        # Disable the entire UI during simulation
                                        st.session_state.simulation_running = True
                                        st.session_state.prevent_rerun = True
                                        logger.debug("Set simulation_running and prevent_rerun flags to True")
                                        
                                        # Step 2: Save uploaded IFC file
                                        logger.info("Saving uploaded IFC file")
                                        status_text.text("📁 Preparing IFC file...")
                                        progress_bar.progress(40)
                                        
                                        # Create models directory and save IFC file
                                        models_dir = Path("./eplus_sim/models")
                                        models_dir.mkdir(parents=True, exist_ok=True)
                                        logger.debug(f"Created models directory: {models_dir}")
                                        
                                        # Save uploaded file
                                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                        ifc_filename = f"{target_sensor}_{timestamp}.ifc"
                                        ifc_path = models_dir / ifc_filename
                                        logger.debug(f"Saving IFC file as: {ifc_path}")
                                        
                                        with open(ifc_path, "wb") as f:
                                            f.write(uploaded_file.getbuffer())
                                        
                                        logger.info(f"IFC file saved successfully: {ifc_path} ({uploaded_file.size} bytes)")
                                        
                                        # Step 3: Run EnergyPlus simulation
                                        logger.info("Starting EnergyPlus simulation")
                                        status_text.text("🏃‍♂️ Running EnergyPlus simulation...")
                                        progress_bar.progress(60)
                                        
                                        # Call the EnergyPlus pipeline via conda run
                                        logger.info(f"Calling run_eplus_simulation_async with IFC: {ifc_path}, EPW: {epw_path}")
                                        simulation_results = run_eplus_simulation_async(
                                            ifc_file_path=ifc_path,
                                            weather_file_path=epw_path,
                                            sensor_id=target_sensor,
                                            project_base_dir=Path("./eplus_sim")
                                        )
                                        
                                        progress_bar.progress(80)
                                        status_text.text("📊 Processing simulation results...")
                                        logger.info(f"EnergyPlus simulation completed. Success: {simulation_results.get('success', False)}")
                                        
                                        # Step 4: Process and store results (still within spinner)
                                        if simulation_results["success"]:
                                            logger.info("EnergyPlus simulation completed successfully")
                                            
                                            # **Store simulation results in database**
                                            logger.info("Storing energy simulation results in database")
                                            try:
                                                storage_success = _store_energy_simulation_results(
                                                    simulation_results, target_sensor, str(ifc_path), str(epw_path)
                                                )
                                                if storage_success:
                                                    logger.info("SUCCESS Energy simulation results stored in database")
                                                else:
                                                    logger.warning("ERROR Failed to store energy simulation results in database")
                                            except Exception as e:
                                                logger.error(f"Error storing simulation results: {str(e)}", exc_info=True)
                                            
                                            progress_bar.progress(100)
                                            status_text.text("✅ Simulation completed successfully!")
                                        else:
                                            logger.error(f"EnergyPlus simulation failed: {simulation_results.get('error', 'Unknown error')}")
                                            progress_bar.progress(0)
                                            status_text.text("❌ Simulation failed")
                                        
                                        # Re-enable UI after everything is complete
                                        st.session_state.simulation_running = False
                                        st.session_state.prevent_rerun = False
                                        logger.debug("Reset simulation_running and prevent_rerun flags")
                                    
                                    except Exception as e:
                                        # Make sure we reset flags even if there's an error
                                        st.session_state.simulation_running = False
                                        st.session_state.prevent_rerun = False
                                        logger.error(f"Error during EnergyPlus simulation: {str(e)}", exc_info=True)
                                        progress_bar.progress(0)
                                        status_text.text("❌ Simulation failed")
                                        raise  # Re-raise to show error to user
                                
                                # Now display results AFTER the spinner completes
                                if simulation_results["success"]:
                                    st.success("✔️ EnergyPlus simulation completed successfully!")
                                    
                                    # Display simulation results
                                    project_path = simulation_results['project_path']
                                    logger.info(f"Simulation results saved to: {project_path}")
                                    st.info(f"📁 Results saved to: `{project_path}`")
                                    
                                    # Show database storage status
                                    if storage_success:
                                        st.success("💾 Energy data successfully stored in database!")
                                    else:
                                        st.warning("⚠️ Energy data could not be stored in database (check logs)")
                                    
                                    # **Visualize energy results**
                                    logger.info("Starting energy results visualization")
                                    # Energy tab always shows building-wide data regardless of space selection
                                    _display_energy_results(simulation_results, "latest")
                                    
                                    # Show bim2sim logs if available
                                    if simulation_results.get("process_stdout"):
                                        logger.debug("Displaying bim2sim simulation logs")
                                        with st.expander("📋 bim2sim Simulation Logs"):
                                            st.text_area(
                                                "Detailed logs from bim2sim simulation:",
                                                value=simulation_results["process_stdout"],
                                                height=300,
                                                help="These are the detailed logs from the bim2sim simulation process"
                                            )
                                    
                                    # Show simulation details
                                    with st.expander("🔍 Simulation Technical Details"):
                                        st.json(simulation_results)
                                else:
                                    st.error(f"❌ EnergyPlus simulation failed: {simulation_results.get('error', 'Unknown error')}")
                                    
                                    # Show bim2sim error logs prominently
                                    if simulation_results.get("process_stderr"):
                                        logger.debug("Displaying bim2sim error logs")
                                        st.subheader("🚨 Error Logs")
                                        st.error("**bim2sim Error Output:**")
                                        st.text_area(
                                            "Error details:",
                                            value=simulation_results["process_stderr"],
                                            height=200,
                                            help="Error messages from the bim2sim simulation process"
                                        )
                                    
                                    if simulation_results.get("process_stdout"):
                                        with st.expander("📋 Full bim2sim Output (for debugging)"):
                                            st.text_area(
                                                "Complete output from bim2sim:",
                                                value=simulation_results["process_stdout"],
                                                height=300,
                                                help="Complete output from the bim2sim simulation process"
                                            )
                                    
                                    # Show technical error details
                                    with st.expander("🔍 Technical Error Details"):
                                        st.json(simulation_results)
                            else:
                                # Just weather file generation - display completion
                                logger.info("Weather file generation completed successfully")
                                progress_bar.progress(100)
                                status_text.text("✅ Weather file generation completed!")
                                st.success(f"✔️ Weather file successfully generated!")
                            
                            # Display file info (common for both paths)
                            logger.info(f"Final weather file path: {epw_path}")
                            st.info(f"📄 Weather file saved to: `{epw_path}`")
                            if os.path.exists(epw_path):
                                file_size = os.path.getsize(epw_path) / 1024  # KB
                                logger.debug(f"Weather file size: {file_size:.1f} KB")
                                st.metric("File Size", f"{file_size:.1f} KB")
                                
                                # Option to download the file
                                with open(epw_path, 'rb') as f:
                                    st.download_button(
                                        label="⬇️ Download EPW File",
                                        data=f.read(),
                                        file_name=os.path.basename(epw_path),
                                        mime="application/octet-stream"
                                    )
                            else:
                                logger.warning(f"Weather file not found after generation: {epw_path}")
                            
                        except Exception as e:
                            logger.error(f"Error during weather file generation: {str(e)}", exc_info=True)
                            progress_bar.progress(0)
                            status_text.text("❌ Generation failed")
                            st.error(f"❌ Error generating weather file: {str(e)}")
                
                # Information section
                st.markdown("---")
                st.subheader("ℹ️ About Energy Simulation")
                st.markdown("""
                **Weather File Generation:**
                - Creates EPW (EnergyPlus Weather) files from historical weather data
                - Uses weather data stored in the database for the specified location and time range
                - Generated files can be used with EnergyPlus and other building simulation tools
                
                **EnergyPlus Building Simulation:**
                - Converts IFC building models to IDF format using bim2sim
                - Runs detailed building energy simulations
                - Generates comprehensive energy and comfort analysis reports
                
                **Workflow:**
                1. Upload an IFC building model file
                2. Generate weather data for your location and time period
                3. Run EnergyPlus simulation with the generated weather file
                4. Analyze results for energy consumption and comfort metrics
                """)
                
                # Log viewer section
                st.markdown("---")
                st.subheader("📊 Application Logs")
                
                with st.expander("🔍 View Application Logs"):
                    st.info("**Note:** Detailed bim2sim logs appear here during simulation runs. Check the main application log file for complete history.")
                    
                    # Option to view recent log file
                    log_path = Path("./logs/__main__.log")
                    if log_path.exists():
                        try:
                            # Read last 100 lines of log file
                            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                                lines = f.readlines()
                                recent_lines = lines[-100:] if len(lines) > 100 else lines
                            
                            log_content = ''.join(recent_lines)
                            st.text_area(
                                "Recent application logs (last 100 lines):",
                                value=log_content,
                                height=400,
                                help="This shows the most recent entries from the application log file"
                            )
                            
                            # Button to download full log
                            with open(log_path, 'rb') as f:
                                st.download_button(
                                    label="⬇️ Download Full Log File",
                                    data=f.read(),
                                    file_name=f"energy_tool_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
                                    mime="text/plain"
                                )
                                
                        except Exception as e:
                            st.error(f"Could not read log file: {e}")
                    else:
                        st.warning("No log file found. Logs will appear here after running simulations.")
                        
                    # Show log file location for manual access
                    st.caption(f"💡 **Log file location:** `{log_path.absolute()}`")
                
            elif name == 'Energy Comfortness':
                # ========== Energy Comfortness Tab ==========
                st.header("🔥❄️ Energy Comfortness Analysis")
                st.markdown("Analyze heating and cooling energy patterns for space comfort optimization.")
                
                # Get filtering parameters
                start_dt = st.session_state.get('start_dt', None)
                end_dt = st.session_state.get('end_dt', None)
                sel = st.session_state.get("sensor_filter", "").strip()
                space_filter_applied = bool(sel)
                
                # **Try to get energy data from database only**
                logger.info("Attempting to retrieve energy data from database")
                energy_data = _get_energy_data_from_database(sensor_id=sel if space_filter_applied else None)
                
                if energy_data:
                    logger.info("SUCCESS Using energy data from database")
                    
                    # Show data source info more concisely
                    building_metadata = energy_data.get('building_metadata', {})
                    simulation_timestamp = building_metadata.get('simulation_timestamp')
                    
                    if simulation_timestamp:
                        st.caption(f"📊 Simulation data from {simulation_timestamp.strftime('%Y-%m-%d %H:%M')}")
                    else:
                        st.caption("📊 Database data")
                        
                else:
                    logger.info("No energy data found in database")
                    st.info("📊 No energy simulation data available in database.")
                    st.info("� Run an energy simulation to generate and store energy data.")
                    energy_data = None
                
                # ==== COMFORT DATA RETRIEVAL (INDEPENDENT OF ENERGY DATA) ====
                # Use the same df_pred DataFrame that contains comfort data (same approach as other tabs)
                comfort_data = df_pred.copy() if not df_pred.empty else None
                
                if comfort_data is not None and len(comfort_data) > 0:
                    logger.info(f"Using comfort data from df_pred: {len(comfort_data)} records")
                    
                    # Apply date filter if specified
                    if start_dt and end_dt:
                        date_mask = (comfort_data["time_end"] >= start_dt) & (comfort_data["time_end"] <= end_dt)
                        comfort_data = comfort_data.loc[date_mask].copy()
                        logger.info(f"Applied date filter: {len(comfort_data)} records remaining")
                    
                    # Apply space filter if specified  
                    if space_filter_applied:
                        space_mask = comfort_data["sensor_id"] == sel
                        comfort_data = comfort_data.loc[space_mask].copy()
                        logger.info(f"Applied space filter: {len(comfort_data)} records remaining")
                
                # Create tabs for different analysis views
                energy_comfort_tabs = st.tabs(["⚡ Energy Timeseries", "🌡️ Comfort Analysis"])
                
                # ==== ENERGY TIMESERIES TAB ====
                with energy_comfort_tabs[0]:
                    st.markdown("### Energy Time Series")
                    
                    if energy_data and ('heating' in energy_data or 'cooling' in energy_data):
                        # Show data source info more concisely
                        building_metadata = energy_data.get('building_metadata', {})
                        simulation_timestamp = building_metadata.get('simulation_timestamp')
                        
                        if simulation_timestamp:
                            st.caption(f"📊 Simulation data from {simulation_timestamp.strftime('%Y-%m-%d %H:%M')}")
                        else:
                            st.caption("📊 Database data")
                        
                        # Initialize variables needed for space filtering at the top level
                        zone_energy = energy_data.get('zone_energy', {})
                        space_names = energy_data.get('space_names', {})
                        filtered_zones = []
                        
                        # Show current filters more concisely
                        col1, col2 = st.columns(2)
                        with col1:
                            if start_dt and end_dt:
                                st.caption(f"📅 {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}")
                            else:
                                st.caption("📅 Full simulation period")
                        
                        with col2:
                            if space_filter_applied:
                                st.caption(f" Space: {sel}")
                            else:
                                st.caption(" All spaces")
                            
                            # Create time series charts for heating and cooling
                            col1, col2 = st.columns(2)
                        
                        # Create time series charts for heating and cooling
                        col1, col2 = st.columns(2)
                        
                        # If space filter is applied, try to match it with zone data
                        if space_filter_applied and zone_energy:
                            # Try to find matching zones
                            for zone_id in zone_energy.keys():
                                zone_id_upper = zone_id.upper()
                                if zone_id_upper in space_names:
                                    space_name = space_names[zone_id_upper]
                                    if sel.lower() in space_name.lower() or sel.lower() in zone_id.lower():
                                        filtered_zones.append(zone_id)
                                elif sel.lower() in zone_id.lower():
                                    filtered_zones.append(zone_id)
                            
                            if filtered_zones:
                                st.info(f"🎯 Found {len(filtered_zones)} zones matching '{sel}': {', '.join(filtered_zones)}")
                            else:
                                st.warning(f"⚠️ No zones found matching '{sel}'. Showing all zones.")
                        
                        # Heating Time Series
                        with col1:
                            st.markdown("### 🔥 Heating Energy Over Time")
                            
                            if 'heating' in energy_data and energy_data['heating'].get('hourly_data'):
                                hourly_heating = energy_data['heating']['hourly_data'][:8760]
                                logger.info(f"Heating timeseries data: {len(hourly_heating)} points")
                                
                                # Create datetime range for the chart
                                if start_dt and end_dt:
                                    chart_start = start_dt
                                    chart_end = end_dt
                                    num_days = (chart_end - chart_start).days + 1
                                    if num_days > 0 and len(hourly_heating) < 8760:
                                        data_points_per_day = max(1, len(hourly_heating) // num_days)
                                        daily_avg = [np.mean(hourly_heating[i:i+data_points_per_day]) for i in range(0, len(hourly_heating), data_points_per_day)]
                                        date_range = pd.date_range(start=chart_start, periods=len(daily_avg), freq='D')
                                    else:
                                        daily_avg = [np.mean(hourly_heating[i:i+24]) for i in range(0, len(hourly_heating), 24)]
                                        date_range = pd.date_range(start=chart_start, periods=len(daily_avg), freq='D')
                                else:
                                    chart_start = pd.Timestamp('2024-01-01')
                                    daily_avg = [np.mean(hourly_heating[i:i+24]) for i in range(0, len(hourly_heating), 24)]
                                    date_range = pd.date_range(start=chart_start, periods=len(daily_avg), freq='D')
                                
                                logger.info(f"Created heating chart data: {len(daily_avg)} daily averages")
                                
                                # Create DataFrame for plotting
                                heating_df = pd.DataFrame({
                                    'Timestamp': date_range,
                                    'Heating_Power_W': [float(x) for x in daily_avg]  # Ensure values are float
                                })
                                
                                logger.info(f"Heating DataFrame shape: {heating_df.shape}")
                                logger.info(f"Heating DataFrame columns: {heating_df.columns.tolist()}")
                                
                                # Create Altair chart
                                heating_chart = alt.Chart(heating_df).mark_line(
                                    point=True, color='red', strokeWidth=2
                                ).add_params(
                                    alt.selection_interval(bind='scales')
                                ).encode(
                                    x=alt.X('Timestamp:T', title='Date', axis=alt.Axis(format='%d %b %Y', labelAngle=-45)),
                                    y=alt.Y('Heating_Power_W:Q', title='Heating Power (W)'),
                                    tooltip=[
                                        alt.Tooltip('Timestamp:T', title='Date', format='%d %b %Y'),
                                        alt.Tooltip('Heating_Power_W:Q', title='Heating Power (W)', format='.1f')
                                    ]
                                ).properties(
                                    width=350,
                                    height=300,
                                    title='Daily Average Heating Power'
                                )
                                
                                st.altair_chart(heating_chart, use_container_width=True)
                                
                                # Show heating stats
                                total_heating = energy_data['heating']['total_energy_kwh']
                                peak_heating = energy_data['heating']['peak_rate_w']
                                st.metric("Total Heating", f"{total_heating:,.1f} kWh")
                                st.metric("Peak Heating", f"{peak_heating:,.0f} W")
                                
                            else:
                                st.info("No heating data available")
                        
                        # Cooling Time Series
                        with col2:
                            st.markdown("### ❄️ Cooling Energy Over Time")
                            
                            if 'cooling' in energy_data and energy_data['cooling'].get('hourly_data'):
                                hourly_cooling = energy_data['cooling']['hourly_data'][:8760]
                                
                                # Create datetime range for the chart
                                if start_dt and end_dt:
                                    chart_start = start_dt
                                    chart_end = end_dt
                                    num_days = (chart_end - chart_start).days + 1
                                    if num_days > 0 and len(hourly_cooling) < 8760:
                                        data_points_per_day = max(1, len(hourly_cooling) // num_days)
                                        daily_avg = [np.mean(hourly_cooling[i:i+data_points_per_day]) for i in range(0, len(hourly_cooling), data_points_per_day)]
                                        date_range = pd.date_range(start=chart_start, periods=len(daily_avg), freq='D')
                                    else:
                                        daily_avg = [np.mean(hourly_cooling[i:i+24]) for i in range(0, len(hourly_cooling), 24)]
                                        date_range = pd.date_range(start=chart_start, periods=len(daily_avg), freq='D')
                                else:
                                    chart_start = pd.Timestamp('2024-01-01')
                                    daily_avg = [np.mean(hourly_cooling[i:i+24]) for i in range(0, len(hourly_cooling), 24)]
                                    date_range = pd.date_range(start=chart_start, periods=len(daily_avg), freq='D')
                                
                                # Create DataFrame for plotting
                                cooling_df = pd.DataFrame({
                                    'Timestamp': date_range,
                                    'Cooling_Power_W': [float(x) for x in daily_avg]  # Ensure values are float
                                })
                                
                                # Create Altair chart
                                cooling_chart = alt.Chart(cooling_df).mark_line(
                                    point=True, color='blue', strokeWidth=2
                                ).add_params(
                                    alt.selection_interval(bind='scales')
                                ).encode(
                                    x=alt.X('Timestamp:T', title='Date', axis=alt.Axis(format='%d %b %Y', labelAngle=-45)),
                                    y=alt.Y('Cooling_Power_W:Q', title='Cooling Power (W)'),
                                    tooltip=[
                                        alt.Tooltip('Timestamp:T', title='Date', format='%d %b %Y'),
                                        alt.Tooltip('Cooling_Power_W:Q', title='Cooling Power (W)', format='.1f')
                                    ]
                                ).properties(
                                    width=350,
                                    height=300,
                                    title='Daily Average Cooling Power'
                                )
                                
                                st.altair_chart(cooling_chart, use_container_width=True)
                                
                                # Show cooling stats
                                total_cooling = energy_data['cooling']['total_energy_kwh']
                                peak_cooling = energy_data['cooling']['peak_rate_w']
                                st.metric("Total Cooling", f"{total_cooling:,.1f} kWh")
                                st.metric("Peak Cooling", f"{peak_cooling:,.0f} W")
                                
                            else:
                                st.info("No cooling data available")
                        
                        # Combined Analysis
                        if 'heating' in energy_data and 'cooling' in energy_data:
                            st.subheader("⚙️ Combined Energy Analysis")
                            
                            # Calculate energy balance
                            total_heating = energy_data['heating']['total_energy_kwh']
                            total_cooling = energy_data['cooling']['total_energy_kwh']
                            total_energy = total_heating + total_cooling
                            
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Total Energy", f"{total_energy:,.1f} kWh")
                            with col2:
                                heating_ratio = (total_heating / total_energy * 100) if total_energy > 0 else 0
                                st.metric("Heating Share", f"{heating_ratio:.1f}%")
                            with col3:
                                cooling_ratio = (total_cooling / total_energy * 100) if total_energy > 0 else 0
                                st.metric("Cooling Share", f"{cooling_ratio:.1f}%")
                            
                            # Combined time series chart
                            if energy_data['heating'].get('hourly_data') and energy_data['cooling'].get('hourly_data'):
                                st.markdown("### 🔥❄️ Combined Heating & Cooling")
                                
                                # Prepare data for combined chart
                                hourly_heating = energy_data['heating']['hourly_data'][:8760]
                                hourly_cooling = energy_data['cooling']['hourly_data'][:8760]
                                
                                # Create datetime range
                                if start_dt and end_dt:
                                    chart_start = start_dt
                                    num_days = (end_dt - start_dt).days + 1
                                    if num_days > 0 and len(hourly_heating) < 8760:
                                        data_points_per_day = max(1, len(hourly_heating) // num_days)
                                        heating_daily = [np.mean(hourly_heating[i:i+data_points_per_day]) for i in range(0, len(hourly_heating), data_points_per_day)]
                                        cooling_daily = [np.mean(hourly_cooling[i:i+data_points_per_day]) for i in range(0, len(hourly_cooling), data_points_per_day)]
                                        date_range = pd.date_range(start=chart_start, periods=len(heating_daily), freq='D')
                                    else:
                                        heating_daily = [np.mean(hourly_heating[i:i+24]) for i in range(0, len(hourly_heating), 24)]
                                        cooling_daily = [np.mean(hourly_cooling[i:i+24]) for i in range(0, len(hourly_cooling), 24)]
                                        date_range = pd.date_range(start=chart_start, periods=len(heating_daily), freq='D')
                                else:
                                    chart_start = pd.Timestamp('2024-01-01')
                                    heating_daily = [np.mean(hourly_heating[i:i+24]) for i in range(0, len(hourly_heating), 24)]
                                    cooling_daily = [np.mean(hourly_cooling[i:i+24]) for i in range(0, len(hourly_cooling), 24)]
                                    date_range = pd.date_range(start=chart_start, periods=len(heating_daily), freq='D')
                                
                                # Create combined DataFrame
                                combined_data = []
                                for i, timestamp in enumerate(date_range):
                                    if i < len(heating_daily):
                                        combined_data.append({'Timestamp': timestamp, 'Energy_W': float(heating_daily[i]), 'Type': 'Heating'})
                                    if i < len(cooling_daily):
                                        combined_data.append({'Timestamp': timestamp, 'Energy_W': float(cooling_daily[i]), 'Type': 'Cooling'})
                                
                                combined_df = pd.DataFrame(combined_data)
                                
                                # Create combined chart
                                combined_chart = alt.Chart(combined_df).mark_line(
                                    point=True, strokeWidth=2
                                ).add_params(
                                    alt.selection_interval(bind='scales')
                                ).encode(
                                    x=alt.X('Timestamp:T', title='Date', axis=alt.Axis(format='%d %b %Y', labelAngle=-45)),
                                    y=alt.Y('Energy_W:Q', title='Power (W)'),
                                    color=alt.Color('Type:N', scale=alt.Scale(domain=['Heating', 'Cooling'], range=['red', 'blue'])),
                                    tooltip=[
                                        alt.Tooltip('Timestamp:T', title='Date', format='%d %b %Y'),
                                        alt.Tooltip('Energy_W:Q', title='Power (W)', format='.1f'),
                                        alt.Tooltip('Type:N', title='Energy Type')
                                    ]
                                ).properties(
                                    width=700,
                                    height=400,
                                    title='Daily Average Heating & Cooling Power Comparison'
                                )
                                
                                st.altair_chart(combined_chart, use_container_width=True)
                        
                        # Space-specific filtering results
                        if space_filter_applied and filtered_zones and zone_energy:
                            st.subheader(f" Space-Specific Analysis: {sel}")
                            
                            # Calculate totals for filtered zones
                            filtered_heating = sum(zone_energy[zone].get('heating_kwh', 0) for zone in filtered_zones)
                            filtered_cooling = sum(zone_energy[zone].get('cooling_kwh', 0) for zone in filtered_zones)
                            filtered_total = filtered_heating + filtered_cooling
                            
                            if filtered_total > 0:
                                col1, col2, col3 = st.columns(3)
                                with col1:
                                    st.metric(f"{sel} - Total Energy", f"{filtered_total:,.1f} kWh")
                                with col2:
                                    st.metric(f"{sel} - Heating", f"{filtered_heating:,.1f} kWh")
                                with col3:
                                    st.metric(f"{sel} - Cooling", f"{filtered_cooling:,.1f} kWh")
                                
                                # Show percentage of total building energy
                                total_building_energy = total_heating + total_cooling
                                if total_building_energy > 0:
                                    space_percentage = (filtered_total / total_building_energy) * 100
                                    st.info(f"📊 **{sel}** accounts for **{space_percentage:.1f}%** of total building energy consumption")
                            else:
                                st.warning(f"No energy data found for spaces matching '{sel}'")
                    
                    else:
                        st.info("ℹ️ No energy simulation data available in database.")
                        st.info("💡 Run an energy simulation to generate and store energy data.")
                        st.markdown("""
                        **To generate energy data:**
                        1. Go to the **Energy** tab
                        2. Upload an IFC building model file
                        3. Generate weather data for your location
                        4. Run an EnergyPlus simulation
                        5. Return here to analyze the energy patterns
                        """)
                
                # ==== COMFORT ANALYSIS TAB ====
                with energy_comfort_tabs[1]:
                            logger.info("Entering Comfort Analysis tab")
                            st.subheader("🌡️ Comfort Analysis")
                            
                            if comfort_data is not None and len(comfort_data) > 0:
                                logger.info(f"Processing comfort data with {len(comfort_data)} records")
                                
                                # *** CRITICAL PERFORMANCE FIX ***
                                # Sample large datasets to prevent browser hanging
                                # SAMPLE_SIZE = 50000  # Maximum records to display
                                # if len(comfort_data) > SAMPLE_SIZE:
                                #     logger.warning(f"Large dataset detected ({len(comfort_data)} records). Sampling to {SAMPLE_SIZE} records for visualization.")
                                #     st.warning(f"WARNING **Large dataset detected!** Showing a representative sample of {SAMPLE_SIZE:,} records out of {len(comfort_data):,} total records.")
                                    
                                #     # Use systematic sampling to maintain temporal distribution
                                #     step = len(comfort_data) // SAMPLE_SIZE
                                #     comfort_data_display = comfort_data.iloc[::step].copy()
                                #     logger.info(f"Sampled dataset: {len(comfort_data_display)} records (every {step}th record)")
                                # else:
                                #     comfort_data_display = comfort_data.copy()
                                
                                # Use full dataset for now (sampling logic commented out)
                                comfort_data_display = comfort_data.copy()
                                
                                # PMV/PPD Overview with Overall Comfort
                                col1, col2, col3, col4, col5 = st.columns(5)
                                
                                logger.info("Calculating PMV/PPD metrics...")
                                with col1:
                                    avg_pmv = comfort_data['PMV_pred'].mean() if 'PMV_pred' in comfort_data.columns else 0
                                    st.metric("Average PMV", f"{avg_pmv:.2f}")
                                
                                with col2:
                                    avg_ppd = comfort_data['PPD_pred'].mean() if 'PPD_pred' in comfort_data.columns else 0
                                    st.metric("Average PPD", f"{avg_ppd:.1f}%")
                                
                                logger.info("Calculating overall comfort metric...")
                                with col3:
                                    # Use overall_comfort from database if available, otherwise calculate it
                                    if 'overall_comfort' in comfort_data.columns and comfort_data['overall_comfort'].notna().any():
                                        avg_overall = comfort_data['overall_comfort'].mean()
                                    else:
                                        # Fallback: calculate on the fly if not in database
                                        logger.info("Calculating overall comfort on-the-fly (this may take a moment for large datasets)...")
                                        temp_df = comfort_data_display.copy()  # Use sampled data for calculation
                                        temp_df['overall_comfort'] = _calculate_overall_comfort(temp_df)
                                        avg_overall = temp_df['overall_comfort'].mean() if temp_df['overall_comfort'].notna().any() else 0
                                    st.metric("Overall Comfort", f"{avg_overall:.2f}", help="Weighted average of all comfort metrics (scale: 0-4, where 4 is best)")
                                
                                logger.info("Calculating visual and acoustic comfort metrics...")
                                with col4:
                                    comfort_score = comfort_data['vis_score_pred'].mean() if 'vis_score_pred' in comfort_data.columns else 0
                                    st.metric("Visual Comfort", f"{comfort_score:.2f}")
                                
                                with col5:
                                    annoyance_level = comfort_data['annoy_pred'].mean() if 'annoy_pred' in comfort_data.columns else 0
                                    st.metric("Acoustic Annoyance", f"{annoyance_level:.2f}")
                                
                                # Comfort Classes Distribution
                                logger.info("Starting comfort classes distribution analysis...")
                                st.markdown("### 🏷️ Comfort Classes Distribution")
                                
                                # Overall Comfort Class (displayed prominently)
                                if 'overall_comfort_class' in comfort_data.columns:
                                    logger.info("Creating overall comfort class pie chart...")
                                    st.markdown("#### 🎯 Overall Comfort Class")
                                    _pie_chart(comfort_data_display, 'overall_comfort_class', title="Overall Comfort Distribution", context="comfort_analysis")
                                    logger.info("Overall comfort class pie chart completed")
                                    st.markdown("---")
                                
                                logger.info("Processing primary comfort classes...")
                                comfort_class_cols = ['thermal_class', 'visual_class', 'acoustic_class']
                                available_comfort_cols = [col for col in comfort_class_cols if col in comfort_data.columns]
                                logger.info(f"Available primary comfort columns: {available_comfort_cols}")
                                
                                if available_comfort_cols:
                                    st.markdown("#### 🌡️ Primary Comfort Classes")
                                    pie_cols = st.columns(len(available_comfort_cols))
                                    for idx, class_col in enumerate(available_comfort_cols):
                                        logger.info(f"Creating pie chart for {class_col}...")
                                        with pie_cols[idx]:
                                            _pie_chart(comfort_data_display, class_col, title=DISPLAY.get(class_col, class_col.replace('_', ' ').title()), context="comfort_analysis")
                                        logger.info(f"Completed pie chart for {class_col}")
                                
                                # IAQ Comfort Classes
                                logger.info("Processing IAQ comfort classes...")
                                st.markdown("### 🌬️ Indoor Air Quality Comfort")
                                
                                iaq_comfort_cols = ['co2_comfort_class', 'co_comfort_class', 'tvoc_comfort_class', 'pm25_comfort_class', 'pm10_comfort_class']
                                available_iaq_cols = [col for col in iaq_comfort_cols if col in comfort_data.columns]
                                logger.info(f"Available IAQ comfort columns: {available_iaq_cols}")
                                
                                if available_iaq_cols:
                                    logger.info("Creating IAQ pie charts...")
                                    iaq_pie_cols = st.columns(min(3, len(available_iaq_cols)))
                                    for idx, class_col in enumerate(available_iaq_cols[:3]):  # Show first 3
                                        logger.info(f"Creating IAQ pie chart for {class_col}...")
                                        with iaq_pie_cols[idx % 3]:
                                            _pie_chart(comfort_data_display, class_col, title=DISPLAY.get(class_col, class_col.replace('_', ' ').title()), context="comfort_analysis")
                                        logger.info(f"Completed IAQ pie chart for {class_col}")
                                    
                                    # Second row if more than 3
                                    if len(available_iaq_cols) > 3:
                                        logger.info("Creating second row of IAQ pie charts...")
                                        iaq_pie_cols2 = st.columns(len(available_iaq_cols) - 3)
                                        for idx, class_col in enumerate(available_iaq_cols[3:]):
                                            with iaq_pie_cols2[idx]:
                                                _pie_chart(comfort_data_display, class_col, title=DISPLAY.get(class_col, class_col.replace('_', ' ').title()), context="comfort_analysis")
                                
                                # Comfort Time Series
                                st.markdown("### � Comfort Time Series")
                                
                                # Overall Comfort Time Series
                                if 'overall_comfort' in comfort_data.columns and comfort_data['overall_comfort'].notna().any():
                                    logger.info("Creating overall comfort time series chart...")
                                    st.markdown("#### 🎯 Overall Comfort Over Time")
                                    
                                    logger.info("Preparing overall comfort data for charting...")
                                    # Use sampled data for time series charts
                                    chart_data = comfort_data_display[comfort_data_display['overall_comfort'].notna()].copy()
                                    
                                    if len(chart_data) > 0:
                                        logger.info(f"Creating overall comfort DataFrame with {len(chart_data)} data points...")
                                        
                                        # Prepare data for chart - simplified approach
                                        chart_data = chart_data[['time_end', 'overall_comfort']].rename(columns={
                                            'time_end': 'Timestamp',
                                            'overall_comfort': 'Overall_Comfort'
                                        })
                                        
                                        logger.info("Creating overall comfort Altair chart...")
                                        overall_chart = alt.Chart(chart_data).mark_line(
                                            point=True, strokeWidth=3, color='#2E8B57'
                                        ).add_params(
                                            alt.selection_interval(bind='scales')
                                        ).encode(
                                            x=alt.X('Timestamp:T', title='Time', axis=alt.Axis(format='%d %b %Y', labelAngle=-45)),
                                            y=alt.Y('Overall_Comfort:Q', title='Overall Comfort Score', scale=alt.Scale(domain=[0, 4])),
                                            tooltip=[
                                                alt.Tooltip('Timestamp:T', title='Time', format='%d %b %Y %H:%M'),
                                                alt.Tooltip('Overall_Comfort:Q', title='Overall Comfort', format='.2f')
                                            ]
                                        ).properties(
                                            width=700,
                                            height=300,
                                            title='Overall Comfort Score Over Time (Scale: 0-4, where 4 is best)'
                                        )
                                        
                                        logger.info("Displaying overall comfort chart...")
                                        st.altair_chart(overall_chart, use_container_width=True)
                                        logger.info("Overall comfort chart displayed successfully")
                                        
                                        # Show interpretation
                                        avg_comfort = comfort_data['overall_comfort'].mean()
                                        if avg_comfort >= 3.5:
                                            st.success(f"COMPLETE **Excellent overall comfort** (Average: {avg_comfort:.2f}/4)")
                                        elif avg_comfort >= 2.5:
                                            st.info(f"👍 **Good overall comfort** (Average: {avg_comfort:.2f}/4)")
                                        elif avg_comfort >= 1.5:
                                            st.warning(f"WARNING **Moderate overall comfort** (Average: {avg_comfort:.2f}/4)")
                                        else:
                                            st.error(f"ERROR **Poor overall comfort** (Average: {avg_comfort:.2f}/4)")
                                        
                                        # Export button for overall comfort data
                                        csv_bytes = chart_data.to_csv(index=False).encode("utf-8")
                                        st.download_button(
                                            "Export Overall Comfort CSV",
                                            data=csv_bytes,
                                            file_name=f"overall_comfort_{datetime.now(tz=timezone.utc):%Y%m%dT%H%M%S}.csv",
                                            mime="text/csv",
                                            type="secondary",
                                            key="csv_overall_comfort",
                                        )
                                else:
                                    st.info("ℹ️ Overall Comfort data not available. Run new predictions to generate this metric.")
                                
                                # PMV/PPD Time Series
                                if 'PMV_pred' in comfort_data.columns and 'PPD_pred' in comfort_data.columns:
                                    logger.info("Creating PMV & PPD time series chart...")
                                    st.markdown("#### 🌡️ PMV & PPD Over Time")
                                    
                                    logger.info("Preparing PMV/PPD data for charting...")
                                    # Use sampled data and vectorized approach
                                    chart_data = comfort_data_display[['time_end', 'PMV_pred', 'PPD_pred']].dropna()
                                    
                                    if len(chart_data) > 0:
                                        logger.info(f"Creating PMV/PPD DataFrame with {len(chart_data)} data points...")
                                        
                                        # Melt the data for easier plotting
                                        pmv_ppd_df = pd.melt(
                                            chart_data,
                                            id_vars=['time_end'],
                                            value_vars=['PMV_pred', 'PPD_pred'],
                                            var_name='Metric',
                                            value_name='Value'
                                        )
                                        pmv_ppd_df['Metric'] = pmv_ppd_df['Metric'].map({
                                            'PMV_pred': 'PMV',
                                            'PPD_pred': 'PPD (%)'
                                        })
                                        pmv_ppd_df = pmv_ppd_df.rename(columns={'time_end': 'Timestamp'})
                                        
                                        logger.info("Creating PMV/PPD Altair chart...")
                                        pmv_ppd_chart = alt.Chart(pmv_ppd_df).mark_line(
                                            point=True, strokeWidth=2
                                        ).add_params(
                                            alt.selection_interval(bind='scales')
                                        ).encode(
                                            x=alt.X('Timestamp:T', title='Time', axis=alt.Axis(format='%d %b %Y', labelAngle=-45)),
                                            y=alt.Y('Value:Q', title='Value'),
                                            color=alt.Color('Metric:N', scale=alt.Scale(domain=['PMV', 'PPD (%)'], range=['blue', 'red'])),
                                            tooltip=[
                                                alt.Tooltip('Timestamp:T', title='Time', format='%d %b %Y %H:%M'),
                                            alt.Tooltip('Value:Q', title='Value', format='.2f'),
                                            alt.Tooltip('Metric:N', title='Metric')
                                            ]
                                        ).properties(
                                            width=700,
                                            height=300,
                                            title='PMV and PPD Over Time'
                                        ).resolve_scale(
                                            y='independent'
                                        )
                                        
                                        logger.info("Displaying PMV/PPD chart...")
                                        st.altair_chart(pmv_ppd_chart, use_container_width=True)
                                        logger.info("PMV/PPD chart displayed successfully")
                                else:
                                    st.info("ℹ️ No PMV/PPD data available for visualization.")
                                    
                                # Comfort Class Time Series
                                logger.info("Preparing comfort class time series...")
                                comfort_class_timeseries_cols = [col for col in comfort_class_cols if col in comfort_data.columns]
                                
                                # Add overall comfort class if available
                                if 'overall_comfort_class' in comfort_data.columns:
                                    comfort_class_timeseries_cols.append('overall_comfort_class')
                                    
                                logger.info(f"Available comfort class timeseries columns: {comfort_class_timeseries_cols}")
                                
                                if comfort_class_timeseries_cols:
                                    logger.info("Creating comfort class time series...")
                                    st.markdown("#### 🏷️ Comfort Classes Over Time")
                                    _class_timeseries(comfort_data_display, comfort_class_timeseries_cols, title="Comfort Classes Over Time")
                                    logger.info("Comfort class time series completed")
                                
                                logger.info("Comfort Analysis tab processing completed successfully")
                            
                            else:
                                logger.info("No comfort data available for analysis")
                                st.info("ℹ️ No comfort data available. Run predictions to generate comfort analysis.")
                
            elif name == 'IAQ':
                # --- pie-chart
                iaq_fields = [
                    "co2_ppm_class", "co_ppm_class", "tvoc_ppb_class",
                    "pm10_ugm3_class", "pm2_5_ugm3_class",
                ]
                iaq_active = [col for col in iaq_fields if col in df_pred ]
                if len(iaq_active):
                    # add columns
                    pie_cols = st.columns(len(iaq_active))
                    # keep a running index so we know when to start a new row
                    for idx, class_col in enumerate(iaq_active):
                        target = pie_cols[idx]

                        # render the pie for this IAQ metric inside that placeholder
                        with target:
                            _pie_chart(df_pred, class_col, title=DISPLAY.get(class_col, class_col), context="iaq")
                    st.markdown("-- IAQ Report --" + DUMMY_TEXT)
            else:
                # single pie for Thermal / Visual / Acoustic
                pie_cols = st.columns([1, 3], gap="small")
                class_col = f"{name.lower()}_class"
                if class_col in df_pred.columns:
                    with pie_cols[0]:
                        _pie_chart(df_pred, class_col, title=f"{name} class", context=name.lower())
                    with pie_cols[1]:
                        st.markdown(f"-- {name} Report --" + "\n" + DUMMY_TEXT)
                    logger.info("Rendered %s pie for column %s", name, class_col)
                else:
                    logger.warning("No class column %s – pie skipped", class_col)
            
            # ------- class time-series immediately below pies ------------
            if name == "Energy Comfortness":
                # Skip timeseries for Energy Comfortness tab
                pass
            elif name == "IAQ":
                iaq_class_cols = [
                    c for c in [
                        "co2_ppm_class", "co_ppm_class", "tvoc_ppb_class",
                        "pm10_ugm3_class", "pm2_5_ugm3_class",
                    ] if c in df_pred.columns
                ]
                _class_timeseries(df_pred, iaq_class_cols, title="IAQ class")
            else:
                single_class_col = f"{name.lower()}_class"
                if single_class_col in df_pred.columns:
                    _class_timeseries(df_pred, [single_class_col], title=f"{name} class")              
            
            # now plot line charts
            if name != "Energy Comfortness":  # Skip line charts for Energy Comfortness
                for tgt in domain_map[name]:
                    if tgt.endswith("_pred"):                       # comfort metrics
                        if tgt in df_pred.columns:
                            _line_chart(df_pred, obs=None, pred=tgt)
                        else:
                            st.info(f"No data for {DISPLAY.get(tgt, tgt)}")
                    else:                                           # regular measurement
                        obs_col, pred_col = tgt, f"pred_{tgt}"
                        if pred_col in df_pred.columns:
                            # Check if we have observations for this target
                            obs_available = obs_col in df_pred.columns and not df_pred[obs_col].isna().all()
                            if obs_available:
                                _line_chart(df_pred, obs_col, pred_col)
                            else:
                                _line_chart(df_pred, obs=None, pred=pred_col)
                        else:
                            st.info(f"No prediction data for {DISPLAY.get(tgt, tgt)}")
                
else:
    st.title("Energy Comfortness Tool ")
    st.info("Run predictions to see results.")
