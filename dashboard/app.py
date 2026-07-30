"""Streamlit dashboard for the Energy Comfortness Tool (ECT)."""

from __future__ import annotations

# versioning
from __version__ import __version__ as _VERSION

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
from db.models import Measurement, Weather, Prediction, TrainedModel, EnergyBuilding, EnergySpace, EnergyTimeSeries, Space  # type: ignore[attr-defined]
from ece.pipeline_ml import main_train_all_targets  # type: ignore
from ece.feature_map import MAP as FEATURE_MAP, TIME_DRIVERS
from ece.weather_api import fetch_open_meteo
from ece.pipeline_weather import generate_epw_for_location  # type: ignore
from ece.pipeline_eplus_wrapper import run_eplus_simulation_async, test_bim2sim_environment, run_user_request  # type: ignore

def _get_default_ifc_path() -> Optional[Path]:
    """Dynamically find the first available .ifc file under etc/ifc/* subdirectories."""
    etc_ifc_dir = Path(__file__).parent.parent / "etc" / "ifc"
    if etc_ifc_dir.exists():
        for b_folder in sorted([d for d in etc_ifc_dir.iterdir() if d.is_dir()]):
            ifc_files = list(b_folder.glob("*.ifc"))
            if ifc_files:
                return ifc_files[0]
    return None

DEFAULT_IFC_PATH = _get_default_ifc_path()


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


def _store_energy_simulation_results(simulation_results: dict, space_id: str, 
                                   ifc_file_path: str, epw_file_path: str, end_date: Optional[Any] = None) -> bool:
    """
    Store energy simulation results in the database with timestamped energy data.
    
    Args:
        simulation_results: Dictionary containing simulation results from EnergyPlus
        space_id: Space identifier that triggered the simulation
        ifc_file_path: Path to the IFC file used
        epw_file_path: Path to the EPW weather file used
        
    Returns:
        bool: True if storage was successful, False otherwise
    """
    logger.info(f"Storing energy simulation results for space: {space_id}")
    logger.debug(f"Simulation results keys: {list(simulation_results.keys())}")
    logger.debug(f"Simulation results structure: {simulation_results}")
    
    try:
        with SessionLocal() as session:
            # Get building_id from the Space table
            space_record = session.query(Space).filter(Space.space_id == space_id).first()
            
            if not space_record:
                logger.warning(f"Space {space_id} not found in database, creating default entry")
                # Use standard default coordinates and building ID
                lat = 40.6401
                lon = 22.9444
                default_building_id = f"building_{space_id}"
                
                # Create a default space if it doesn't exist
                space_record = Space(
                    space_id=space_id,
                    building_id=default_building_id,
                    latitude=lat,
                    longitude=lon
                )
                session.add(space_record)
                session.flush()
                logger.debug(f"Created space record for {space_id} with building_id: {space_record.building_id}")
            
            building_id = space_record.building_id
            logger.info(f"Using building_id: {building_id} for space: {space_id}")
            
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
                        logger.debug(f"Found EnergyPlus results directory: {actual_results_dir}")
                    else:
                        logger.exception(f"No result directories found in: {export_dir}")
                        return False
                else:
                    logger.exception(f"Export directory not found: {export_dir}")
                    return False
            else:
                logger.exception(f"Neither 'eplus_results_path' nor 'project_path' found in simulation_results. Available keys: {list(simulation_results.keys())}")
                return False
            
            energy_data = _parse_energyplus_outputs(actual_results_dir)
            
            if not energy_data or ('heating' not in energy_data and 'cooling' not in energy_data):
                logger.warning("No energy data available to store")
                return False
            
            # Extract simulation metadata
            simulation_timestamp = datetime.now()
            
            # Extract target end date limit from end_date parameter
            target_end_dt = end_date
            if target_end_dt:
                if not isinstance(target_end_dt, datetime) and hasattr(target_end_dt, 'year'):
                    target_end_dt = datetime.combine(target_end_dt, datetime.max.time())
                elif hasattr(target_end_dt, 'tzinfo') and target_end_dt.tzinfo is not None:
                    target_end_dt = target_end_dt.replace(tzinfo=None)

            # Use actual parsed simulation timestamps if available, otherwise fallback to EPW year
            if energy_data.get('timestamps') and len(energy_data['timestamps']) > 0:
                timestamps = [ts for ts in energy_data['timestamps'] if pd.notna(ts)]
                
                # Truncate timestamps and series to target_end_dt if specified
                if target_end_dt and timestamps:
                    timestamps = [ts for ts in timestamps if ts <= target_end_dt]
                    logger.info(f"Truncated simulation timestamps to target end date {target_end_dt}: {len(timestamps)} points remaining")

                if timestamps:
                    simulation_start = timestamps[0]
                    simulation_end = timestamps[-1]
                    logger.info(f"Using parsed simulation date range: {simulation_start} to {simulation_end}")
                else:
                    simulation_year = _get_simulation_year_from_epw(actual_results_dir) or 2024
                    simulation_start = datetime(simulation_year, 1, 1)
                    simulation_end = datetime(simulation_year, 12, 31)
            else:
                simulation_year = _get_simulation_year_from_epw(actual_results_dir) or 2024
                simulation_start = datetime(simulation_year, 1, 1)
                simulation_end = datetime(simulation_year, 12, 31)
                logger.info(f"Fallback to simulation period: {simulation_start} to {simulation_end}")
            
            # Prepare time series data
            heating_timeseries = energy_data.get('heating', {}).get('hourly_data', [])
            cooling_timeseries = energy_data.get('cooling', {}).get('hourly_data', [])
            
            if energy_data.get('timestamps') and len(energy_data['timestamps']) > len(timestamps):
                limit_len = len(timestamps)
                heating_timeseries = heating_timeseries[:limit_len]
                cooling_timeseries = cooling_timeseries[:limit_len]

            # Calculate building-level totals from (possibly truncated) timeseries data
            total_heating_kwh = sum(heating_timeseries) if heating_timeseries else energy_data.get('heating', {}).get('total_energy_kwh', 0)
            total_cooling_kwh = sum(cooling_timeseries) if cooling_timeseries else energy_data.get('cooling', {}).get('total_energy_kwh', 0)
            total_energy_kwh = total_heating_kwh + total_cooling_kwh
            
            peak_heating_w = max(heating_timeseries) * 1000.0 if heating_timeseries else energy_data.get('heating', {}).get('peak_rate_w', 0)
            peak_cooling_w = max(cooling_timeseries) * 1000.0 if cooling_timeseries else energy_data.get('cooling', {}).get('peak_rate_w', 0)
            
            zone_energy = energy_data.get('zone_energy', {})
            zones_count = len(zone_energy)
            
            # Get file paths from simulation results or use the function parameters as fallback
            weather_file_path = simulation_results.get('weather_file', epw_file_path)
            ifc_file_path_from_results = simulation_results.get('ifc_file', ifc_file_path)
            
            # Create EnergyBuilding record with building_id
            energy_building = EnergyBuilding(
                building_id=building_id,  # Add the building_id from space record
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
            
            logger.debug(f"Created EnergyBuilding record with ID: {energy_building.energy_building_id}")
            
            # Create EnergySpace records and timestamped data for each zone
            space_names = energy_data.get('space_names', {})
            spaces_created = 0
            spaces_skipped = 0
            timeseries_points_created = 0
            
            # Use already truncated timestamps if available
            if timestamps and len(timestamps) > 0:
                logger.info(f"Using {len(timestamps)} truncated simulation timestamps from {timestamps[0]} to {timestamps[-1]}")
            else:
                num_data_points = max(len(heating_timeseries), len(cooling_timeseries))
                if num_data_points > 0:
                    timestamps = [simulation_start + timedelta(hours=i) for i in range(num_data_points)]
                    logger.debug(f"Creating {num_data_points} hourly timestamped data points from {timestamps[0]} to {timestamps[-1]}")
                else:
                    timestamps = []
                    logger.warning("No time series data available for timestamp creation")
            
            for zone_id, zone_data in zone_energy.items():
                # Get zone name from space mapping (case-insensitive lookup)
                zone_name = space_names.get(zone_id.upper(), zone_id)
                
                logger.debug(f"Processing zone: '{zone_id}' -> '{zone_name}'")
                
                # Check if this space exists in the spaces table before storing energy data
                existing_space = session.query(Space).filter(Space.space_id == zone_name).first()
                if not existing_space:
                    logger.warning(f"SKIPPING: energy storage for zone '{zone_name}' - space not found in spaces table. Upload CSV data containing this space_id first.")
                    spaces_skipped += 1
                    continue
                
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
                    energy_building_id=energy_building.energy_building_id,  # Fix: use energy_building_id not building_id
                    space_id=zone_name,  # Use zone_name as space_id to match measurements tab naming
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
                
                logger.debug(f"   Created EnergySpace record with ID: {energy_space.space_id}")
                
                # Create timestamped energy data for this zone
                heating_series = zone_data.get('heating_timeseries', [])
                cooling_series = zone_data.get('cooling_timeseries', [])
                
                logger.info(f"   🕐 Timeseries check: heating={len(heating_series)} points, cooling={len(cooling_series)} points, timestamps={len(timestamps)}")
                
                if timestamps and heating_series and cooling_series:
                    # Ensure we have data to work with
                    max_points = min(len(timestamps), len(heating_series), len(cooling_series))
                    logger.info(f"   Creating {max_points} time series points for zone {zone_id}")
                    
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
                            'energy_space_id': energy_space.energy_space_id,  # Fix: use energy_space_id not space_id
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
            logger.info(f"   - Zones skipped (no matching space): {spaces_skipped}")
            logger.info(f"   - Time series points stored: {timeseries_points_created}")
            logger.info(f"   - Results path: {actual_results_dir}")
            
            return True
            
    except Exception as e:
        logger.exception(f"ERROR Error storing energy simulation results: {str(e)}", exc_info=True)
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
        # Check space.csv inside results_dir directly or export_dir
        results_dir = Path(eplus_results_path)
        space_csv_path = results_dir / "space.csv"
        if not space_csv_path.exists():
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
        logger.exception(f"Error loading space names from CSV: {e}", exc_info=True)
        return {}


def _get_energy_data_from_database(space_id: Optional[str] = None, building_id: Optional[str] = None, limit: int = 1) -> Optional[dict]:
    """
    Retrieve energy simulation data from the database.
    
    Args:
        space_id: Optional space ID to filter by
        building_id: Optional building ID to filter by
        limit: Number of records to retrieve (default 1 for latest)
        
    Returns:
        Dictionary containing energy data in visualization format, or None
    """
    logger.info(f"Retrieving energy data from database for building: {building_id or 'any'}, space: {space_id or 'any'}")
    
    try:
        with SessionLocal() as session:
            # Get date range from session state if available
            start_dt = st.session_state.get('start_dt')
            end_dt = st.session_state.get('end_dt')
            
            # Query for energy buildings - filter by building_id if provided or derived from space_id
            target_building_id = building_id
            if not target_building_id and space_id:
                space_rec = session.query(Space).filter(Space.space_id == space_id).first()
                if space_rec:
                    target_building_id = space_rec.building_id
            
            buildings_query = session.query(EnergyBuilding)
            if target_building_id:
                buildings_query = buildings_query.filter(EnergyBuilding.building_id == target_building_id)
            
            buildings = buildings_query.order_by(EnergyBuilding.simulation_timestamp.desc()).all()
            
            if not buildings:
                logger.info("No energy simulation data found in database")
                return None
            
            # Find the building that has data in the selected date range
            selected_building = None
            for building in buildings:
                # Get spaces for this building
                spaces = session.query(EnergySpace).filter_by(energy_building_id=building.energy_building_id).all()
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
                        data_count = session.query(EnergyTimeSeries).join(EnergySpace).filter(
                            EnergySpace.space_id.in_(space_ids),
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
                EnergySpace.energy_building_id == building.energy_building_id
            )
            
            # If a specific space_id is selected (not "latest"), filter to only that space
            if space_id and space_id != "latest":
                spaces_query = spaces_query.filter(EnergySpace.space_id == space_id)
                logger.info(f"Filtering to space(s) for specific space: {space_id}")
            
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
            if space_id and space_id != "latest":
                if len(valid_spaces) == 1:
                    space_name = space_names_from_csv.get(valid_spaces[0].zone_id.upper(), valid_spaces[0].zone_id)
                    logger.info(f"📍 Showing energy data for specific space: '{space_name}' (space: {space_id})")
                elif len(valid_spaces) == 0:
                    logger.warning(f"ERROR No spaces found for space {space_id}")
                else:
                    logger.info(f"📍 Showing energy data for {len(valid_spaces)} spaces matching space: {space_id}")
            else:
                logger.info(f"DATA Showing energy data for all {len(valid_spaces)} spaces in building")
            
            # Initialize filtered totals - will be recalculated from space data if date filtering is applied
            # For specific space selection, start with 0 and accumulate only from selected spaces
            if space_id and space_id != "latest":
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
                    # Join through EnergySpace to filter by building
                    timestamps_query = session.query(EnergyTimeSeries.timestamp).join(EnergySpace).filter(
                        EnergySpace.energy_building_id == building.energy_building_id
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
                    'selected_space_id': space_id if is_space_specific else None
                }
            }
            
            # Add space-level data (only for valid spaces)
            space_heating_timeseries = []  # Accumulate heating timeseries for space-specific view
            space_cooling_timeseries = []  # Accumulate cooling timeseries for space-specific view
            
            for space in valid_spaces:
                zone_id = space.zone_id
                
                # Get timestamped data for this space
                timeseries_query = session.query(EnergyTimeSeries).filter(
                    EnergyTimeSeries.energy_space_id == space.energy_space_id
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
                if (is_date_filtered or is_space_specific) and (heating_timeseries or cooling_timeseries):
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
                    'space_id': space.space_id,  # Include sensor association
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
                        ).join(EnergySpace).filter(EnergySpace.space_id.in_(space_ids)).first()
                        
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
                logger.info(f"   - Selected space: {space_id}")
            
            return energy_data
            
    except Exception as e:
        logger.exception(f"ERROR Error retrieving energy data from database: {str(e)}", exc_info=True)
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
        logger.exception(f"Error loading latest simulation results: {e}", exc_info=True)
        return None


def _display_energy_results(simulation_results: dict, space_id: Optional[str] = None, building_id: Optional[str] = None) -> None:
    """
    Display energy consumption results from EnergyPlus simulation for a building.
    Only uses data from database - no CSV fallback.
    
    Args:
        simulation_results: Dictionary containing simulation results
        space_id: Sensor identifier for the simulation (optional)
        building_id: Building identifier to filter by
    """
    logger.info(f"Displaying energy results for building: {building_id or 'any'}")
    logger.debug(f"Simulation results keys: {list(simulation_results.keys())}")
    
    st.subheader("📊 Energy Analysis Results")
    
    try:
        # Get energy data for the whole building from database (do NOT filter to single space_id)
        logger.info("Attempting to retrieve building energy data from database")
        energy_data = _get_energy_data_from_database(building_id=building_id)
        
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
                    total_spaces = session.query(EnergySpace).filter(EnergySpace.energy_building_id == latest_building.energy_building_id).count()
                    
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
            _create_energy_visualizations(energy_data, space_id, start_dt, end_dt)
        else:
            logger.info("No energy data found in database")
            st.info("📊 No energy simulation data available in database.")
            st.info("💡 Run an energy simulation to generate and store energy data.")
    except Exception as e:
        logger.exception(f"Error processing energy results: {str(e)}", exc_info=True)
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
                logger.exception(f"ERROR Error reading space.csv file: {e}", exc_info=True)
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
        logger.exception(f"Error parsing EnergyPlus outputs: {e}", exc_info=True)
        
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
        logger.exception(f"ERROR Error extracting year from EPW file: {e}", exc_info=True)
    
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
        
        # Always search for and parse Date/Time column if present
        time_cols = [col for col in df.columns if any(word in col.lower() for word in ['date', 'time', 'hour', 'timestamp'])]
        time_col = time_cols[0] if time_cols else None
        logger.debug(f"Found potential time columns: {time_cols}")
        
        if time_col:
            try:
                # EnergyPlus CSV files often have complex datetime formats ("01/01  01:00:00")
                if 'Date/Time' in time_col:
                    simulation_year = _get_simulation_year_from_epw(csv_file.parent)
                    if simulation_year is None:
                        simulation_year = start_dt.year if start_dt and hasattr(start_dt, 'year') else datetime.now().year
                        logger.warning(f"WARNING Could not extract year from EPW, using fallback year: {simulation_year}")
                    else:
                        logger.info(f"SUCCESS Using simulation year from EPW: {simulation_year}")
                    
                    df_temp = df[time_col].copy()
                    
                    def fix_eplus_datetime(date_str):
                        if isinstance(date_str, str) and '/' in date_str:
                            cleaned = date_str.strip()
                            parts = cleaned.split()
                            if len(parts) == 2:
                                date_part, time_part = parts[0], parts[1]
                                if time_part.startswith('24:'):
                                    time_part = '00:' + time_part[3:]
                                    dt = pd.to_datetime(f"{simulation_year}/{date_part} {time_part}", format='%Y/%m/%d %H:%M:%S', errors='coerce')
                                    if pd.notna(dt):
                                        return dt + pd.Timedelta(days=1)
                                return pd.to_datetime(f"{simulation_year}/{date_part} {time_part}", format='%Y/%m/%d %H:%M:%S', errors='coerce')
                        return pd.to_datetime(date_str, errors='coerce')
                    
                    df[time_col] = df[time_col].apply(fix_eplus_datetime)
                else:
                    df[time_col] = pd.to_datetime(df[time_col], errors='coerce')
                
                if not df[time_col].isna().all():
                    parsed_count = df[time_col].notna().sum()
                    logger.info(f"SUCCESS Successfully parsed {parsed_count}/{len(df)} EnergyPlus dates")
            except Exception as e:
                logger.warning(f"Could not parse time column '{time_col}': {e}. Using all data.")
        
        # Apply date filtering if requested
        if start_dt is not None and end_dt is not None:
            logger.warning(f"DATE FILTERING APPLIED during CSV parsing: {start_dt} to {end_dt}")
            if time_col and not df[time_col].isna().all():
                start_compare = start_dt.replace(tzinfo=None) if hasattr(start_dt, 'tzinfo') else start_dt
                end_compare = end_dt.replace(tzinfo=None) if hasattr(end_dt, 'tzinfo') else end_dt
                
                mask = (df[time_col] >= start_compare) & (df[time_col] <= end_compare)
                df_filtered = df[mask].copy()
                logger.info(f"Time filtering applied: {len(df)} -> {len(df_filtered)} rows")
                if len(df_filtered) > 0:
                    df = df_filtered
        else:
            logger.info("No date filtering applied - parsing complete simulation data")

        # Store parsed timestamps if available
        if time_col and time_col in df.columns and not df[time_col].isna().all():
            data['timestamps'] = df[time_col].tolist()
            logger.info(f"Stored {len(data['timestamps'])} parsed timestamps in energy_data")

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
            # Sum across all zone columns for each timestep to get true building hourly heating rate (in Joules)
            building_heating_j = df[heating_cols].sum(axis=1).fillna(0)
            total_j = float(building_heating_j.sum())
            total_kwh = total_j / 3600000.0
            peak_w = float(building_heating_j.max()) / 3600.0 if len(building_heating_j) > 0 else 0.0  # J/hr to W
            
            # Convert J to kWh for each hourly timestep
            hourly_kwh = (building_heating_j / 3600000.0).tolist()
            
            data['heating'] = {
                'total_energy_j': total_j,
                'total_energy_kwh': total_kwh,
                'peak_rate_w': peak_w,
                'hourly_data': hourly_kwh,
                'zones_detected': len(heating_cols)
            }
            logger.info(f"Heating summary: {total_kwh:.1f} kWh total, {peak_w:.0f} W peak, {len(heating_cols)} zones, {len(hourly_kwh)} hours")
        
        # Process cooling data  
        if cooling_cols:
            logger.debug("Processing cooling data")
            logger.info(f"COOLING Processing cooling data from {len(df)} filtered rows")
            # Sum across all zone columns for each timestep to get true building hourly cooling rate (in Joules)
            building_cooling_j = df[cooling_cols].sum(axis=1).fillna(0)
            total_j = float(building_cooling_j.sum())
            total_kwh = total_j / 3600000.0
            peak_w = float(building_cooling_j.max()) / 3600.0 if len(building_cooling_j) > 0 else 0.0  # J/hr to W
            
            # Convert J to kWh for each hourly timestep
            hourly_kwh = (building_cooling_j / 3600000.0).tolist()
            
            data['cooling'] = {
                'total_energy_j': total_j,
                'total_energy_kwh': total_kwh,
                'peak_rate_w': peak_w,
                'hourly_data': hourly_kwh,
                'zones_detected': len(cooling_cols)
            }
            logger.info(f"Cooling summary: {total_kwh:.1f} kWh total, {peak_w:.0f} W peak, {len(cooling_cols)} zones, {len(hourly_kwh)} hours")
                
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
                logger.exception(f"ERROR Error reading space.csv file: {e}", exc_info=True)
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
            logger.exception("ERROR No zone-specific energy data found in CSV (after space.csv filtering)")
            logger.exception("   This means EnergySpace and EnergyTimeSeries records will NOT be created")
            
            # Debug information to help identify the issue
            if not space_names_from_csv:
                logger.exception("   Root cause: No space.csv data loaded")
            elif not zone_columns:
                logger.exception("   Root cause: No zone energy columns found in CSV")
            else:
                logger.exception("   Root cause: Zone ID mismatch between CSV columns and space.csv")
                logger.exception(f"   Zone prefixes from CSV: {sorted(set(col.split(':')[0].upper() for col in zone_columns))}")
                logger.exception(f"   Space IDs from space.csv: {sorted(list(space_names_from_csv.keys()))}")
            
        logger.info(f"CSV parsing completed successfully. Data sections: {list(data.keys())}")
            
    except Exception as e:
        logger.exception(f"Error parsing CSV file: {e}", exc_info=True)
        
    return data


def _create_energy_visualizations(energy_data: dict, space_id: str, start_dt=None, end_dt=None) -> None:
    """
    Create visualizations for energy consumption data.
    
    Args:
        energy_data: Parsed energy data from EnergyPlus
        space_id: Sensor identifier
        start_dt: Start datetime for filtering (optional)
        end_dt: End datetime for filtering (optional)
    """
    logger.info(f"Creating energy visualizations for sensor: {space_id}")
    if start_dt and end_dt:
        logger.info(f"Time range filtering: {start_dt} to {end_dt}")
    logger.debug(f"Energy data sections available: {list(energy_data.keys())}")
    
    # Check if this is space-specific view
    building_metadata = energy_data.get('building_metadata', {})
    is_space_specific = building_metadata.get('is_space_specific', False)
    selected_space_id = building_metadata.get('selected_space_id')
    
    # Get space name for space-specific view
    space_name = None
    if is_space_specific and space_id and space_id != "latest":
        # Find the space name for the selected sensor
        zone_energy = energy_data.get('zone_energy', {})
        space_names = energy_data.get('space_names', {})
        
        for zone_id, zone_data in zone_energy.items():
            if zone_data.get('space_id') == space_id:
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
        heating_title = "🔥 Heating Energy"
        if is_space_specific and space_name:
            heating_title += f" - {space_name}"
        elif is_space_specific:
            heating_title += f" - Sensor {space_id}"
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
                    if len(hourly_heating) >= 24 and len(real_timestamps) >= 24:
                        # Calculate daily averages from hourly data
                        daily_avg = [np.mean(hourly_heating[i:i+24]) for i in range(0, len(hourly_heating), 24)]
                        # Sample timestamps to daily (every 24th timestamp), ensuring same length
                        daily_timestamps = [real_timestamps[i] for i in range(0, len(real_timestamps), 24)]
                        
                        # Ensure both arrays have the same length
                        min_length = min(len(daily_avg), len(daily_timestamps))
                        daily_avg = daily_avg[:min_length]
                        date_range = daily_timestamps[:min_length]
                    else:
                        # Use hourly data as-is for shorter periods, ensuring same length
                        min_length = min(len(hourly_heating), len(real_timestamps))
                        daily_avg = hourly_heating[:min_length]
                        date_range = real_timestamps[:min_length]
                else:
                    # Fallback if no timestamps available (should not happen)
                    logger.exception("ERROR: NO REAL TIMESTAMPS AVAILABLE - This should never happen!")
                    st.error("No timestamp data available for visualization")
                    daily_avg = []
                    date_range = []
                
                if date_range:
                    logger.debug(f"Created {len(daily_avg)} daily averages for heating chart with date range {date_range[0]} to {date_range[-1]}")
                else:
                    logger.debug(f"Created {len(daily_avg)} daily averages for heating chart with empty date range")
                
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
                    chart_title += f" - Sensor {space_id}"
                if start_dt and end_dt:
                    chart_title += " (Filtered Period)"
                heating_chart = alt.Chart(heating_df).mark_line(
                    point=True, color='red', strokeWidth=2
                ).add_params(
                    alt.selection_interval(bind='scales')
                ).encode(
                    x=alt.X('Timestamp:T', title='Date', axis=alt.Axis(format='%d %b %Y', labelAngle=-45)),
                    y=alt.Y('Heating_Power_W:Q', title=''),
                    tooltip=[
                        alt.Tooltip('Timestamp:T', title='Date', format='%d %b %Y'),
                        alt.Tooltip('Heating_Power_W:Q', title='Heating Power (W)', format='.1f')
                    ]
                ).properties(
                    width=400,
                    height=300,
                    title=chart_title
                )
                
                st.altair_chart(heating_chart, width='stretch')
                logger.debug("Heating chart displayed successfully")
        else:
            logger.info("No heating data found in energy results")
            st.info("ℹ️ No heating data found in simulation results")
    
    # Cooling Energy Analysis  
    with col2:
        cooling_title = "❄️ Cooling Energy"
        if is_space_specific and space_name:
            cooling_title += f" - {space_name}"
        elif is_space_specific:
            cooling_title += f" - Sensor {space_id}"
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
                    if len(hourly_cooling) >= 24 and len(real_timestamps) >= 24:
                        # Calculate daily averages from hourly data
                        daily_avg = [np.mean(hourly_cooling[i:i+24]) for i in range(0, len(hourly_cooling), 24)]
                        # Sample timestamps to daily (every 24th timestamp), ensuring same length
                        daily_timestamps = [real_timestamps[i] for i in range(0, len(real_timestamps), 24)]
                        
                        # Ensure both arrays have the same length
                        min_length = min(len(daily_avg), len(daily_timestamps))
                        daily_avg = daily_avg[:min_length]
                        date_range = daily_timestamps[:min_length]
                    else:
                        # Use hourly data as-is for shorter periods, ensuring same length
                        min_length = min(len(hourly_cooling), len(real_timestamps))
                        daily_avg = hourly_cooling[:min_length]
                        date_range = real_timestamps[:min_length]
                else:
                    # Fallback if no timestamps available (should not happen)
                    logger.exception("ERROR: NO REAL TIMESTAMPS AVAILABLE FOR COOLING - This should never happen!")
                    st.error("No timestamp data available for cooling visualization")
                    daily_avg = []
                    date_range = []
                
                if date_range:
                    logger.debug(f"Created {len(daily_avg)} daily averages for cooling chart with date range {date_range[0]} to {date_range[-1]}")
                else:
                    logger.debug(f"Created {len(daily_avg)} daily averages for cooling chart with empty date range")
                
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
                    chart_title += f" - Sensor {space_id}"
                if start_dt and end_dt:
                    chart_title += " (Filtered Period)"
                cooling_chart = alt.Chart(cooling_df).mark_line(
                    point=True, color='blue', strokeWidth=2
                ).add_params(
                    alt.selection_interval(bind='scales')
                ).encode(
                    x=alt.X('Timestamp:T', title='Date', axis=alt.Axis(format='%d %b %Y', labelAngle=-45)),
                    y=alt.Y('Cooling_Power_W:Q', title=''),
                    tooltip=[
                        alt.Tooltip('Timestamp:T', title='Date', format='%d %b %Y'),
                        alt.Tooltip('Cooling_Power_W:Q', title='Cooling Power (W)', format='.1f')
                    ]
                ).properties(
                    width=400,
                    height=300,
                    title=chart_title
                )
                
                st.altair_chart(cooling_chart, width='stretch')
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
    
    # Zone Energy Contribution Stacked Bar Chart (only show for building-wide view)
    if 'zone_energy' in energy_data and energy_data['zone_energy'] and not is_space_specific:
        st.markdown("### 📊 Space Energy Contribution")
        
        # Prepare data for stacked bar chart
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
                    logger.debug(f"Bar chart: Zone {zone_id} -> Space '{zone_name}' ({total_zone:.1f} kWh)")
                else:
                    zone_name = zone_id
                    logger.debug(f"Bar chart: Zone {zone_id} (no space name) -> {total_zone:.1f} kWh")
                
                pie_data.append({
                    'Space': zone_name,
                    'Energy_kWh': total_zone,
                    'Heating_kWh': heating,
                    'Cooling_kWh': cooling,
                    'Percentage': (total_zone / total_energy * 100) if total_energy > 0 else 0
                })
        
        if pie_data:
            pie_df = pd.DataFrame(pie_data)
            logger.debug(f"Creating stacked bar chart with {len(pie_df)} spaces, total: {pie_df['Energy_kWh'].sum():.1f} kWh")
            
            # Create two columns for stacked bar chart and data table
            chart_col1, chart_col2 = st.columns([2, 1])
            
            with chart_col1:
                # Create horizontal stacked bar chart for space energy distribution
                # Sort spaces by energy consumption and take top 8 for clarity
                pie_df_sorted = pie_df.sort_values('Energy_kWh', ascending=False).head(8)
                
                # Calculate cumulative percentages for stacking
                pie_df_sorted = pie_df_sorted.copy()
                pie_df_sorted['cumulative_start'] = pie_df_sorted['Percentage'].cumsum() - pie_df_sorted['Percentage']
                pie_df_sorted['cumulative_end'] = pie_df_sorted['Percentage'].cumsum()
                pie_df_sorted['Category'] = "Energy by Space"
                
                # Create horizontal stacked bar chart
                space_bar_chart = alt.Chart(pie_df_sorted, height=100, width=500).mark_bar(
                    height=60
                ).encode(
                    x=alt.X('cumulative_start:Q', title="", scale=alt.Scale(domain=[0, 100])),
                    x2=alt.X2('cumulative_end:Q'),
                    y=alt.Y('Category:N', title="", axis=alt.Axis(labels=False, ticks=False)),
                    color=alt.Color('Space:N', 
                                    scale=alt.Scale(scheme='category20'),
                                    legend=alt.Legend(
                                        title="Spaces", 
                                        orient="bottom", 
                                        columns=4,
                                        labelLimit=120,
                                        labelFontSize=10,
                                        titleFontSize=11
                                    )),
                    tooltip=[
                        alt.Tooltip('Space:N', title='Space Name'),
                        alt.Tooltip('Energy_kWh:Q', title='Total Energy (kWh)', format='.1f'),
                        alt.Tooltip('Heating_kWh:Q', title='Heating (kWh)', format='.1f'),
                        alt.Tooltip('Cooling_kWh:Q', title='Cooling (kWh)', format='.1f'),
                        alt.Tooltip('Percentage:Q', title='Share (%)', format='.1f')
                    ]
                ).properties(
                    title=f"Energy Consumption by Space{' (Filtered Period)' if start_dt and end_dt else ''}"
                )
                
                st.altair_chart(space_bar_chart, width='stretch')
            
            with chart_col2:
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
            st.info("ℹ️ No zone energy data available for stacked bar chart")
    
    # Zone-level data if available
    if 'zone_energy' in energy_data:
        if is_space_specific:
            st.markdown("###  Selected Space Details")
        else:
            st.markdown("###  Thermal Zone Energy Breakdown")
        
        zone_energy = energy_data['zone_energy']
        zone_info = energy_data.get('zones', {})
        space_names = energy_data.get('space_names', {})
        
        logger.debug(f"Displaying zone energy breakdown for {len(zone_energy)} zones")
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
            if not zone_energy:
                st.info("No space-specific breakdown available.")
            else:
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


def _find_existing_epw_file(space_id: str, start_date: date, end_date: date) -> Optional[Path]:
    """
    Check if an EPW file already exists for the given sensor and date range.
    Prioritizes full-year EPW files over partial period files.
    
    Parameters
    ----------
    space_id : str
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
    full_year_filename = f"weather_{space_id}_{year}_full_year.epw"
    full_year_path = weather_dir / full_year_filename
    
    if full_year_path.exists():
        return full_year_path
    
    # Fallback: check for specific date range file
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    expected_filename = f"weather_{space_id}_{start_str}_{end_str}.epw"
    expected_path = weather_dir / expected_filename
    
    if expected_path.exists():
        return expected_path
    
    # Also check for files with similar date ranges (within a few days)
    pattern = f"weather_{space_id}_*.epw"
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
from ece.utils.logging import get_logger
logger = get_logger(__name__)

# --------------------- FILE LOCATIONS -------------------------
LOGO      = Path("./dashboard/assets/images/logo.png")
ECT_LOGO  = Path("./dashboard/assets/images/ect_logo.png")
UNIS_LOGO = Path("./dashboard/assets/images/unis_logo.png")
EU_LOGO   = Path("./dashboard/assets/images/eu_logo.png")
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
@st.cache_data(ttl=30)
def _get_building_ids() -> list[str]:
    """Return all distinct building_id / folder_name values (sorted) from DB and jobs."""
    buildings = set()
    try:
        with SessionLocal() as ses:
            from db.models import Space, IFCSimulationJob, EnergyBuilding
            job_rows = ses.query(IFCSimulationJob.building_name).filter(IFCSimulationJob.status == "OK").all()
            for r in job_rows:
                if r[0]: buildings.add(r[0])

            eb_rows = ses.query(EnergyBuilding.building_id).distinct().all()
            for r in eb_rows:
                if r[0]: buildings.add(r[0])

            rows = ses.query(Space.building_id).filter(Space.building_id != None).distinct().all()
            for r in rows:
                if r[0]: buildings.add(r[0])
    except Exception as e:
        logger.exception(f"Error querying building IDs: {e}")
        
    return sorted(list(buildings))

def _get_space_ids(building_id: str = None) -> list[str]:
    """Return all distinct space_id / zone_name values (sorted) from EnergySpace strictly filtered by building."""
    with SessionLocal() as ses:
        from db.models import EnergySpace, EnergyBuilding
        query = ses.query(EnergySpace.zone_name)
        if building_id:
            query = query.join(EnergyBuilding, EnergySpace.energy_building_id == EnergyBuilding.energy_building_id).filter(EnergyBuilding.building_id == building_id)
        rows = query.distinct().all()
        if rows:
            return sorted(list(set(r[0] for r in rows if r[0])))
    return []

def _is_system_configured() -> bool:
    """Check if the system has been configured with data (spaces, measurements, or models)."""
    try:
        with SessionLocal() as ses:
            from db.models import Space, Measurement, TrainedModel
            
            # Check if we have any spaces (indicates initialization happened)
            spaces_count = ses.query(Space).count()
            if spaces_count > 0:
                return True
            
            # Check if we have any measurements (indicates data upload)
            measurements_count = ses.query(Measurement).count()
            if measurements_count > 0:
                return True
                
            # Check if we have any trained models
            models_count = ses.query(TrainedModel).count()
            if models_count > 0:
                return True
                
            return False
    except Exception as e:
        logger.warning(f"Error checking system configuration: {e}")
        return False

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
            "../models", 
            "../model_reports", 
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
        'latest_epw_path', 'latest_space_id', 'simulation_running', 
        'prevent_rerun', 'latest_simulation_results'
    ]
    for key in energy_keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
            logger.debug(f"Cleared session state key: {key}")
    
    st.session_state.clear()
    st.sidebar.success("Workspace reset – fresh start!")


def _show_csv_format_help():
    """Display CSV format help in an expandable section."""
    with st.expander("📋 CSV Format Guide", expanded=False):
        st.markdown("""
        ### **New Format (Recommended)**
        Your CSV should include these columns:
        
        **Required columns:**
        - `time_end` - Timestamp (YYYY-MM-DD HH:MM:SS)
        - `space_id` - Unique identifier for the space/room
        - `building_id` - Identifier for the building
        - `latitude` - Latitude coordinate for weather data
        - `longitude` - Longitude coordinate for weather data
        
        **Measurement columns (at least one required):**
        - `temperature_c` - Temperature in Celsius
        - `energy_kwh` - Energy consumption in kWh
        - `co2_ppm` - CO2 levels in ppm
        - `rh_percent` - Relative humidity percentage
        - `luminance_lux` - Light levels in lux
        - `average_noise_db` - Average noise in decibels
        - `pm2_5_ugm3` - PM2.5 particles in μg/m³
        - `tvoc_ppb` - Total VOCs in ppb
        - `peak_db` - Peak noise in decibels
        - `co_ppm` - Carbon monoxide in ppm
        - `pm10_ugm3` - PM10 particles in μg/m³
        
        **Optional columns:**
        - `time_stored` - When data was recorded (auto-generated if missing)
        - `window_seconds` - Time window for measurements
        - `data_type` - Will be set based on upload type
        
        ### **Legacy Format**
        If you have older data, you can use:
        - `time_end` + `space_id` + measurement columns
        - No coordinates in CSV (weather data fetching will be skipped)
        
        ### **Example CSV Header:**
        ```
        time_end,space_id,building_id,latitude,longitude,temperature_c,energy_kwh,co2_ppm
        2024-01-01 10:00:00,room_101,building_a,40.7128,-74.0060,22.5,1.2,450
        2024-01-01 11:00:00,room_102,building_a,40.7128,-74.0060,23.1,0.8,430
        ```
        
        ### **Data Tips:**
        - Use consistent timezone for all timestamps
        - Space IDs should be unique within a building
        - Coordinates should be decimal degrees (not DMS format)
        - Missing measurement values are allowed (will be stored as NULL)
        """)

def _validate_csv_columns(df: pd.DataFrame, dtype: str) -> tuple[bool, list[str], list[str]]:
    """
    Validate CSV columns and provide detailed feedback about missing columns.
    
    Args:
        df: DataFrame to validate
        dtype: Data type being imported (train/inference)
    
    Returns:
        tuple: (is_valid, missing_required, missing_optional)
    """
    # Define required columns for different data types
    base_required = ["time_end"]  # Always required
    measurement_columns = [
        "temperature_c", "energy_kwh", "co2_ppm", "rh_percent",
        "luminance_lux", "average_noise_db", "pm2_5_ugm3", "tvoc_ppb",
        "peak_db", "co_ppm", "pm10_ugm3"
    ]
    
    # Check for new format (preferred) vs legacy format
    has_new_format = all(col in df.columns for col in ["space_id", "building_id", "latitude", "longitude"])
    has_legacy_format = "space_id" in df.columns
    has_space_identifier = has_new_format or has_legacy_format
    
    # Required columns based on format
    if has_new_format:
        space_required = ["space_id", "building_id", "latitude", "longitude"]
        format_name = "New format (space_id, building_id, coordinates)"
    elif has_legacy_format:
        space_required = ["space_id"]
        format_name = "Legacy format (space_id)"
    else:
        space_required = ["space_id"]  # Default expectation
        format_name = "Expected format"
    
    required_columns = base_required + space_required
    
    # Check for missing required columns
    missing_required = [col for col in required_columns if col not in df.columns]
    
    # Check for missing measurement columns (at least one should be present)
    available_measurements = [col for col in measurement_columns if col in df.columns]
    if not available_measurements:
        missing_required.append("at least one measurement column (temperature_c, energy_kwh, etc.)")
    
    # Optional columns that enhance functionality
    optional_columns = ["time_stored", "window_seconds", "data_type"]
    missing_optional = [col for col in optional_columns if col not in df.columns]
    
    is_valid = len(missing_required) == 0
    
    # Log validation results
    logger.info(f"CSV validation for {dtype} data:")
    logger.info(f"  - Format detected: {format_name}")
    logger.info(f"  - Columns found: {list(df.columns)}")
    logger.info(f"  - Required columns missing: {missing_required}")
    logger.info(f"  - Optional columns missing: {missing_optional}")
    logger.info(f"  - Available measurements: {available_measurements}")
    logger.info(f"  - Validation result: {'PASS' if is_valid else 'FAIL'}")
    
    return is_valid, missing_required, missing_optional


def _insert_csv(file: bytes, dtype: str, lat: float | None = None, lon: float | None = None):
    try:
        # Try to parse with time_stored first, fall back if not present
        try:
            df = pd.read_csv(file, parse_dates=["time_end", "time_stored"])
        except (ValueError, KeyError):
            # time_stored column might not exist, parse only time_end
            df = pd.read_csv(file, parse_dates=["time_end"])
    except Exception as exc:
        st.sidebar.error(f"Could not read CSV: {exc}")
        logger.exception("CSV read failed")
        return

    # -------------------------------------------
    # Validate CSV columns before processing
    # -------------------------------------------
    is_valid, missing_required, missing_optional = _validate_csv_columns(df, dtype)
    
    if not is_valid:
        error_msg = f"❌ **CSV Validation Failed for {dtype} data**\n\n"
        error_msg += f"**Missing required columns:**\n"
        for col in missing_required:
            error_msg += f"- `{col}`\n"
        
        if missing_optional:
            error_msg += f"\n**Missing optional columns** (will use defaults):\n"
            for col in missing_optional:
                error_msg += f"- `{col}`\n"
        
        error_msg += f"\n**Quick format reference:**\n"
        error_msg += f"**New format:** `time_end`, `space_id`, `building_id`, `latitude`, `longitude`, plus measurements\n"
        error_msg += f"**Legacy format:** `time_end`, `space_id`, plus measurements\n\n"
        error_msg += f"**Your CSV columns:** `{', '.join(df.columns)}`\n\n"
        error_msg += f"💡 See the **CSV Format Guide** above for detailed examples."
        
        st.sidebar.error(error_msg)
        logger.exception(f"CSV validation failed for {dtype}: missing {missing_required}")
        return
    
    # Show validation success message with summary
    if missing_optional:
        st.sidebar.info(f"✅ CSV validated successfully! Missing optional columns will use defaults: {', '.join(missing_optional)}")
    else:
        st.sidebar.success(f"✅ CSV validated successfully! All required and optional columns found.")
    
    # Show data summary
    measurement_cols = [col for col in df.columns if col in [
        "temperature_c", "energy_kwh", "co2_ppm", "rh_percent",
        "luminance_lux", "average_noise_db", "pm2_5_ugm3", "tvoc_ppb",
        "peak_db", "co_ppm", "pm10_ugm3"
    ]]
    
    summary_msg = f"**Data Summary:**\n"
    summary_msg += f"- Rows: {len(df):,}\n"
    summary_msg += f"- Time range: {df['time_end'].min()} to {df['time_end'].max()}\n"
    
    if "space_id" in df.columns:
        unique_spaces = df['space_id'].nunique()
        summary_msg += f"- Unique spaces: {unique_spaces}\n"
        if "building_id" in df.columns:
            unique_buildings = df['building_id'].nunique()
            summary_msg += f"- Unique buildings: {unique_buildings}\n"
    elif "space_id" in df.columns:
        unique_sensors = df['space_id'].nunique()
        summary_msg += f"- Unique sensors: {unique_sensors}\n"
    
    summary_msg += f"- Measurement types: {', '.join(measurement_cols)}"
    st.sidebar.info(summary_msg)

    # -------------------------------------------
    # Extract space and building information from CSV and ensure spaces exist
    # -------------------------------------------
    
    # First, process spaces information - handle all possible cases
    spaces_data = []
    
    # Check if we have space_id column (required for measurements)
    if "space_id" in df.columns:
        # Extract unique space_ids from the CSV
        unique_space_ids = df["space_id"].dropna().unique()
        
        if len(unique_space_ids) == 0:
            st.sidebar.error("❌ No valid space_id values found in CSV")
            logger.exception("No valid space_id values found in CSV")
            return
        
        with SessionLocal() as ses:
            from db.models import Space
            
            for space_id in unique_space_ids:
                # Check if space already exists
                existing_space = ses.query(Space).filter(Space.space_id == space_id).first()
                
                if not existing_space:
                    # Need to create new space - determine building_id, lat, lon
                    if all(col in df.columns for col in ["building_id", "latitude", "longitude"]):
                        # Get building info from CSV for this space
                        space_info = df[df["space_id"] == space_id][["building_id", "latitude", "longitude"]].iloc[0]
                        building_id = space_info["building_id"]
                        latitude = float(space_info["latitude"])
                        longitude = float(space_info["longitude"])
                    else:
                        # Use defaults or provided coordinates
                        building_id = "default_building"
                        latitude = lat if lat is not None else 40.6401  # Default: Thessaloniki
                        longitude = lon if lon is not None else 22.9444
                    
                    # Create new space record
                    new_space = Space(
                        space_id=space_id,
                        building_id=building_id,
                        latitude=latitude,
                        longitude=longitude
                    )
                    ses.add(new_space)
                    spaces_data.append({
                        'space_id': space_id,
                        'building_id': building_id,
                        'latitude': latitude,
                        'longitude': longitude
                    })
                    logger.info(f"Created new space: {space_id} in building {building_id}")
                else:
                    # Space exists - optionally update coordinates if provided in CSV
                    if all(col in df.columns for col in ["building_id", "latitude", "longitude"]):
                        space_info = df[df["space_id"] == space_id][["building_id", "latitude", "longitude"]].iloc[0]
                        existing_space.building_id = space_info["building_id"]
                        existing_space.latitude = float(space_info["latitude"])
                        existing_space.longitude = float(space_info["longitude"])
                        logger.info(f"Updated existing space: {space_id}")
            
            ses.commit()
            logger.debug(f"Processed {len(unique_space_ids)} unique spaces")
    else:
        st.sidebar.error("❌ CSV must contain 'space_id' or 'space_id' column")
        logger.exception("CSV missing space_id/space_id column")
        return

    # -------------------------------------------
    # keep only columns that really exist on measurements table
    # and let PG fill defaults (time_stored, window_seconds, …)
    # -------------------------------------------
    allowed_cols = {
        "time_end", "space_id", "data_type","time_stored", "window_seconds",
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
                render_nulls=True          # keep NULLs, don't omit keys
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
    # Use coordinates from spaces data if available, otherwise use provided lat/lon
    coords_to_fetch = []
    
    if spaces_data:
        # Store the first building_id as current for session
        st.session_state['current_building_id'] = spaces_data[0]['building_id']
        logger.debug(f"Set current building_id in session: {spaces_data[0]['building_id']}")
        
        # Use unique coordinates from the spaces data
        unique_coords = set((space['latitude'], space['longitude']) for space in spaces_data)
        coords_to_fetch = list(unique_coords)
    else:
        # Fallback: get coordinates from database for existing spaces
        with SessionLocal() as ses:
            from db.models import Space
            unique_space_ids = df["space_id"].dropna().unique()
            spaces_from_db = ses.query(Space).filter(Space.space_id.in_(unique_space_ids)).all()
            unique_coords = set((float(space.latitude), float(space.longitude)) for space in spaces_from_db)
            coords_to_fetch = list(unique_coords)
    
    if coords_to_fetch:
        # fetch weather data for each unique location
        start = df["time_end"].min()
        end = df["time_end"].max()
        logger.info("Fetching weather data for %d locations from %s to %s", len(coords_to_fetch), start, end)
        
        # Process weather data for each unique location
        with SessionLocal() as ses:
            from db.models import Space
            
            for fetch_lat, fetch_lon in coords_to_fetch:
                logger.info(f"Fetching weather data for location: {fetch_lat}, {fetch_lon}")
                weather_df = fetch_open_meteo(lat=fetch_lat, lon=fetch_lon, start=start, end=end)
                weather_df['fetched_at'] = datetime.now(tz=timezone.utc)
                
                # minor rename 'temperature_2m' to 'outdoor_temperature_2m'
                # and          'relative_humidity_2m' to 'outdoor_relative_humidity_2m'
                weather_df.rename(columns={
                    "temperature_2m": "outdoor_temperature_2m",
                    "relative_humidity_2m": "outdoor_relative_humidity_2m"
                }, inplace=True)
                
                logger.info("Weather data fetched for location (%.4f, %.4f): %s", fetch_lat, fetch_lon, str(weather_df.shape))
                
                # Find all spaces at this location
                spaces_at_location = ses.query(Space).filter(
                    Space.latitude == fetch_lat,
                    Space.longitude == fetch_lon
                ).all()
                
                # Insert weather data for each space at this location
                try:
                    for space in spaces_at_location:
                        if space.space_id in df["space_id"].unique():
                            # Create weather data for this space
                            weather_df_space = weather_df.copy()
                            weather_df_space["space_id"] = space.space_id
                            
                            # if empty, skip this space_id
                            if not weather_df_space.empty:
                                # insert dataframe with session bulk insert mappings
                                ses.bulk_insert_mappings(
                                    Weather,
                                    weather_df_space.to_dict("records"),
                                    render_nulls=True  # keep NULLs, don't omit keys
                                )
                                logger.info("Inserted %d weather rows for space %s", len(weather_df_space), space.space_id)
                    
                    # Commit all weather data for this location
                    ses.commit()
                    
                except Exception as exc:
                    ses.rollback()
                    st.sidebar.error(f"Weather data insert failed for location ({fetch_lat}, {fetch_lon}): {exc}")
                    logger.exception("Weather data insert failed for location (%s, %s)", fetch_lat, fetch_lon)
    else:
        logger.info("No coordinates available for weather data fetching - skipping weather data")


def _show_initialize_modal():
    """Display the initialization modal for uploading CSV and IFC files."""
    
    # Create a modal-like container using st.container and custom styling
    modal_container = st.container()
    
    with modal_container:
        # Add some custom CSS for modal-like appearance
        st.markdown("""
        <style>
        .modal-container {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.5);
            z-index: 1000;
        }
        .modal-content {
            background-color: white;
            margin: 5% auto;
            padding: 20px;
            border-radius: 10px;
            width: 80%;
            max-width: 600px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Use columns to center the modal
        col1, col2, col3 = st.columns([1, 3, 1])
        
        with col2:
            st.markdown("### ⚙️ Configure Energy Comfortness Tool")
            st.markdown("---")
            
            # Use a form to group all uploads
            with st.form("initialize_form", clear_on_submit=False):
                st.markdown("#### 📊 Training Data")
                uploaded_csv = st.file_uploader(
                    "Upload Training Data CSV", 
                    type="csv",
                    help="Upload CSV file containing measurement data for training",
                    key="init_csv"
                )
                
                # Add CSV format help
                _show_csv_format_help()
                
                st.markdown("#### 🏢 Building Model")
                uploaded_ifc = st.file_uploader(
                    "Upload IFC Building Model", 
                    type=['ifc'],
                    help="Upload an IFC (Industry Foundation Classes) file for building simulation",
                    key="init_ifc"
                )
                
                # Submit button
                submit_full = st.form_submit_button("🚀 Submit", type="primary", 
                                                  help="Upload CSV and/or IFC files")
            
            # Handle form submission outside the form
            if submit_full:
                if uploaded_csv and uploaded_ifc:
                    # Both files uploaded - full initialization
                    _handle_initialization(uploaded_csv, uploaded_ifc)
                elif uploaded_csv and not uploaded_ifc:
                    # Only CSV uploaded
                    _handle_csv_upload(uploaded_csv)
                elif uploaded_ifc and not uploaded_csv:
                    # Only IFC uploaded - handle IFC file
                    _handle_ifc_upload(uploaded_ifc)
                else:
                    # No files uploaded
                    st.error("Please upload at least one file (CSV for training data or IFC for building model).")
            
            # Cancel button outside form
            if st.button("❌ Cancel", key="cancel_init"):
                st.session_state['show_initialize_modal'] = False
                st.rerun()


def _handle_initialization(csv_file, ifc_file):
    """Handle the full initialization with both CSV and IFC files."""
    errors = []
    
    # Validate inputs
    if csv_file is None:
        errors.append("Please upload a CSV file")
    # if ifc_file is None:  # is fine for user to not upload an IFC
    #     errors.append("Please upload an IFC file")
    
    if errors:
        for error in errors:
            st.error(error)
        return
    
    try:
        # Process CSV file
        st.info("🔄 Processing training data...")
        _insert_csv(csv_file, "train")
        
        # Store IFC file
        st.info("🔄 Storing building model...")
        models_dir = Path("./eplus_sim/models")
        models_dir.mkdir(parents=True, exist_ok=True)
        
        # Save IFC file with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ifc_filename = f"building_model_{timestamp}.ifc"
        ifc_path = models_dir / ifc_filename
        
        with open(ifc_path, "wb") as f:
            f.write(ifc_file.getbuffer())
        
        # Clear cache and close modal
        st.cache_data.clear()
        st.session_state['show_initialize_modal'] = False
        st.session_state['latest_ifc_path'] = str(ifc_path)
        st.session_state['ifc_is_default'] = False
        
        st.success(f"✅ Initialization complete! CSV processed and IFC file saved as {ifc_filename}")
        logger.info(f"Initialization completed: CSV processed, IFC saved to {ifc_path}")
        
        # Rerun to update the interface
        st.rerun()
        
    except Exception as e:
        st.error(f"❌ Initialization failed: {str(e)}")
        logger.exception(f"Initialization failed: {str(e)}", exc_info=True)


def _handle_csv_upload(csv_file):
    """Handle CSV-only upload."""
    try:
        st.info("🔄 Processing training data...")
        _insert_csv(csv_file, "train")
        
        # Clear cache and close modal
        st.cache_data.clear()
        st.session_state['show_initialize_modal'] = False
        
        st.success("✅ Training data uploaded successfully!")
        logger.info("CSV upload completed successfully")
        
        # Rerun to update the interface
        st.rerun()
        
    except Exception as e:
        st.error(f"❌ CSV upload failed: {str(e)}")
        logger.exception(f"CSV upload failed: {str(e)}", exc_info=True)


def _handle_ifc_upload(ifc_file):
    """Handle IFC file upload only."""
    try:
        if ifc_file is None:
            st.error("❌ No IFC file provided")
            return
        
        # Save IFC file
        models_dir = Path("./eplus_sim/models")
        models_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ifc_filename = f"uploaded_{timestamp}.ifc"
        ifc_path = models_dir / ifc_filename
        
        with open(ifc_path, "wb") as f:
            f.write(ifc_file.getbuffer())
        
        # Store in session state
        st.session_state['latest_ifc_path'] = str(ifc_path)
        st.session_state['uploaded_ifc_path'] = str(ifc_path)
        st.session_state['ifc_is_default'] = False
        
        # Show success message
        file_size_mb = len(ifc_file.getbuffer()) / (1024 * 1024)
        st.success(f"✅ **IFC file uploaded successfully!**")
        st.info(f"📄 **File:** {ifc_file.name} ({file_size_mb:.1f} MB)")
        st.info(f"💾 **Saved as:** {ifc_filename}")
        
        # Close modal
        st.session_state['show_initialize_modal'] = False
        
        logger.info(f"IFC file uploaded successfully: {ifc_path} ({file_size_mb:.1f} MB)")
        st.rerun()
        
    except Exception as e:
        st.error(f"❌ IFC upload failed: {str(e)}")
        logger.exception(f"IFC upload failed: {str(e)}", exc_info=True)


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

# *** UI FIX: Hide cursor, image expand buttons, and focus outlines ***
st.markdown("""
<style>
/* Hide caret everywhere except actual text inputs */
.stApp *:not(input):not(textarea):not([contenteditable="true"]) {
  caret-color: transparent !important;
}
/* Remove focus ring on non-inputs */
.stApp *:not(input):not(textarea):focus {
  outline: none !important;
}
/* (Optional) stop text selection in empty areas */
.stApp, .stSidebar {
  -webkit-user-select: none;
  user-select: none;
}

/* Remove the fullscreen/expand button on images */
[data-testid="stImage"] button,
button[title="View fullscreen"] {
  display: none !important;
  
}
            
/* Hide top-right Deploy + 3-dot menu */
header [data-testid="stToolbar"],
header [data-testid="stStatusWidget"],
header div[role="button"] {
  display: none !important;
}

/* 5) Hide Streamlit footer ("Made with Streamlit") */
footer {visibility: hidden;}
[data-testid="stFooter"] {
  display: none !important;
}
            
/* 6) Hide sidebar's collapsible button
/* Hide collapse/expand buttons in Streamlit 1.46.1 */
[data-testid="stSidebarCollapseButton"] {
    display: none !important;
}
</style>
""", unsafe_allow_html=True)

# ECT Logo at top of sidebar - centered
if ECT_LOGO.exists() and LOGO.exists():
    import base64
    
    # Convert images to base64 for HTML embedding
    with open(ECT_LOGO, "rb") as f:
        ect_logo_b64 = base64.b64encode(f.read()).decode()
    with open(LOGO, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode()
    
    st.sidebar.markdown(
        f"""
        <div style="display: flex; justify-content: center; align-items: center; gap: 10px;">
            <img src="data:image/png;base64,{ect_logo_b64}" width="100">
            <a href="https://www.euproject-access.eu/en" target="_blank">
                <img src="data:image/png;base64,{logo_b64}" width="100">
            </a>
        </div>
        """,
        unsafe_allow_html=True
    )



# Initialize button - Create popup for data upload
if st.sidebar.button("⚙️ Configure", help="Upload CSV data and IFC file to configure the system", type="primary"):
    st.session_state['show_initialize_modal'] = True

# Initialize Modal Dialog
if st.session_state.get('show_initialize_modal', False):
    _show_initialize_modal()
    st.stop()  # Stop execution here to prevent showing the rest of the app

# Dynamic date limits based on when the application is run
CURRENT_DATE = datetime.now(tz=timezone.utc)   # Current date when app is run
TIME_BEFORE_LIMIT = timedelta(days=365 * 3)    # 3 years before current date
TIME_AFTER_LIMIT = timedelta(days=14)          # 14 days after current date

min_limit = CURRENT_DATE - TIME_BEFORE_LIMIT   # earliest selectable (3 years before current date)
max_limit = CURRENT_DATE + TIME_AFTER_LIMIT    # latest selectable (14 days from current date)

DEFAULT_START = date(2026, 1, 1)
DEFAULT_END   = max_limit.date()

# Time window in expandable section
with st.sidebar.expander("📅 Time Window", expanded=False):
    start = st.date_input(
        "Start",
        value=DEFAULT_START,
        min_value=min_limit.date(),
        max_value=max_limit.date(),
        help=f"Select start date (allowed range: {min_limit.date()} to {max_limit.date()})\nDynamic limits: 2 years before to 14 days after current date"
    )

    end = st.date_input(
        "End",
        value=DEFAULT_END,
        min_value=min_limit.date(),
        max_value=max_limit.date(),
        help=f"Select end date (allowed range: {min_limit.date()} to {max_limit.date()})\nDynamic limits: 2 years before to 14 days after current date"
    )
    
    # Show current date and dynamic limits info
    st.caption(f"📅 Current date: {CURRENT_DATE.date()} | Valid range: {min_limit.date()} to {max_limit.date()}")
    
    # Date validation: Check if start date is after end date
    if start > end:
        st.error("⚠️ **Invalid date range**: Start date cannot be later than end date. Please adjust your selection.")
    else:
        # Show current valid selection
        if start != end:
            days_diff = (end - start).days
            st.success(f"✅ Valid time window: {days_diff + 1} days selected ({start} to {end})")
        else:
            st.info(f"📅 Single day selected: {start}")
    
    # Handle date reset if requested
    if st.session_state.get('reset_dates', False):
        start = DEFAULT_START
        end = DEFAULT_END
        st.session_state['reset_dates'] = False
        st.rerun()

start_dt = pd.to_datetime(start)
end_dt = pd.to_datetime(end)

# Store in session state for global access
st.session_state['start_dt'] = start_dt
st.session_state['end_dt'] = end_dt

# Profile details in an expander
profiles = pd.read_csv(PROFILES)
with st.sidebar.expander("👤 Profile Details", expanded=False):
    prof_id = st.selectbox("Occupant profile", profiles["occupant_profile_id"])
    prof    = profiles.set_index("occupant_profile_id").loc[prof_id]
    
    # Store selected profile in session state
    st.session_state["occupant_profile"] = prof_id

    A_m2   = get_human_surf_area(prof["weight_kg"], prof["height_cm"])
    BMR_W  = basal_metabolic_rate(prof)
    BMR_kcal = BMR_W / 0.048425
    M_Wm2  = metabolic_rate_fanger(BMR_W, A_m2)
    M_met  = wm2_to_met(M_Wm2)
    if prof['visual_impairment']:
        vis_imp = "Yes"
    else:
        vis_imp = "No"
    st.markdown(
        f"""**Profile details**  
        - Age: **{prof['age']}**  
        - Gender: {prof['gender']}  
        - Weight: **{prof['weight_kg']} kg**  
        - Height: **{prof['height_cm']} cm**  
        - *BMR*: **{BMR_kcal:.0f} kcal/day**  
        - *M*: **{M_Wm2:.1f} W m⁻²**  ≈  **{M_met:.2f} met**  
        - *Visual Impairment*: **{vis_imp}**
        """
    )


# Building and space selection
building_options = _get_building_ids()
if building_options:
    selected_building = st.sidebar.selectbox(
        "Selected building", building_options, key="building_filter"
    )
else:
    st.sidebar.warning("⚠️ No buildings available. Please upload data first.")
    selected_building = None

# Space selection (filtered by building)
space_options = _get_space_ids(selected_building if building_options else None)
if space_options:
    selected_space = st.sidebar.selectbox(
        "Selected space", space_options, key="space_filter"
    )
else:
    st.sidebar.warning("⚠️ No spaces available. Please upload training data first.")
    selected_space = None

# Keep legacy variable name for compatibility
selected_sensor = selected_space

# Train models button
if "training" not in st.session_state:
    st.session_state["training"] = False
if "predicted" not in st.session_state:
    st.session_state["predicted"] = False


def _train():
    st.session_state["training"] = True
    try:
        main_train_all_targets()
        st.session_state["training"] = False
        st.session_state["training_success"] = True
    except Exception as e:
        st.session_state["training"] = False
        st.session_state["training_error"] = str(e)


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
        logger.exception(f"Error calculating comfort on-the-fly for profile {selected_profile}: {e}")
    
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
            logger.warning(f"Error calculating thermal comfort for profile {profile.get('name', 'unknown')}: {e}")
    
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
            logger.warning(f"Error calculating visual comfort for profile {profile.get('name', 'unknown')}: {e}")
    
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
            logger.warning(f"Error calculating acoustic comfort for profile {profile.get('name', 'unknown')}: {e}")
    
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
                logger.warning(f"Error calculating {comfort_key} for profile {profile.get('name', 'unknown')}: {e}")
    
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
        logger.warning(f"Error calculating overall comfort for profile {profile.get('name', 'unknown')}: {e}")
    
    return comfort_data


def _predict():
    """Generate predictions by downloading weather data for the selected period and running models."""
    st.session_state["predicted"] = False
    logger.info("Simulation trigger clicked")
    
    try:
        import pandas as pd
        import joblib
        import numpy as np
        from pathlib import Path
        from datetime import datetime, timezone
        
        with st.spinner("Running simulation …"):
            logger.info("Starting simulation process...")
            
            # Get time range and space from sidebar
            start_dt = st.session_state.get('start_dt')
            end_dt = st.session_state.get('end_dt')
            selected_space = st.session_state.get('space_filter')
            
            if not start_dt or not end_dt:
                st.sidebar.error("❌ Please select a time range in the sidebar.")
                logger.exception("No time range selected")
                return
                
            # Convert to datetime if needed
            if not isinstance(start_dt, datetime):
                start_dt = pd.to_datetime(start_dt)
            if not isinstance(end_dt, datetime):
                end_dt = pd.to_datetime(end_dt)
            
            # First check if we have trained models - try multiple possible locations
            possible_models_dirs = [
                Path("./models"),           # Same level as dashboard
                Path("../models"),          # One level up from dashboard  
                Path("dashboard/models"),   # Relative from project root
                Path("./dashboard/models")  # From current working directory
            ]
            
            models_dir = None
            for potential_dir in possible_models_dirs:
                if potential_dir.exists():
                    models_dir = potential_dir
                    logger.info(f"Found models directory at: {models_dir}")
                    break
            
            if models_dir is None:
                st.session_state["model_error"] = "no_models_dir"
                logger.exception(f"Models directory does not exist. Checked locations: {[str(p) for p in possible_models_dirs]}")
                return
            
            with SessionLocal() as ses:
                from db.models import TrainedModel, Space, Weather
                from ece.feature_map import MAP as FEATURE_MAP, TIME_DRIVERS
                from ece.pipeline_weather import ensure_complete_weather_data
                
                # Check if any trained models exist
                models_count = ses.query(TrainedModel).count()
                if models_count == 0:
                    st.sidebar.error("❌ No trained models found. Please train models first.")
                    logger.exception("No trained models in database")
                    return
                
                logger.info(f"Found {models_count} trained model(s) in database")
                
                # Get spaces to predict for
                if selected_space:
                    spaces = ses.query(Space).filter(Space.space_id == selected_space).all()
                else:
                    spaces = ses.query(Space).all()
                
                if not spaces:
                    st.sidebar.error("❌ No spaces found. Please upload data first.")
                    logger.exception("No spaces found in database")
                    return
                
                logger.info(f"Generating predictions for {len(spaces)} space(s)")
                
                # Download weather data for each space for the specified period
                weather_progress = st.empty()
                weather_progress.info("🌤️ Downloading weather data for the selected period...")
                for space in spaces:
                    logger.info(f"Ensuring weather data for space {space.space_id} ({space.latitude}, {space.longitude})")
                    try:
                        ensure_complete_weather_data(
                            space_id=space.space_id,
                            latitude=space.latitude,
                            longitude=space.longitude,
                            start=start_dt,
                            end=end_dt
                        )
                    except Exception as e:
                        logger.exception(f"Failed to download weather data for space {space.space_id}: {e}")
                        st.sidebar.warning(f"⚠️ Failed to download weather data for space {space.space_id}")
                        continue
                
                # Clear weather progress message
                weather_progress.empty()
                
                # Now fetch the weather data we just downloaded/ensured
                prediction_progress = st.empty()
                prediction_progress.info("🔮 Running prediction models...")
                query = ses.query(Weather).filter(
                    Weather.time_end >= start_dt,
                    Weather.time_end <= end_dt
                )
                
                if selected_space:
                    query = query.filter(Weather.space_id == selected_space)
                
                weather_results = query.order_by(Weather.time_end).all()
                
                if not weather_results:
                    st.sidebar.error("❌ No weather data available for the selected period and space(s).")
                    logger.exception("No weather data found after download attempt")
                    return
                
                logger.info(f"Found {len(weather_results)} weather records for prediction")
                
                # Convert weather data to DataFrame for predictions
                weather_data = []
                for weather in weather_results:
                    row = {
                        'time_end': weather.time_end,
                        'space_id': weather.space_id,
                        # Weather features for prediction input
                        'outdoor_temperature_2m': weather.outdoor_temperature_2m,
                        'outdoor_relative_humidity_2m': weather.outdoor_relative_humidity_2m,
                        'wind_speed_10m': weather.wind_speed_10m,
                        'shortwave_radiation': weather.shortwave_radiation or 0,
                        'direct_radiation': weather.direct_radiation or 0,
                        'precipitation': weather.precipitation or 0,
                        'cloud_cover': weather.cloud_cover or 0,
                    }
                    weather_data.append(row)
                
                df_base = pd.DataFrame(weather_data)
                df_base = df_base.sort_values(['space_id', 'time_end'])
                
                # Generate predictions per space (use space-specific models)
                all_predictions = []
                unique_spaces = df_base['space_id'].unique()
                
                logger.info(f"Generating predictions for {len(unique_spaces)} space(s): {', '.join(unique_spaces)}")
                
                for current_space_id in unique_spaces:
                    logger.info(f"\n  [Predicting for space: {current_space_id}]")
                    
                    # Filter data for this space
                    df_space = df_base[df_base['space_id'] == current_space_id].copy()
                    logger.info(f"    - {len(df_space)} weather records for space {current_space_id}")
                    
                    # Get models trained for THIS specific space
                    space_models = ses.query(TrainedModel).filter(
                        TrainedModel.space_id == current_space_id
                    ).all()
                    
                    if not space_models:
                        logger.warning(f"    - No trained models found for space {current_space_id}, skipping")
                        continue
                    
                    logger.info(f"    - Found {len(space_models)} trained model(s) for space {current_space_id}")
                    
                    # Dictionary to store predictions for this space
                    space_predictions = {}
                    
                    for model_record in space_models:
                        target = model_record.target
                        model_path = Path(model_record.model_path)
                        
                        if not model_path.exists():
                            logger.warning(f"    - Model file not found: {model_path}")
                            continue
                        
                        try:
                            # Load the trained model
                            model_data = joblib.load(model_path)
                            model = model_data['model']
                            features = model_data['features']
                            model_space_id = model_data.get('space_id', None)
                            
                            # Verify model was trained for this space
                            if model_space_id and model_space_id != current_space_id:
                                logger.warning(f"    - Model space_id mismatch: expected {current_space_id}, got {model_space_id}")
                                continue
                            
                            # Prepare feature data (add derived features)
                            df_features = _add_derived_features_for_prediction(df_space.copy(), features)
                            
                            # Check which features are available for this model
                            available_features = []
                            missing_features = []
                            
                            for f in features:
                                if f in TIME_DRIVERS:
                                    # Time features are generated automatically
                                    available_features.append(f)
                                elif f in df_features.columns:
                                    available_features.append(f)
                                else:
                                    missing_features.append(f)
                            
                            if missing_features:
                                logger.warning(f"    - Missing features for {target}: {missing_features}")
                            
                            if len(available_features) < len(features) * 0.5:  # Need at least 50% of features
                                logger.warning(f"    - Too many missing features for {target} ({len(missing_features)}/{len(features)})")
                                continue
                            
                            # Make predictions using available features
                            X = df_features[available_features].fillna(0)  # Fill NaN with reasonable defaults
                            if len(X) > 0:
                                y_pred = model.predict(X)
                                space_predictions[f'pred_{target}'] = y_pred
                                logger.info(f"    - Generated {len(y_pred)} predictions for {target} using {len(available_features)}/{len(features)} features")
                            
                        except Exception as e:
                            logger.exception(f"    - Error predicting {target}: {e}")
                            continue
                    
                    if not space_predictions:
                        logger.warning(f"    - No predictions generated for space {current_space_id}")
                        continue
                    
                    # Create prediction DataFrame for this space
                    df_space_pred = df_space[['time_end', 'space_id']].copy()
                    for pred_col, pred_values in space_predictions.items():
                        df_space_pred[pred_col] = pred_values
                    
                    all_predictions.append(df_space_pred)
                    logger.info(f"    - ✓ Completed predictions for space {current_space_id}: {len(space_predictions)} targets")
                
                if not all_predictions:
                    st.sidebar.error("❌ Failed to generate any predictions. Check that models exist for the selected space(s).")
                    logger.exception("No predictions generated for any space")
                    return
                
                # Combine predictions from all spaces
                df_pred = pd.concat(all_predictions, ignore_index=True)
                df_pred = df_pred.sort_values(['space_id', 'time_end'])
                logger.info(f"\n✓ Combined predictions: {len(df_pred)} total rows across {len(unique_spaces)} space(s)")
                
                # Add comfort analysis using the selected occupant profile
                profile_id = st.session_state.get('occupant_profile', 'Profile1')
                profiles = pd.read_csv(PROFILES)
                prof = profiles.set_index("occupant_profile_id").loc[profile_id]
                
                # Calculate comfort metrics
                df_pred = _add_comfort_cols(df_pred, prof)
                
                # Store results in session state
                st.session_state["pred_df"] = df_pred
                st.session_state["predicted"] = True
                
                # Clear prediction progress message
                prediction_progress.empty()
                
                logger.info(f"Simulation completed successfully with {len(df_pred)} predictions")
                st.sidebar.success(f"🎯 Simulation complete! Generated {len(df_pred)} predictions with comfort analysis.")
                
    except Exception as e:
        logger.exception(f"Error during simulation: {e}")
        # Clear any progress messages on error
        try:
            prediction_progress.empty()
        except:
            pass
        st.sidebar.error(f"❌ Simulation failed: {str(e)}")
        st.session_state["pred_df"] = pd.DataFrame()
        st.session_state["predicted"] = False


def _add_derived_features_for_prediction(df: pd.DataFrame, feats: list) -> pd.DataFrame:
    """Add derived features for prediction (simplified version of pipeline_ml function)."""
    import math
    import re
    
    df = df.copy()
    
    # Regex for derived features
    _DERIV_RE = re.compile(r"^(?P<base>.+)_(?P<agg>mean|std|max|min)_(?P<win>\d+)h$")
    _AGG_FUN = {"mean": "mean", "std": "std", "max": "max", "min": "min"}
    
    # Rolling window features
    for f in feats:
        if f in df.columns or f in TIME_DRIVERS:
            continue
        m = _DERIV_RE.match(f)
        if not m:
            continue
        base, agg, win = m.group("base"), m.group("agg"), int(m.group("win"))
        
        if base not in df.columns:
            continue
            
        try:
            rolled = (
                df.set_index("time_end")
                  .groupby("space_id")[base]
                  .rolling(f"{win}h", min_periods=1)
                  .agg(_AGG_FUN[agg])
                  .reset_index(level=0, drop=True)
            )
            df[f] = rolled.values
        except Exception as e:
            logger.warning(f"Failed to create derived feature {f}: {e}")
            continue
    
    # Time harmonic features
    if any(td in feats for td in TIME_DRIVERS):
        doy = df["time_end"].dt.dayofyear
        hod = df["time_end"].dt.hour + df["time_end"].dt.minute / 60
        if "doy_sin" in feats:
            df["doy_sin"] = np.sin(2 * math.pi * doy / 365)
        if "doy_cos" in feats:
            df["doy_cos"] = np.cos(2 * math.pi * doy / 365)
        if "hour_sin" in feats:
            df["hour_sin"] = np.sin(2 * math.pi * hod / 24)
        if "hour_cos" in feats:
            df["hour_cos"] = np.cos(2 * math.pi * hod / 24)
    
    return df


# Train and Simulate buttons
col1, col2 = st.sidebar.columns(2)
col1.button("Train models", on_click=_train, disabled=st.session_state["training"])
col2.button("Simulate", on_click=_predict)

# DEBUG: Add test button to check database state
def _test_database_state():
    """Test database connectivity and state."""
    try:
        from db.models import Space, Measurement
        with SessionLocal() as session:
            # Check if spaces table exists and has data
            spaces_count = session.query(Space).count()
            measurements_count = session.query(Measurement).count()
            
            st.write(f"🏢 Spaces in database: {spaces_count}")
            st.write(f"📊 Measurements in database: {measurements_count}")
            
            if spaces_count > 0:
                sample_space = session.query(Space).first()
                st.write(f"📍 Sample space: {sample_space.space_id} in building {sample_space.building_id}")
            
            st.success("Database connection successful!")
            
    except Exception as e:
        st.error(f"Database test failed: {str(e)}")
        logger.exception(f"Database test error: {e}")

# Dev Tools in expandable section
with st.sidebar.expander("🔧 Dev Tools", expanded=False):
    # Test DB State button
    if st.button("🔍 Test DB State", help="Check database state and recent predictions"):
        _test_database_state()

    # Dynamic Space Energy Query button
    selected_space_dev = st.session_state.get("space_filter", "").strip()
    target_space_dev = selected_space_dev if selected_space_dev else None
    button_label = f"🔋 Test Energy Query ({selected_space_dev if selected_space_dev else 'All Spaces'})"
    
    if st.button(button_label, help="Query energy data from database for current selected space"):
        st.write(f"Querying database for space_id = {selected_space_dev if selected_space_dev else 'All Spaces'}...")
        data = _get_energy_data_from_database(space_id=target_space_dev)
        if data:
            st.success("✅ Query Successful!")
            st.write(f"Heating: {data.get('heating', {}).get('total_energy_kwh', 0):.2f} kWh")
            st.write(f"Cooling: {data.get('cooling', {}).get('total_energy_kwh', 0):.2f} kWh")
            if 'zone_energy' in data:
                st.write("Zones detected:")
                for zone_id, zone_data in data['zone_energy'].items():
                    st.write(f"- {zone_id}: {zone_data.get('heating_kwh', 0):.2f} kWh heating, {zone_data.get('cooling_kwh', 0):.2f} kWh cooling")
        else:
            st.warning(f"⚠️ No energy simulation data found for space_id = {selected_space_dev if selected_space_dev else 'All Spaces'}")

    # Reset and cache management buttons
    reset_cache_col1, reset_cache_col2 = st.columns(2)

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
        st.write("- All measurements, predictions, and models")
        st.write("- All energy simulation results")
        st.write("- All uploaded files and weather data")
        st.write("- All logs and reports")
        
        confirm_col1, confirm_col2 = st.columns(2)
        
        if confirm_col1.button("✅ Yes, Reset", type="primary"):
            st.session_state.reset_confirmation = False
            _reset_all()
            st.rerun()
            
        if confirm_col2.button("❌ Cancel"):
            st.session_state.reset_confirmation = False
            st.rerun()
# add UniSystems logo
if UNIS_LOGO.exists():
    import base64
    
    # Convert images to base64 for HTML embedding
    with open(UNIS_LOGO, "rb") as f:
        unis_logo_b64 = base64.b64encode(f.read()).decode()
    
    st.sidebar.markdown(
            f"""
            <div style="display: flex; justify-content: center; align-items: center; gap: 10px;">
                <a href="https://www.unisystems.com/" target="_blank">
                    <img src="data:image/png;base64,{unis_logo_b64}" width="150">
                </a>
            </div>
            """,
        unsafe_allow_html=True
    )

# EU logo and funding info at bottom
if EU_LOGO.exists():
    # st.sidebar.markdown('---')
    # Convert images to base64 for HTML embedding
    with open(EU_LOGO, "rb") as f:
        eu_logo = base64.b64encode(f.read()).decode()
    # st.sidebar.markdown('---')
    st.sidebar.markdown(
        f"""
        <div style="display: flex; align-items: center; gap: 15px;">
            <img src="data:image/png;base64,{eu_logo}" alt="EU Logo" width="50">
            <span style="font-size:12px; text-align: justify;">
                Funded by the EU (Grant No. 101147722)
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

# ---------------------------------------------------------------------------
# Display name helpers
# ---------------------------------------------------------------------------
DISPLAY = {
    "time_end": "Timestamp",

    # ---- Measurement labels
    "temperature_c": "Indoor Temperature (°C)",
    "rh_percent": "Indoor Rel. Humidity (%)",
    "luminance_lux": "Luminance (lux)",
    "average_noise_db": "Avg Noise (dB)",
    "peak_db": "Peak Noise (dB)",
    "co_ppm":  "CO (ppm)",
    "co2_ppm": "CO₂ (ppm)",
    "pm2_5_ugm3": "PM₂.₅ (µg/m³)",
    "pm10_ugm3": "PM10 (µg/m³)",
    "tvoc_ppb": "TVOC (ppb)",

    # --- Predicted measurement labels (new naming convention)
    "pred_temperature_c": "Indoor Temperature (°C)",
    "pred_rh_percent": "Indoor Rel. Humidity (%)",
    "pred_luminance_lux": "Luminance (lux)",
    "pred_average_noise_db": "Avg Noise (dB)",
    "pred_peak_db": "Peak Noise (dB)",
    "pred_co_ppm": "CO (ppm)",
    "pred_co2_ppm": "CO₂ (ppm)",
    "pred_pm2_5_ugm3": "PM₂.₅ (μg/m³)",
    "pred_pm10_ugm3": "PM10 (μg/m³)",
    "pred_tvoc_ppb": "TVOC (ppb)",

    # --- Comfort labels
    "PMV_pred":         "Predicted PMV",
    "PPD_pred":         "Predicted PPD (%)",
    "vis_score_pred":   "Visual Score",
    "annoy_pred":       "Annoyance Level",
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
    "pm10_ugm3_class":      "PM10",
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
    """Draw line+marker chart for time-series data."""
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
            y=alt.Y("value:Q", title=""),
            color=alt.Color("Series", scale=alt.Scale(domain=["Observed", "Predicted"])),
            order="order:Q",
            opacity=alt.condition(alt.datum.Series == "Predicted", alt.value(0.7), alt.value(1)),
        )
        .properties(title=title)
        .interactive()
    )
    st.altair_chart(line, width='stretch')


# ---------------------------------------------------------------------------
# Comfort class time-series
# ---------------------------------------------------------------------------
def _class_timeseries(df: pd.DataFrame, cols: list[str], *, title: str):
    """Draw a line/step chart of class evolution over time."""
    logger.debug(f"Creating class timeseries for {title} with {len(df)} records and columns: {cols}")
    
    if not cols:
        logger.warning(f"No columns available for {title}")
        st.info(f"No {title.lower()} data"); return

    logger.debug("Preparing data for timeseries chart...")
    # tidy: Timestamp | Series | Class
    tmp = (df[["time_end"] + cols]
           .rename(columns={"time_end": "Timestamp"})
           .melt("Timestamp", var_name="Series", value_name="Class")
           .dropna())

    if tmp.empty:
        logger.warning(f"No data available after processing for {title}")
        st.info(f"No {title.lower()} data"); return

    logger.debug(f"Creating Altair chart for {title} with {len(tmp)} data points...")
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
                       axis=alt.Axis(title="")),
               color="Series:N",
           )
           .properties(title=title)
           .interactive()
    )
    logger.debug(f"Displaying timeseries chart for {title}...")
    st.altair_chart(chart, width='stretch')
    logger.debug(f"Timeseries chart displayed successfully for {title}")

def _pie_chart(df: pd.DataFrame, class_col: str, *, title: str, context: str = "default") -> None:
    """Draw a pie chart of comfort-class distribution."""
    logger.debug(f"Starting pie chart generation for {class_col} with {len(df)} records")
    
    if class_col not in df.columns:
        logger.warning(f"Column {class_col} not found in dataframe. Available columns: {list(df.columns)}")
        st.info(f"No {title.lower()} data")
        return

    logger.debug(f"Calculating value counts for {class_col}...")
    # --- counts -----------------------------------------------------------
    counts = (df[class_col]
              .dropna()
              .value_counts()
            #   .sort_index()
               .reindex(["A","B","C","D","NC"], fill_value=0)
              .reset_index()
              .rename(columns={class_col: "Class"}))
    counts["Share"] = counts["count"] / counts["count"].sum()
    logger.debug(f"Value counts calculated: {len(counts)} classes")

    logger.debug(f"Building legend labels for {class_col}...")
    # --- build legend labels "A (limits)" ---------------------------------
    limits = _LIMITS.get(class_col, {})
    counts["Label"] = counts["Class"].apply(
        lambda c: f"{c} ({limits.get(c,'')})" if c in limits else c
    )

    logger.debug(f"Creating Altair chart for {class_col}...")
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
                    orient    = "bottom",      # Position legend below the chart
                    columns   = 1,             # Use single column layout
                    titleAnchor = "start",     # Align title to the left
                    labelLimit = 200,          # Allow longer labels
                         ),
               ),
               tooltip=[
                   "Label:N",
                   alt.Tooltip("Share:Q", format=".0%")
               ],
            )
    )
    logger.debug(f"Displaying Altair chart for {class_col}...")
    st.altair_chart(chart, width='stretch')
    logger.debug(f"Chart displayed successfully for {class_col}")

def _stacked_bar_chart(df: pd.DataFrame, class_col: str, *, title: str, context: str = "default") -> None:
    """Draw a horizontal stacked bar chart of comfort-class distribution."""
    logger.debug(f"Starting stacked bar chart generation for {class_col} with {len(df)} records")
    
    if class_col not in df.columns:
        logger.warning(f"Column {class_col} not found in dataframe. Available columns: {list(df.columns)}")
        st.info(f"No {title.lower()} data")
        return

    logger.debug(f"Calculating value counts for {class_col}...")
    # --- counts -----------------------------------------------------------
    counts = (df[class_col]
              .dropna()
              .value_counts()
               .reindex(["A","B","C","D","NC"], fill_value=0)
              .reset_index()
              .rename(columns={class_col: "Class"}))
    
    # Filter out classes with zero counts for better visualization
    counts = counts[counts["count"] > 0]
    counts["Share"] = counts["count"] / counts["count"].sum()
    logger.debug(f"Value counts calculated: {len(counts)} classes")

    logger.debug(f"Building legend labels for {class_col}...")
    # --- build legend labels "A (limits)" ---------------------------------
    limits = _LIMITS.get(class_col, {})
    counts["Label"] = counts["Class"].apply(
        lambda c: f"{c} ({limits.get(c,'')})" if c in limits else c
    )

    logger.debug(f"Creating Altair stacked bar chart for {class_col}...")
    
    # Add a dummy category for the stacked bar
    counts["Category"] = title
    
    # Create cumulative positions for stacking
    counts = counts.sort_values("Class")  # Ensure consistent ordering
    counts["cumulative_start"] = counts["Share"].cumsum() - counts["Share"]
    counts["cumulative_end"] = counts["Share"].cumsum()
    
    # stable ordering A,B,C,D,NC → keeps colours fixed
    order = list(_LIMITS[class_col].keys())
    available_classes = counts["Class"].tolist()
    order = [c for c in order if c in available_classes]  # Filter to available classes
    palette = _COLOURS[:len(order)]

    chart = (
        alt.Chart(counts, height=80, width=600)
        .mark_bar(height=40)
        .encode(
            x=alt.X("cumulative_start:Q", title="", scale=alt.Scale(domain=[0, 1])),
            x2=alt.X2("cumulative_end:Q"),
            y=alt.Y("Category:N", title="", axis=alt.Axis(labels=False, ticks=False)),
            color=alt.Color(
                "Label:N",
                sort=[f"{c} ({limits.get(c,'')})" for c in order],
                scale=alt.Scale(
                    domain=[f"{c} ({limits.get(c,'')})" for c in order],
                    range=[_COLOURS[order.index(c)] for c in order],
                ),
                legend=alt.Legend(
                    title=title,
                    orient="bottom",
                    columns=min(len(order), 5),  # Limit columns for better layout
                    labelFontSize=11,
                    titleFontSize=12
                ),
            ),
            tooltip=[
                alt.Tooltip("Label:N", title="Class"),
                alt.Tooltip("count:Q", title="Count"),
                alt.Tooltip("Share:Q", format=".1%", title="Percentage")
            ],
        )
        .resolve_scale(color='independent')
    )
    
    logger.debug(f"Displaying Altair stacked bar chart for {class_col}...")
    st.altair_chart(chart, width='stretch')
    
    # Show summary statistics below the chart
    col1, col2, col3 = st.columns(3)
    total_records = counts["count"].sum()
    with col1:
        st.metric("Total Records", f"{total_records:,}")
    if len(counts) > 0:
        with col2:
            best_class = counts.loc[counts["count"].idxmax()]
            st.metric("Most Common", f"{best_class['Class']} ({best_class['Share']:.1%})")
        with col3:
            if "A" in available_classes:
                class_a_share = counts[counts["Class"] == "A"]["Share"].iloc[0]
                st.metric("Class A (Best)", f"{class_a_share:.1%}")
            else:
                st.metric("Class A (Best)", "0%")
    
    logger.debug(f"Chart displayed successfully for {class_col}")
    logger.debug(f"Stacked bar chart generation completed for {class_col}")


def _generate_iaq_report(df: pd.DataFrame):
    """Generate automatic IAQ report based on comfort classes and thresholds."""
    
    # IAQ Explainer
    st.markdown("### 📊 IAQ Assessment Method")
    st.info("""
    **Evaluation Method:** Indoor Air Quality is assessed using concentration thresholds for key pollutants: 
    CO₂ levels (ppm), CO levels (ppm), TVOC emissions (ppb), and particulate matter PM2.5 & PM10 (μg/m³). 
    Each parameter is classified into comfort classes A (excellent) through D (poor) based on established health and comfort standards.
    """)
    
    # Calculate IAQ metrics from available data
    iaq_fields = ["co2_ppm_class", "co_ppm_class", "tvoc_ppb_class", "pm2_5_ugm3_class", "pm10_ugm3_class"]
    available_fields = [f for f in iaq_fields if f in df.columns]
    
    if not available_fields:
        st.info("No IAQ data available for analysis.")
        return
    
    # Performance Report
    st.markdown("### 📈 IAQ Performance Report")
    
    total_records = len(df)
    overall_compliance = []
    worst_param = None
    worst_compliance = 100
    
    # Parameter-specific analysis
    param_names = {
        'co2_ppm_class': 'CO₂',
        'co_ppm_class': 'CO', 
        'tvoc_ppb_class': 'TVOC',
        'pm2_5_ugm3_class': 'PM2.5',
        'pm10_ugm3_class': 'PM10'
    }
    
    for field in available_fields:
        if field in df.columns:
            class_counts = df[field].value_counts()
            total_valid = class_counts.sum()
            
            if total_valid > 0:
                # Classes A and B are considered compliant
                compliant = class_counts.get('A', 0) + class_counts.get('B', 0)
                compliance_pct = (compliant / total_valid) * 100
                overall_compliance.append(compliance_pct)
                
                param_name = param_names.get(field, field)
                
                # Track worst performing parameter
                if compliance_pct < worst_compliance:
                    worst_compliance = compliance_pct
                    worst_param = param_name
                
                # Poor performance analysis (including NC as non-compliant)
                poor_classes = class_counts.get('C', 0) + class_counts.get('D', 0) + class_counts.get('NC', 0)
                poor_pct = (poor_classes / total_valid) * 100
                
                with st.expander(f"🔍 {param_name} Analysis"):
                    st.write(f"**Compliance Rate:** {compliance_pct:.1f}% of measurements met acceptable standards (Classes A-B)")
                    
                    if poor_pct > 20:
                        st.warning(f"**Concern:** {poor_pct:.1f}% of measurements showed poor air quality, indicating potential health risks.")
                    elif poor_pct > 10:
                        st.info(f"**Moderate Issues:** {poor_pct:.1f}% of measurements were suboptimal.")
                    else:
                        st.success(f"**Good Performance:** Only {poor_pct:.1f}% of measurements were suboptimal.")
    
    # Overall Summary
    if overall_compliance:
        avg_compliance = sum(overall_compliance) / len(overall_compliance)
        
        st.markdown("### 🎯 Overall IAQ Summary")
        
        if avg_compliance >= 80:
            st.success(f"**Good Overall IAQ:** Average compliance rate of {avg_compliance:.1f}% indicates generally healthy indoor air quality.")
        elif avg_compliance >= 60:
            st.warning(f"**Moderate IAQ:** Average compliance rate of {avg_compliance:.1f}% suggests room for improvement in air quality management.")
        else:
            st.error(f"**Poor IAQ:** Average compliance rate of {avg_compliance:.1f}% indicates significant air quality issues requiring immediate attention.")
        
        # Main limitation identification
        if worst_param:
            st.info(f"**Main Limitation:** {worst_param} shows the poorest performance with {worst_compliance:.1f}% compliance rate.")


def _generate_thermal_report(df: pd.DataFrame):
    """Generate automatic thermal comfort report."""
    st.markdown("### 📊 Thermal Comfort Assessment Method")
    st.info("""
    **Evaluation Method:** Thermal comfort is evaluated using Predicted Mean Vote (PMV) and Predicted Percentage Dissatisfied (PPD) indices. 
    PMV ranges from -3 (cold) to +3 (hot) with ±0.5 being acceptable, while PPD indicates the percentage of people likely to be dissatisfied.
    """)
    
    if 'thermal_class' not in df.columns:
        st.info("No thermal comfort data available for analysis.")
        return
    
    class_counts = df['thermal_class'].value_counts()
    total_valid = class_counts.sum()
    
    if total_valid == 0:
        st.info("No valid thermal comfort data available.")
        return
    
    compliant = class_counts.get('A', 0) + class_counts.get('B', 0)
    compliance_pct = (compliant / total_valid) * 100
    poor_pct = (class_counts.get('C', 0) + class_counts.get('D', 0) + class_counts.get('NC', 0)) / total_valid * 100
    
    st.markdown("### 📈 Thermal Performance Report")
    st.write(f"**Compliance Rate:** {compliance_pct:.1f}% of conditions met acceptable thermal comfort standards (Classes A-B)")
    
    if poor_pct > 20:
        st.warning(f"**Significant Discomfort:** {poor_pct:.1f}% of conditions caused thermal dissatisfaction, indicating inadequate HVAC control.")
    elif poor_pct > 10:
        st.info(f"**Moderate Issues:** {poor_pct:.1f}% of conditions were suboptimal for thermal comfort.")
    else:
        st.success(f"**Good Performance:** Only {poor_pct:.1f}% of conditions were thermally uncomfortable.")


def _generate_visual_report(df: pd.DataFrame):
    """Generate automatic visual comfort report."""
    st.markdown("### 📊 Visual Comfort Assessment Method")
    st.info("""
    **Evaluation Method:** Visual comfort is assessed using illuminance levels (lux) measured at work surfaces. 
    Optimal ranges balance adequate task lighting (200-700 lux) while avoiding glare and eye strain from excessive brightness.
    """)
    
    if 'visual_class' not in df.columns:
        st.info("No visual comfort data available for analysis.")
        return
    
    class_counts = df['visual_class'].value_counts()
    total_valid = class_counts.sum()
    
    if total_valid == 0:
        st.info("No valid visual comfort data available.")
        return
    
    compliant = class_counts.get('A', 0) + class_counts.get('B', 0)
    compliance_pct = (compliant / total_valid) * 100
    poor_pct = (class_counts.get('C', 0) + class_counts.get('D', 0) + class_counts.get('NC', 0)) / total_valid * 100
    
    st.markdown("### 📈 Visual Performance Report")
    st.write(f"**Compliance Rate:** {compliance_pct:.1f}% of conditions provided adequate lighting (Classes A-B)")
    
    if poor_pct > 25:
        st.warning(f"**Lighting Issues:** {poor_pct:.1f}% of conditions had inadequate or excessive illumination.")
    else:
        st.success(f"**Good Lighting:** Only {poor_pct:.1f}% of conditions were visually uncomfortable.")


def _generate_acoustic_report(df: pd.DataFrame):
    """Generate automatic acoustic comfort report."""
    st.markdown("### 📊 Acoustic Comfort Assessment Method")
    st.info("""
    **Evaluation Method:** Acoustic comfort is evaluated using A-weighted equivalent sound levels (LAeq) in decibels. 
    Classifications range from Class A (<35 dB, excellent) to Class D (≥65 dB, poor) based on suitability for concentration and communication.
    """)
    
    if 'acoustic_class' not in df.columns:
        st.info("No acoustic comfort data available for analysis.")
        return
    
    class_counts = df['acoustic_class'].value_counts()
    total_valid = class_counts.sum()
    
    if total_valid == 0:
        st.info("No valid acoustic comfort data available.")
        return
    
    compliant = class_counts.get('A', 0) + class_counts.get('B', 0) + class_counts.get('C', 0)
    compliance_pct = (compliant / total_valid) * 100
    poor_pct = (class_counts.get('D', 0) + class_counts.get('NC', 0)) / total_valid * 100
    
    st.markdown("### 📈 Acoustic Performance Report")
    st.write(f"**Compliance Rate:** {compliance_pct:.1f}% of conditions maintained acceptable noise levels (Classes A-C: <65 dB)")
    
    if poor_pct > 15:
        st.warning(f"**Noise Issues:** {poor_pct:.1f}% of conditions exceeded 65 dB, likely causing concentration difficulties.")
    else:
        st.success(f"**Good Acoustic Environment:** Only {poor_pct:.1f}% of conditions were acoustically disruptive.")


def _generate_overall_comfort_report(df: pd.DataFrame):
    """Generate comprehensive comfort analysis report for Energy Comfortness section."""
    
    st.markdown("### 📊 Overall Comfort Assessment")
    st.info("""
    **Evaluation Method:** Overall comfort integrates thermal (PMV/PPD), visual (lux), acoustic (dB), and air quality (ppm/μg/m³) metrics. 
    Each domain is classified into comfort classes A-D, with an aggregate comfort score representing the combined indoor environmental quality.
    """)
    
    # Analyze available comfort domains
    comfort_domains = {
        'thermal_class': 'Thermal',
        'visual_class': 'Visual', 
        'acoustic_class': 'Acoustic',
        'co2_ppm_class': 'CO₂',
        'tvoc_ppb_class': 'TVOC',
        'pm2_5_ugm3_class': 'PM2.5'
    }
    
    available_domains = {field: name for field, name in comfort_domains.items() if field in df.columns}
    
    if not available_domains:
        st.info("No comfort analysis data available.")
        return
    
    st.markdown("### 📈 Multi-Domain Performance Report")
    
    total_records = len(df)
    domain_performance = {}
    
    # Analyze each available domain
    for field, domain_name in available_domains.items():
        if field in df.columns:
            class_counts = df[field].value_counts()
            total_valid = class_counts.sum()
            
            if total_valid > 0:
                # Classes A and B are considered acceptable
                compliant = class_counts.get('A', 0) + class_counts.get('B', 0)
                compliance_pct = (compliant / total_valid) * 100
                
                # Class A is excellent
                excellent_pct = (class_counts.get('A', 0) / total_valid) * 100
                
                # Classes C, D, and NC are poor (non-compliant)
                poor_classes = class_counts.get('C', 0) + class_counts.get('D', 0) + class_counts.get('NC', 0)
                poor_pct = (poor_classes / total_valid) * 100
                
                domain_performance[domain_name] = {
                    'compliance': compliance_pct,
                    'excellent': excellent_pct,
                    'poor': poor_pct,
                    'total_records': total_valid
                }
    
    # Overall summary
    if domain_performance:
        avg_compliance = sum(d['compliance'] for d in domain_performance.values()) / len(domain_performance)
        avg_excellent = sum(d['excellent'] for d in domain_performance.values()) / len(domain_performance)
        avg_poor = sum(d['poor'] for d in domain_performance.values()) / len(domain_performance)
        
        # Performance summary
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Average Compliance (A-B)", f"{avg_compliance:.1f}%")
        with col2:
            st.metric("Excellent Conditions (A)", f"{avg_excellent:.1f}%")
        with col3:
            st.metric("Poor Conditions (C-D)", f"{avg_poor:.1f}%")
        
        # Domain breakdown
        with st.expander("🔍 Domain-by-Domain Analysis"):
            for domain_name, metrics in domain_performance.items():
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.write(f"**{domain_name}**")
                with col2:
                    st.write(f"{metrics['compliance']:.1f}% compliant")
                with col3:
                    st.write(f"{metrics['excellent']:.1f}% excellent")
                with col4:
                    st.write(f"{metrics['poor']:.1f}% poor")
        
        # Overall assessment
        st.markdown("### 🎯 Integrated Comfort Summary")
        
        if avg_compliance >= 80 and avg_poor <= 10:
            st.success(f"**Excellent Overall Comfort:** {avg_compliance:.1f}% average compliance with only {avg_poor:.1f}% poor conditions across all comfort domains.")
        elif avg_compliance >= 70:
            st.success(f"**Good Overall Comfort:** {avg_compliance:.1f}% average compliance indicates satisfactory indoor environmental quality.")
        elif avg_compliance >= 50:
            st.warning(f"**Moderate Comfort Issues:** {avg_compliance:.1f}% average compliance suggests room for improvement across multiple comfort domains.")
        else:
            st.error(f"**Significant Comfort Deficiencies:** {avg_compliance:.1f}% average compliance indicates widespread indoor environmental quality issues.")
        
        # Identify worst performing domain
        worst_domain = min(domain_performance.items(), key=lambda x: x[1]['compliance'])
        best_domain = max(domain_performance.items(), key=lambda x: x[1]['compliance'])
        
        st.info(f"**Performance Range:** {best_domain[0]} performs best ({best_domain[1]['compliance']:.1f}% compliance) while {worst_domain[0]} shows the most issues ({worst_domain[1]['compliance']:.1f}% compliance).")
    
    # Overall comfort class analysis if available
    if 'overall_comfort_class' in df.columns:
        st.markdown("### 🏆 Overall Comfort Classification")
        overall_counts = df['overall_comfort_class'].value_counts()
        total_overall = overall_counts.sum()
        
        if total_overall > 0:
            excellent_overall = (overall_counts.get('A', 0) / total_overall) * 100
            good_overall = (overall_counts.get('B', 0) / total_overall) * 100
            acceptable_overall = (overall_counts.get('C', 0) / total_overall) * 100
            poor_overall = (overall_counts.get('D', 0) + overall_counts.get('NC', 0)) / total_overall * 100
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Excellent + Good (A-B)", f"{excellent_overall + good_overall:.1f}%")
            with col2:
                st.metric("Poor + Unclassified (D+NC)", f"{poor_overall:.1f}%")
            
            if excellent_overall + good_overall >= 70:
                st.success(f"**Strong Overall Performance:** {excellent_overall + good_overall:.1f}% of conditions achieve good or excellent overall comfort ratings.")
            elif acceptable_overall >= 60:
                st.info(f"**Acceptable Performance:** Most conditions ({excellent_overall + good_overall + acceptable_overall:.1f}%) meet at least minimum comfort standards.")
            else:
                st.warning(f"**Performance Concerns:** Only {excellent_overall + good_overall:.1f}% of conditions achieve good overall comfort ratings.")


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
if st.session_state.get("predicted"):
    # Safely get prediction DataFrame
    df_pred: pd.DataFrame = st.session_state.get("pred_df", pd.DataFrame())
    
    if df_pred.empty:
        st.warning("⚠️ No prediction data available. Please run simulation first.")
        st.stop()
    
    # Select based on space
    sel = st.session_state.get("space_filter", "")  # Changed from sensor_filter to space_filter
    if sel:
        # Use space_id instead of space_id for filtering
        if "space_id" in df_pred.columns:
            df_pred = df_pred[df_pred["space_id"] == sel]
        elif "space_id" in df_pred.columns:  # Fallback for legacy data
            df_pred = df_pred[df_pred["space_id"] == sel]
        logger.info("Plotting data for space %s", sel)
    
    # ---- Fetch actual measurements and merge with predictions ----
    with SessionLocal() as ses:
        measurement_rows = (
            ses.query(Measurement)
            .filter(
                Measurement.time_end.between(start_dt, end_dt),
                Measurement.space_id.in_(
                    [sel] if sel else _get_space_ids()
                )
            )
            .all()
        )
        
        if measurement_rows:
            # Convert Decimal objects to float to avoid PyArrow serialization issues
            df_obs = pd.DataFrame([{c.name: _convert_decimal_to_float(getattr(r, c.name)) for c in r.__table__.columns} for r in measurement_rows])
            # Filter by selected sensor if needed
            if sel:
                df_obs = df_obs[df_obs["space_id"] == sel]
            
            # Merge observations with predictions on time_end and space_id
            df_pred = pd.merge(
                df_pred, 
                df_obs[["time_end", "space_id", "temperature_c", "rh_percent", "luminance_lux", 
                       "average_noise_db", "peak_db", "co2_ppm", "pm2_5_ugm3", "tvoc_ppb", 
                       "co_ppm", "pm10_ugm3"]],
                on=["time_end", "space_id"],
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
                    comfort_query = comfort_query.filter(Weather.space_id == sel)
                
                comfort_results = comfort_query.all()
                
                if comfort_results:
                    logger.info(f"Found {len(comfort_results)} comfort records to merge")
                    
                    # Create comfort dataframe with standardized column names for line charts
                    comfort_df_data = []
                    for prediction, weather in comfort_results:
                        comfort_df_data.append({
                            'time_end': weather.time_end,
                            'space_id': weather.space_id,
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
                    
                    # Merge comfort data with predictions on time_end and space_id
                    df_pred = pd.merge(
                        df_pred, 
                        comfort_df,
                        on=["time_end", "space_id"],
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
            logger.exception(f"Error fetching comfort data for line charts: {e}", exc_info=True)
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

    # Initialize tab state management
    if 'active_tab' not in st.session_state:
        st.session_state.active_tab = 0
    
    # Check if we need to force Energy tab selection
    if st.session_state.get('keep_energy_tab', False):
        st.session_state.active_tab = 4  # Force Energy tab (index 4)
        st.success("🔄 **Energy Simulation Active** - Staying on Energy tab to show progress and results.")
        st.session_state.keep_energy_tab = False  # Reset flag
    
    # Create tab selector in sidebar for better control
    tab_names = ["Thermal", "Visual", "Acoustic", "IAQ", "Energy", "Energy Comfortness"]
    
    # setup tabs (they will always start from first tab, but we'll only show content for active tab)
    tabs = st.tabs(tab_names)
    domain_map = {
        "Thermal": ["temperature_c", "rh_percent", "PMV_pred", "PPD_pred"],
        "Visual": ["luminance_lux", "vis_score_pred"],
        "Acoustic": ["average_noise_db", "peak_db"],  # "annoy_pred" commented out until calculation is fixed
        "IAQ": ["co2_ppm", "pm2_5_ugm3", "tvoc_ppb"],
        "Energy": [],  # Will be handled separately
        "Energy Comfortness": [],  # Will be handled separately
    }
    for idx, (name, tab) in enumerate(zip(domain_map.keys(), tabs)):
        with tab:
            if name == 'Energy':
                st.header("⚡ Energy Simulation")
                st.markdown("Run detailed building energy simulations for comfort analysis.")
                
                # Check if simulation is running - workflow handled later in the code
                # Note: Do not use st.stop() here as it prevents the simulation workflow from executing
                
                # Check if we should prevent UI updates during simulation
                # Note: Removed st.stop() to allow simulation workflow to execute
                
                # Display latest simulation results
                def display_energy_simulation_results():
                    """Display energy simulation results for selected building."""
                    try:
                        latest_results = _get_latest_simulation_results()
                        selected_building_tab = st.session_state.get("building_filter", "").strip()
                        target_building = selected_building_tab if selected_building_tab else None
                        _display_energy_results(latest_results or {}, space_id=None, building_id=target_building)
                    except Exception as e:
                        logger.exception(f"Error displaying simulation results: {e}")
                
                display_energy_simulation_results()
                
                # Simulation workflow trigger - MUST come before UI logic
                if st.session_state.get('simulation_running', False):
                    logger.info("SIMULATION WORKFLOW TRIGGERED - Starting energy simulation pipeline")
                    logger.info(f"Session state: simulation_running={st.session_state.get('simulation_running')}")
                    logger.info(f"Available parameters: IFC={st.session_state.get('latest_ifc_path')}, Space={st.session_state.get('space_filter')}")
                    logger.info(f"Date range: {st.session_state.get('start_dt')} to {st.session_state.get('end_dt')}")
                    
                    st.subheader("🏃‍♂️ Running EnergyPlus Simulation")
                    st.info("⏳ Energy simulation in progress... This may take several minutes.")
                    
                    with st.spinner("🔄 Processing EnergyPlus simulation pipeline..."):
                        try:
                            # Get configuration values
                            latest_ifc_path = st.session_state.get('latest_ifc_path')
                            target_sensor = st.session_state.get('space_filter')
                            start_dt = st.session_state.get('start_dt')
                            end_dt = st.session_state.get('end_dt')
                            start = start_dt.date() if start_dt else date(2024, 1, 1)
                            end = end_dt.date() if end_dt else date(2024, 1, 31)
                            
                            # Convert dates for pipeline
                            start_datetime = datetime.combine(start, datetime.min.time())
                            end_datetime = datetime.combine(end, datetime.min.time())
                            
                            # Create progress indicators
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            # Step 1: Generate weather file
                            logger.info("Step 1: Generating weather file")
                            status_text.text("🌤️ Generating weather file...")
                            progress_bar.progress(25)
                            
                            from ece.pipeline_weather import generate_epw_for_location
                            lat = st.session_state.get('init_lat', 40.6401)
                            lon = st.session_state.get('init_lon', 22.9444)
                            epw_path = generate_epw_for_location(
                                space_id=target_sensor,
                                latitude=lat,
                                longitude=lon,
                                start=start_datetime,
                                end=end_datetime,
                                full_year=True
                            )
                            logger.info(f"Weather file generated: {epw_path}")
                            
                            # Step 2: Prepare IFC file
                            logger.info("Step 2: Preparing IFC file")
                            status_text.text("📁 Preparing IFC file...")
                            progress_bar.progress(50)
                            
                            ifc_path = Path(latest_ifc_path)
                            logger.info(f"Using IFC file: {ifc_path}")
                            
                            # Step 3: Run EnergyPlus simulation
                            logger.info("Step 3: Running EnergyPlus simulation")
                            status_text.text("🏃‍♂️ Running EnergyPlus simulation...")
                            progress_bar.progress(75)
                            
                            from ece.pipeline_eplus_wrapper import run_user_request
                            simulation_results = run_user_request(
                                ifc_file_path=ifc_path,
                                weather_file_path=epw_path,
                                sensor_id=target_sensor,  # Fixed: parameter name should be sensor_id
                                start_date=start_datetime.strftime('%Y-%m-%d'),
                                end_date=end_datetime.strftime('%Y-%m-%d'),
                                project_base_dir=Path("./eplus_sim")
                            )
                            
                            # Step 4: Store results
                            logger.info("Step 4: Storing simulation results")
                            status_text.text("💾 Storing simulation results...")
                            progress_bar.progress(90)
                            
                            if simulation_results.get("success", False):
                                storage_success = _store_energy_simulation_results(
                                    simulation_results, target_sensor, str(ifc_path), str(epw_path), end_date=end_datetime
                                )
                                if storage_success:
                                    progress_bar.progress(100)
                                    status_text.text("✅ Energy simulation completed successfully!")
                                    st.success("✅ **Simulation completed!** Results stored in database.")
                                else:
                                    st.warning("⚠️ Simulation completed but failed to store results")
                            else:
                                error_msg = simulation_results.get('error', 'Unknown error')
                                logger.exception(f"EnergyPlus simulation failed: {error_msg}")
                                st.error(f"❌ **Simulation failed:** {error_msg}")
                    
                        except Exception as e:
                            logger.exception(f"Error during energy simulation: {str(e)}", exc_info=True)
                            st.error(f"❌ **Simulation error:** {str(e)}")
                
                        finally:
                            # Always reset flags when simulation is done
                            st.session_state.simulation_running = False
                            st.session_state.prevent_rerun = False
                            st.session_state.keep_energy_tab = False
                            logger.info("Energy simulation workflow completed, flags reset")
                            # Auto-refresh to show results
                            st.rerun()
                
                if st.session_state.get('show_energy_simulation', True):
                    # Energy Simulation Interface
                    simulation_running = st.session_state.get('simulation_running', False)
                    
                    # Preserve Energy tab selection during simulation
                    if simulation_running or st.session_state.get('keep_energy_tab', False):
                        logger.debug("Energy simulation active - preserving Energy tab")
                        if st.session_state.get('active_tab', 0) != 4:  # Energy is index 4
                            logger.info("Forcing tab selection to Energy during simulation")
                            st.session_state.active_tab = 4  # Energy tab index
                        
                        st.success("🔄 **Energy Simulation Active** - Staying on Energy tab to show progress and results.")
                    
                    if simulation_running:
                        logger.debug("Showing simulation running message and stopping further UI rendering")
                        st.info("⚙️ **Energy simulation in progress...** Please wait for completion.")
                        st.stop()
                    
                    else:
                        # Main UI when simulation is NOT running
                        st.subheader("🏗️ Automated Multi-Building Energy Simulations")

                        # Trigger background batch scheduler sync
                        try:
                            from ece.batch_scheduler import run_batch_scheduler, discover_and_sync_ifc_jobs
                            from db.models import IFCSimulationJob

                            # Auto-sync jobs and check date range data availability
                            with SessionLocal() as ses:
                                discover_and_sync_ifc_jobs(ses)
                                
                                # Selected date range from sidebar
                                sel_start = st.session_state.get('start_dt')
                                sel_end = st.session_state.get('end_dt')
                                
                                if sel_start and hasattr(sel_start, 'date'):
                                    s_dt_val = datetime.combine(sel_start.date(), datetime.min.time())
                                else:
                                    s_dt_val = datetime(2026, 1, 1)

                                if sel_end and hasattr(sel_end, 'date'):
                                    e_dt_val = datetime.combine(sel_end.date(), datetime.max.time())
                                else:
                                    e_dt_val = datetime.now() + timedelta(days=14)

                                pending_jobs = ses.query(IFCSimulationJob).filter(IFCSimulationJob.status == "PENDING").count()

                                if pending_jobs > 0:
                                    with st.spinner(f"🔄 Executing automated EnergyPlus pipeline for {pending_jobs} pending building job(s)..."):
                                        run_batch_scheduler(start_date=s_dt_val, end_date=e_dt_val)
                                        st.cache_data.clear()
                                        st.rerun()

                                # Query all simulation jobs
                                all_jobs = ses.query(IFCSimulationJob).order_by(IFCSimulationJob.job_id.asc()).all()

                            if all_jobs:
                                st.markdown("#### 📋 Multi-IFC Building Job Registry")
                                job_table_data = []
                                for j in all_jobs:
                                    status_badge = "✅ OK" if j.status == "OK" else ("🏃 RUNNING" if j.status == "RUNNING" else ("❌ FAILED" if j.status == "FAILED" else "⏳ PENDING"))
                                    last_run_str = j.last_run_timestamp.strftime("%Y-%m-%d %H:%M:%S") if j.last_run_timestamp else "Never"
                                    duration_str = f"{j.last_run_duration_sec:.1f}s" if j.last_run_duration_sec else "-"
                                    job_table_data.append({
                                        "Building": j.building_name,
                                        "Folder": j.folder_name,
                                        "Status": status_badge,
                                        "Last Executed": last_run_str,
                                        "Duration": duration_str,
                                        "Log File": j.log_file_path or "-"
                                    })
                                st.dataframe(pd.DataFrame(job_table_data), use_container_width=True)
                            else:
                                st.info("ℹ️ No building directories found under `etc/ifc/`.")

                        except Exception as e:
                            logger.exception(f"Error checking batch scheduler status: {e}")
                            st.warning("⚠️ Batch scheduler auto-check running in background.")

                
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
                    st.info("**Note:** Detailed bim2sim logs appear here during simulation runs.")
                    
                    # Option to view recent log file
                    log_path = Path("./logs/dashboard.app.log")
                    if log_path.exists():
                        try:
                            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                                lines = f.readlines()
                                recent_lines = lines[-100:] if len(lines) > 100 else lines
                                
                            st.text_area(
                                "Recent application logs (last 100 lines):",
                                value=''.join(recent_lines),
                                height=300,
                                key="energy_logs"
                            )
                        except Exception as e:
                            st.error(f"Error reading log file: {e}")
                    else:
                        st.info("No log file found.")





            elif name == 'Energy Comfortness':
                st.header("⚡🌡️ Energy & Comfort Analysis")
                st.markdown("Correlate energy consumption with occupant comfort metrics.")
                
                # Get filtering parameters
                start_dt = st.session_state.get('start_dt', None)
                end_dt = st.session_state.get('end_dt', None)
                sel = st.session_state.get("space_filter", "").strip()
                space_filter_applied = bool(sel)
                
                # **Try to get energy data from database only**
                logger.info("Attempting to retrieve energy data from database")
                energy_data = _get_energy_data_from_database(space_id=sel if space_filter_applied else None)
                
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
                    st.info("⚡ Run an energy simulation to generate and store energy data.")
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
                        space_mask = comfort_data["space_id"] == sel
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
                                st.caption(f"🏠 Space: {sel}")
                            else:
                                st.caption("🏠 All spaces")
                            
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
                        
                        # ==== ENERGY STATISTICS OVERVIEW ====
                        st.markdown("#### 📊 Energy Overview")
                        
                        # Get energy statistics
                        total_heating = energy_data.get('heating', {}).get('total_energy_kwh', 0) if 'heating' in energy_data else 0
                        total_cooling = energy_data.get('cooling', {}).get('total_energy_kwh', 0) if 'cooling' in energy_data else 0
                        total_energy = total_heating + total_cooling
                        
                        peak_heating = energy_data.get('heating', {}).get('peak_rate_w', 0) if 'heating' in energy_data else 0
                        peak_cooling = energy_data.get('cooling', {}).get('peak_rate_w', 0) if 'cooling' in energy_data else 0
                        
                        # Statistics row
                        stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
                        
                        with stat_col1:
                            st.metric("Total Energy", f"{total_energy:,.1f} kWh")
                        with stat_col2:
                            st.metric("Total Heating", f"{total_heating:,.1f} kWh")
                        with stat_col3:
                            st.metric("Total Cooling", f"{total_cooling:,.1f} kWh")
                        with stat_col4:
                            heating_ratio = (total_heating / total_energy * 100) if total_energy > 0 else 0
                            st.metric("Heating Share", f"{heating_ratio:.1f}%")
                        
                        # ==== STACKED BAR CHART AND PEAK POWER ====
                        chart_col, peak_col = st.columns([2, 1])
                        
                        with chart_col:
                            if total_energy > 0:
                                # Create stacked bar chart data
                                bar_data = pd.DataFrame({
                                    'Energy Type': ['Heating', 'Cooling'],
                                    'Energy (kWh)': [total_heating, total_cooling],
                                    'Percentage': [heating_ratio, 100 - heating_ratio]
                                })
                                
                                # Filter out zero values for cleaner visualization
                                bar_data = bar_data[bar_data['Energy (kWh)'] > 0]
                                
                                # Create cumulative positions for stacking
                                bar_data["cumulative_start"] = bar_data["Percentage"].cumsum() - bar_data["Percentage"]
                                bar_data["cumulative_end"] = bar_data["Percentage"].cumsum()
                                bar_data["Category"] = "Energy Distribution"
                                
                                # Create horizontal stacked bar chart
                                energy_bar_chart = alt.Chart(bar_data, height=60, width=400).mark_bar(
                                    height=30
                                ).encode(
                                    x=alt.X('cumulative_start:Q', title="", scale=alt.Scale(domain=[0, 100])),
                                    x2=alt.X2('cumulative_end:Q'),
                                    y=alt.Y('Category:N', title="", axis=alt.Axis(labels=False, ticks=False)),
                                    color=alt.Color(
                                        'Energy Type:N',
                                        scale=alt.Scale(domain=['Heating', 'Cooling'], range=['#ff4444', '#4488ff']),
                                        legend=alt.Legend(
                                            title="Energy Type", 
                                            orient="bottom",
                                            columns=2,
                                            labelFontSize=11,
                                            titleFontSize=12
                                        )
                                    ),
                                    tooltip=[
                                        alt.Tooltip('Energy Type:N', title='Type'),
                                        alt.Tooltip('Energy (kWh):Q', title='Energy (kWh)', format='.1f'),
                                        alt.Tooltip('Percentage:Q', title='Share (%)', format='.1f')
                                    ]
                                ).properties(
                                    title='Heating vs Cooling Energy Distribution'
                                )
                                
                                st.altair_chart(energy_bar_chart, width='stretch')
                                
                                # Show energy breakdown as metrics
                                energy_col1, energy_col2 = st.columns(2)
                                with energy_col1:
                                    st.metric("🔥 Heating", f"{total_heating:,.1f} kWh", f"{heating_ratio:.1f}%")
                                with energy_col2:
                                    cooling_ratio = 100 - heating_ratio
                                    st.metric("❄️ Cooling", f"{total_cooling:,.1f} kWh", f"{cooling_ratio:.1f}%")
                            else:
                                st.info("No energy data available for energy distribution chart")
                        
                        with peak_col:
                            st.markdown("**Peak Power**")
                            st.metric("Peak Heating", f"{peak_heating/1000.0:,.2f} kW")
                            st.metric("Peak Cooling", f"{peak_cooling/1000.0:,.2f} kW")
                            
                            if peak_heating > 0 or peak_cooling > 0:
                                peak_total = max(peak_heating, peak_cooling) / 1000.0
                                st.metric("Peak Total", f"{peak_total:,.2f} kW")
                        
                        # ==== TIME SERIES CHARTS ====
                        st.markdown("#### 📈 Energy Time Series")
                        
                        # Get hourly data (initialize variables to avoid scope issues)
                        heating_hourly = []
                        cooling_hourly = []
                        
                        if 'heating' in energy_data:
                            heating_hourly = energy_data.get('heating', {}).get('hourly_data', [])
                        if 'cooling' in energy_data:
                            cooling_hourly = energy_data.get('cooling', {}).get('hourly_data', [])
                        
                        if heating_hourly or cooling_hourly:
                            # Create datetime range
                            if start_dt and end_dt:
                                chart_start = start_dt
                                chart_end = end_dt
                                max_hours = ((chart_end - chart_start).days + 1) * 24
                                num_hours = min(max(len(heating_hourly), len(cooling_hourly)), max_hours)
                                date_range = pd.date_range(start=chart_start, periods=num_hours, freq='H')
                            else:
                                chart_start = pd.Timestamp('2024-01-01')
                                num_hours = max(len(heating_hourly), len(cooling_hourly))
                                date_range = pd.date_range(start=chart_start, periods=num_hours, freq='H')
                            
                            # Create individual charts row
                            heat_col, cool_col = st.columns(2)
                            
                            # Heating Time Series
                            with heat_col:
                                if heating_hourly:
                                    # Ensure arrays have the same length
                                    min_len = min(len(heating_hourly), len(date_range))
                                    heating_df = pd.DataFrame({
                                        'Time': date_range[:min_len],
                                        'Power (kW)': [float(x) / 1000.0 for x in heating_hourly[:min_len]]
                                    })
                                    
                                    heating_chart = alt.Chart(heating_df).mark_line(
                                        color='#ff4444', strokeWidth=2
                                    ).encode(
                                        x=alt.X('Time:T', title='Date & Time', axis=alt.Axis(format='%d %b %H:%M', labelAngle=-45)),
                                        y=alt.Y('Power (kW):Q', title=''),
                                        tooltip=[
                                            alt.Tooltip('Time:T', title='Date & Time', format='%d %b %Y %H:%M'),
                                            alt.Tooltip('Power (kW):Q', title='Heating Power (kW)', format='.2f')
                                        ]
                                    ).properties(
                                        title='Heating Power Over Time',
                                        height=300
                                    )
                                    
                                    st.altair_chart(heating_chart, width='stretch')
                                else:
                                    st.info("No heating data available")
                            
                            # Cooling Time Series  
                            with cool_col:
                                if cooling_hourly:
                                    # Ensure arrays have the same length
                                    min_len = min(len(cooling_hourly), len(date_range))
                                    cooling_df = pd.DataFrame({
                                        'Time': date_range[:min_len],
                                        'Power (kW)': [float(x) / 1000.0 for x in cooling_hourly[:min_len]]
                                    })
                                    
                                    cooling_chart = alt.Chart(cooling_df).mark_line(
                                        color='#4488ff', strokeWidth=2
                                    ).encode(
                                        x=alt.X('Time:T', title='Date & Time', axis=alt.Axis(format='%d %b %H:%M', labelAngle=-45)),
                                        y=alt.Y('Power (kW):Q', title=''),
                                        tooltip=[
                                            alt.Tooltip('Time:T', title='Date & Time', format='%d %b %Y %H:%M'),
                                            alt.Tooltip('Power (kW):Q', title='Cooling Power (kW)', format='.2f')
                                        ]
                                    ).properties(
                                        title='Cooling Power Over Time',
                                        height=300
                                    )
                                    
                                    st.altair_chart(cooling_chart, width='stretch')
                                else:
                                    st.info("No cooling data available")
                            
                            # Combined Time Series
                            if heating_hourly and cooling_hourly:
                                st.markdown("#### 🔥❄️ Combined Heating & Cooling")
                                
                                # Create combined DataFrame
                                combined_data = []
                                max_len = min(len(heating_hourly), len(cooling_hourly), len(date_range))
                                
                                for i in range(max_len):
                                    timestamp = date_range[i]
                                    combined_data.append({
                                        'Time': timestamp,
                                        'Power (kW)': float(heating_hourly[i]) / 1000.0,
                                        'Type': 'Heating'
                                    })
                                    combined_data.append({
                                        'Time': timestamp,
                                        'Power (kW)': float(cooling_hourly[i]) / 1000.0,
                                        'Type': 'Cooling'
                                    })
                                
                                combined_df = pd.DataFrame(combined_data)
                                
                                # Create combined chart
                                combined_chart = alt.Chart(combined_df).mark_line(
                                    strokeWidth=2
                                ).encode(
                                    x=alt.X('Time:T', title='Date & Time', axis=alt.Axis(format='%d %b %H:%M', labelAngle=-45)),
                                    y=alt.Y('Power (kW):Q', title=''),
                                    color=alt.Color(
                                        'Type:N',
                                        scale=alt.Scale(domain=['Heating', 'Cooling'], range=['#ff4444', '#4488ff']),
                                        legend=alt.Legend(title="Energy Type")
                                    ),
                                    tooltip=[
                                        alt.Tooltip('Time:T', title='Date & Time', format='%d %b %Y %H:%M'),
                                        alt.Tooltip('Power (kW):Q', title='Power (kW)', format='.2f'),
                                        alt.Tooltip('Type:N', title='Energy Type')
                                    ]
                                ).properties(
                                    title='Combined Heating & Cooling Power Over Time',
                                    height=400
                                )
                                
                                st.altair_chart(combined_chart, width='stretch')
                        
                        else:
                            st.info("No hourly energy data available for time series charts")
                        
                    else:
                        st.info("ℹ️ No energy simulation data available in database.")
                        st.info("💡 Run an energy simulation to generate and store energy data.")
                
                # ==== COMFORT ANALYSIS TAB ====
                with energy_comfort_tabs[1]:
                    st.subheader("🌡️ Comfort Analysis")
                    
                    if comfort_data is not None and len(comfort_data) > 0:
                        logger.info(f"Processing comfort data with {len(comfort_data)} records")
                        
                        # Use full dataset for now
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
                                logger.info("Calculating overall comfort on-the-fly...")
                                temp_df = comfort_data_display.copy()
                                temp_df['overall_comfort'] = _calculate_overall_comfort(temp_df)
                                avg_overall = temp_df['overall_comfort'].mean() if temp_df['overall_comfort'].notna().any() else 0
                            st.metric("Overall Comfort", f"{avg_overall:.2f}", help="Weighted average of all comfort metrics (scale: 0-4, where 4 is best)")
                        
                        with col4:
                            comfort_score = comfort_data['vis_score_pred'].mean() if 'vis_score_pred' in comfort_data.columns else 0
                            st.metric("Visual Comfort", f"{comfort_score:.2f}")
                        
                        # with col5:
                        #     annoyance_level = comfort_data['annoy_pred'].mean() if 'annoy_pred' in comfort_data.columns else 0
                        #     st.metric("Acoustic Annoyance", f"{annoyance_level:.2f}")
                        
                        # Overall Comfort Analysis
                        if 'overall_comfort' in comfort_data.columns and comfort_data['overall_comfort'].notna().any():
                            st.markdown("#### 📊 Overall Comfort Analysis")
                            
                            # Create time series chart for overall comfort
                            chart_data = comfort_data_display[['time_end', 'overall_comfort']].copy()
                            chart_data = chart_data.dropna()
                            
                            if len(chart_data) > 0:
                                overall_chart = alt.Chart(chart_data).mark_line(
                                    point=True, strokeWidth=2
                                ).add_params(
                                    alt.selection_interval(bind='scales')
                                ).encode(
                                    x=alt.X('time_end:T', title='Time'),
                                    y=alt.Y('overall_comfort:Q', title='', scale=alt.Scale(domain=[0, 4])),
                                    tooltip=['time_end:T', 'overall_comfort:Q']
                                ).properties(
                                    title='Overall Comfort Score Over Time (Scale: 0-4, where 4 is best)'
                                )
                                
                                st.altair_chart(overall_chart, width='stretch')
                                
                                # Show interpretation
                                avg_comfort = comfort_data['overall_comfort'].mean()
                                if avg_comfort >= 3.5:
                                    st.success(f"🎉 **Excellent overall comfort** (Average: {avg_comfort:.2f}/4)")
                                elif avg_comfort >= 2.5:
                                    st.info(f"👍 **Good overall comfort** (Average: {avg_comfort:.2f}/4)")
                                elif avg_comfort >= 1.5:
                                    st.warning(f"⚠️ **Moderate overall comfort** (Average: {avg_comfort:.2f}/4)")
                                else:
                                    st.error(f"❌ **Poor overall comfort** (Average: {avg_comfort:.2f}/4)")
                            else:
                                st.info("ℹ️ Overall Comfort data not available.")
                        else:
                            st.info("ℹ️ Overall Comfort data not available. Run new predictions to generate this metric.")
                        
                        # Comfort Classes Distribution Analysis
                        st.markdown("---")
                        st.markdown("### 🏷️ Comfort Classes Distribution")
                        st.markdown("""
                        **Understanding Comfort Classification:**
                        - 🌡️ **Thermal**: Temperature and humidity comfort levels based on PMV/PPD predictions
                        - 👁️ **Visual**: Lighting comfort considering luminance levels and visual satisfaction
                        - 👂 **Acoustic**: Sound comfort based on noise levels and annoyance predictions  
                        - 🫁 **Air Quality**: Indoor air quality considering CO₂, PM2.5, and TVOC levels
                        - 🎯 **Overall**: Weighted combination of all comfort domains for holistic assessment
                        """)
                        
                        # Overall Comfort Class (most prominent)
                        if 'overall_comfort_class' in comfort_data.columns:
                            st.markdown("#### 🎯 Overall Comfort Classification")
                            st.markdown("*Comprehensive assessment combining all comfort domains*")
                            _pie_chart(comfort_data_display, 'overall_comfort_class', 
                                     title="Overall Comfort Distribution", context="energy_comfort_analysis")
                            st.markdown("---")
                        
                        # Grid of individual comfort class stacked bar charts
                        comfort_class_cols = ['thermal_class', 'visual_class', 'acoustic_class', 'iaq_class']
                        available_comfort_cols = [col for col in comfort_class_cols if col in comfort_data.columns]
                        
                        if available_comfort_cols:
                            st.markdown("#### 🔍 Individual Comfort Domain Classifications")
                            
                            # Create grid layout for comfort class stacked bar charts
                            if len(available_comfort_cols) == 4:
                                # 2x2 grid for all 4 domains
                                col1, col2 = st.columns(2)
                                col3, col4 = st.columns(2)
                                grid_cols = [col1, col2, col3, col4]
                            elif len(available_comfort_cols) == 3:
                                # 3 columns for 3 domains
                                col1, col2, col3 = st.columns(3)
                                grid_cols = [col1, col2, col3]
                            elif len(available_comfort_cols) == 2:
                                # 2 columns for 2 domains  
                                col1, col2 = st.columns(2)
                                grid_cols = [col1, col2]
                            else:
                                # Single column for 1 domain
                                grid_cols = [st.container()]
                            
                            # Display comfort class stacked bar charts in grid
                            for idx, class_col in enumerate(available_comfort_cols):
                                with grid_cols[idx]:
                                    # Add domain-specific context and icons
                                    if 'thermal' in class_col:
                                        st.markdown("**🌡️ Thermal Comfort**")
                                        st.caption("Temperature & humidity comfort levels")
                                    elif 'visual' in class_col:
                                        st.markdown("**👁️ Visual Comfort**") 
                                        st.caption("Lighting & luminance satisfaction")
                                    elif 'acoustic' in class_col:
                                        st.markdown("**👂 Acoustic Comfort*")
                                        st.caption("Noise levels & sound annoyance")
                                    elif 'iaq' in class_col:
                                        st.markdown("**🫁 Air Quality**")
                                        st.caption("CO₂, PM2.5, TVOC levels")
                                    
                                    # Create pie chart for this comfort domain
                                    _pie_chart(
                                        comfort_data_display, class_col,
                                        title=class_col.replace('_', ' ').title().replace('Iaq', 'IAQ'),
                                        context="energy_comfort_analysis"
                                    )
                            
            elif name == 'IAQ':
                # --- stacked-bar-chart
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

                        # render the pie chart for this IAQ metric inside that placeholder
                        with target:
                            _pie_chart(df_pred, class_col, title=DISPLAY.get(class_col, class_col), context="iaq")
                    # Generate IAQ report
                    _generate_iaq_report(df_pred)
            else:
                # single pie for Thermal / Visual / Acoustic
                pie_cols = st.columns([1, 3], gap="small")
                class_col = f"{name.lower()}_class"
                if class_col in df_pred.columns:
                    with pie_cols[0]:
                        _pie_chart(df_pred, class_col, title=f"{name} class", context=name.lower())
                    with pie_cols[1]:
                        # Generate domain-specific reports
                        if name == "Thermal":
                            _generate_thermal_report(df_pred)
                        elif name == "Visual":
                            _generate_visual_report(df_pred)
                        elif name == "Acoustic":
                            _generate_acoustic_report(df_pred)
                        else:
                            st.markdown(f"-- {name} Report --")
                    logger.debug("Rendered %s pie for column %s", name, class_col)
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
    st.title("Energy Comfortness Tool")
    if _is_system_configured():
        st.info("🔍 Use the sidebar to select spaces and set parameters, then click 'Predict' to generate comfort analysis.")
        
        # Check for training in progress and display spinner beneath the header
        if st.session_state.get("training", False):
            st.info("🤖 **Training Machine Learning Models**")
            with st.spinner("⏳ Training models in progress... This may take several minutes."):
                # Keep the spinner active while training is happening
                import time
                time.sleep(0.1)  # Small delay to show spinner
            st.stop()  # Prevent rest of UI from rendering during training
        
        # Check for training completion messages
        if st.session_state.get("training_success", False):
            st.success("🎉 **Model training completed successfully!** Ready for predictions.")
            # Clear the success flag after displaying
            del st.session_state["training_success"]
            
        if st.session_state.get("training_error"):
            st.error(f"❌ **Model training failed:** {st.session_state['training_error']}")
            st.info("Please check your data and try again. Ensure you have uploaded valid sensor data.")
            # Clear the error flag after displaying
            del st.session_state["training_error"]
        
        # Check for model-related errors and display them beneath the header
        if st.session_state.get("model_error") == "no_models_dir":
            st.error("🤖 **No Machine Learning Models Found**")
            st.info("""
            **To run predictions, you need to train ML models first:**
            
            1. 📊 **Upload sensor data** (CSV files with measurements)
            2. 🎯 **Click "Train Models"** in the sidebar to create prediction models
            3. ⏳ **Wait for training to complete** (this may take a few minutes)
            4. 🔮 **Then return here to run predictions**
            
            💡 **Tip:** The models directory will be created automatically during training.
            """)
            # Clear the error after displaying
            del st.session_state["model_error"]
            
        elif st.session_state.get("model_error") == "no_trained_models":
            st.error("🎯 **No Trained Models in Database**")
            st.info("""
            **The models directory exists, but no trained models were found in the database.**
            
            **Please:**
            1. 📊 **Ensure you have uploaded sensor data** (CSV files with measurements)
            2. 🎯 **Click "Train Models"** in the sidebar to train prediction models
            3. ✅ **Wait for training to complete successfully**
            
            """)
            # Clear the error after displaying
            del st.session_state["model_error"]
    else:
        st.info("🚀 Get started by uploading data using the 'Configure' button in the sidebar.")


