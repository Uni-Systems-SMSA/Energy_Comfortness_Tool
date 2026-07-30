# -*- coding: utf-8 -*-
"""
ece.energy_storage
==================

Database storage and output parsing routines for EnergyPlus simulation results.
Decoupled from Streamlit UI elements for headless batch processing.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from db.session import SessionLocal
from db.models import EnergyBuilding, EnergySpace, EnergyTimeSeries, Space
from ece.utils.logging import init_logger

logger = init_logger(__name__)


def _convert_decimal_to_float(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _get_simulation_year_from_epw(epw_file_path: Path) -> int:
    """Read the exact simulation year strictly from the EPW weather file."""
    if not epw_file_path.exists():
        raise FileNotFoundError(f"EPW weather file does not exist: {epw_file_path}")

    with open(epw_file_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith(('LOCATION', 'DESIGN', 'TYPICAL', 'GROUND', 'LEAP', 'DAYLIGHT', 'COMMENTS', 'HOLIDAYS', 'DATA PERIODS')):
                parts = line.split(",")
                if len(parts) > 1 and parts[0].strip().isdigit():
                    return int(parts[0].strip())

    raise ValueError(f"Could not parse valid simulation year from EPW file: {epw_file_path}")


def _load_space_names_from_csv(eplus_results_path: str) -> dict:
    try:
        results_dir = Path(eplus_results_path)
        space_csv_path = results_dir / "space.csv"
        if not space_csv_path.exists():
            export_dir = results_dir.parent.parent.parent
            space_csv_path = export_dir / "space.csv"

        if not space_csv_path.exists():
            return {}

        space_df = pd.read_csv(space_csv_path)
        if len(space_df.columns) < 3:
            return {}

        zone_id_col = space_df.columns[1]
        space_name_col = space_df.columns[2]
        valid_rows = space_df.dropna(subset=[zone_id_col, space_name_col])

        if len(valid_rows) == 0:
            return {}

        zone_ids_upper = valid_rows[zone_id_col].astype(str).str.upper()
        space_names = valid_rows[space_name_col].astype(str)
        return dict(zip(zone_ids_upper, space_names))
    except Exception as e:
        logger.warning(f"Error loading space names from CSV: {e}")
        return {}


def _parse_energyplus_outputs(results_dir: Path, epw_file_path: Optional[Path] = None) -> dict:
    if isinstance(results_dir, str):
        results_dir = Path(results_dir)

    logger.info(f"Parsing EnergyPlus outputs from directory: {results_dir}")
    energy_data: Dict[str, Any] = {}

    try:
        export_dir = results_dir.parent.parent.parent
        space_csv_path = export_dir / "space.csv"

        if space_csv_path.exists():
            try:
                space_df = pd.read_csv(space_csv_path)
                if len(space_df.columns) >= 3:
                    zone_id_col = space_df.columns[1]
                    space_name_col = space_df.columns[2]
                    valid_rows = space_df.dropna(subset=[zone_id_col, space_name_col])

                    if len(valid_rows) > 0:
                        zone_ids_upper = valid_rows[zone_id_col].astype(str).str.upper()
                        space_names = valid_rows[space_name_col].astype(str)
                        energy_data['space_names'] = dict(zip(zone_ids_upper, space_names))
            except Exception as e:
                logger.warning(f"Could not load space mapping from {space_csv_path}: {e}")

        eplusout_csv = results_dir / "eplusout.csv"
        if not eplusout_csv.exists():
            logger.error(f"eplusout.csv not found at {eplusout_csv}")
            return {}

        df = pd.read_csv(eplusout_csv)
        df.columns = df.columns.str.strip()

        date_col = [c for c in df.columns if "Date/Time" in c]
        if date_col:
            raw_dates = df[date_col[0]].astype(str).str.strip()
            
            # Resolve EPW file path strictly
            if not epw_file_path or not Path(epw_file_path).exists():
                weather_dir = results_dir.parent.parent.parent / "weather"
                if weather_dir.exists():
                    epw_files = list(weather_dir.glob("*.epw"))
                    if epw_files:
                        epw_file_path = max(epw_files, key=lambda p: p.stat().st_mtime)

            sim_year = _get_simulation_year_from_epw(Path(epw_file_path)) if epw_file_path else datetime.now().year
            parsed_timestamps = []
            for d_str in raw_dates:
                try:
                    parts = d_str.split()
                    month, day = [int(x) for x in parts[0].split('/')]
                    time_parts = parts[1].split(':')
                    hour = int(time_parts[0])
                    minute = int(time_parts[1])
                    if hour == 24:
                        dt = datetime(sim_year, month, day) + timedelta(days=1)
                    else:
                        dt = datetime(sim_year, month, day, hour, minute)
                    parsed_timestamps.append(dt)
                except Exception:
                    parsed_timestamps.append(pd.NaT)
            energy_data['timestamps'] = parsed_timestamps

        heating_cols = [c for c in df.columns if "Heating" in c or "Zone Air System Sensible Heating Energy" in c]
        cooling_cols = [c for c in df.columns if "Cooling" in c or "Zone Air System Sensible Cooling Energy" in c]

        heating_series = df[heating_cols].sum(axis=1) / 3600000.0 if heating_cols else pd.Series(0, index=df.index)
        cooling_series = df[cooling_cols].sum(axis=1) / 3600000.0 if cooling_cols else pd.Series(0, index=df.index)

        energy_data['heating'] = {
            'total_energy_kwh': float(heating_series.sum()),
            'hourly_data': heating_series.tolist(),
            'peak_rate_w': float(heating_series.max() * 1000.0) if len(heating_series) > 0 else 0.0
        }
        energy_data['cooling'] = {
            'total_energy_kwh': float(cooling_series.sum()),
            'hourly_data': cooling_series.tolist(),
            'peak_rate_w': float(cooling_series.max() * 1000.0) if len(cooling_series) > 0 else 0.0
        }

        # Parse per-zone energy data
        zone_energy: Dict[str, Any] = {}
        for col in df.columns:
            c = col.strip()
            is_heating_col = ('Heating Energy' in c) or ('Zone Air System Sensible Heating Energy' in c)
            is_cooling_col = ('Cooling Energy' in c) or ('Zone Air System Sensible Cooling Energy' in c)
            if (is_heating_col or is_cooling_col) and not c.startswith('Heating:') and not c.startswith('Cooling:'):
                raw_zone = c.split(':')[0].strip()
                zone_name = raw_zone.replace(' IDEAL LOADS AIR SYSTEM', '').strip()

                if zone_name not in zone_energy:
                    zone_energy[zone_name] = {'heating_kwh': 0.0, 'cooling_kwh': 0.0, 'hourly_heating': [], 'hourly_cooling': []}

                series_kwh = df[col] / 3600000.0
                if is_heating_col:
                    zone_energy[zone_name]['heating_kwh'] = float(series_kwh.sum())
                    zone_energy[zone_name]['hourly_heating'] = series_kwh.tolist()
                elif is_cooling_col:
                    zone_energy[zone_name]['cooling_kwh'] = float(series_kwh.sum())
                    zone_energy[zone_name]['hourly_cooling'] = series_kwh.tolist()

        energy_data['zone_energy'] = zone_energy
        return energy_data

    except Exception as e:
        logger.exception(f"Error parsing EnergyPlus outputs: {e}")
        return {}


def _store_energy_simulation_results(
    simulation_results: dict,
    space_id: str,
    ifc_file_path: str,
    epw_file_path: str,
    end_date: Optional[Any] = None,
    building_id: Optional[str] = None
) -> bool:
    logger.info(f"Storing energy simulation results for space: {space_id}, building: {building_id}")

    try:
        with SessionLocal() as session:
            space_record = session.query(Space).filter(Space.space_id == space_id).first()

            if not space_record:
                space_record = Space(
                    space_id=space_id,
                    building_id=building_id or f"building_{space_id}",
                    latitude=40.6401,
                    longitude=22.9444
                )
                session.add(space_record)
                session.flush()

            target_building_id = building_id or space_record.building_id

            if 'eplus_results_path' in simulation_results:
                actual_results_dir = Path(simulation_results['eplus_results_path'])
            elif 'project_path' in simulation_results:
                project_path = Path(simulation_results['project_path'])
                export_dir = project_path / "export" / "EnergyPlus" / "SimResults"
                if export_dir.exists():
                    result_dirs = [d for d in export_dir.iterdir() if d.is_dir()]
                    if result_dirs:
                        actual_results_dir = result_dirs[0]
                    else:
                        return False
                else:
                    return False
            else:
                return False

            energy_data = _parse_energyplus_outputs(actual_results_dir, epw_file_path=Path(epw_file_path))
            if not energy_data or ('heating' not in energy_data and 'cooling' not in energy_data):
                return False

            simulation_timestamp = datetime.now()
            target_end_dt = end_date

            if energy_data.get('timestamps') and len(energy_data['timestamps']) > 0:
                timestamps = [ts for ts in energy_data['timestamps'] if pd.notna(ts)]
                if target_end_dt and timestamps:
                    timestamps = [ts for ts in timestamps if ts <= target_end_dt]

                if timestamps:
                    simulation_start = timestamps[0]
                    simulation_end = timestamps[-1]
                else:
                    simulation_year = _get_simulation_year_from_epw(Path(epw_file_path)) if epw_file_path else 2024
                    simulation_start = datetime(simulation_year, 1, 1)
                    simulation_end = datetime(simulation_year, 12, 31)
            else:
                simulation_year = _get_simulation_year_from_epw(Path(epw_file_path)) if epw_file_path else 2024
                simulation_start = datetime(simulation_year, 1, 1)
                simulation_end = datetime(simulation_year, 12, 31)

            heating_timeseries = energy_data.get('heating', {}).get('hourly_data', [])
            cooling_timeseries = energy_data.get('cooling', {}).get('hourly_data', [])

            total_heating_kwh = sum(heating_timeseries) if heating_timeseries else energy_data.get('heating', {}).get('total_energy_kwh', 0)
            total_cooling_kwh = sum(cooling_timeseries) if cooling_timeseries else energy_data.get('cooling', {}).get('total_energy_kwh', 0)
            total_energy_kwh = total_heating_kwh + total_cooling_kwh

            peak_heating_w = max(heating_timeseries) * 1000.0 if heating_timeseries else energy_data.get('heating', {}).get('peak_rate_w', 0)
            peak_cooling_w = max(cooling_timeseries) * 1000.0 if cooling_timeseries else energy_data.get('cooling', {}).get('peak_rate_w', 0)

            zone_energy = energy_data.get('zone_energy', {})
            zones_count = len(zone_energy)

            weather_file_path = simulation_results.get('weather_file', epw_file_path)
            ifc_file_path_from_results = simulation_results.get('ifc_file', ifc_file_path)

            energy_building = EnergyBuilding(
                building_id=building_id,
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
            session.flush()

            space_names = energy_data.get('space_names', {})
            if not timestamps:
                num_data_points = max(len(heating_timeseries), len(cooling_timeseries))
                timestamps = [simulation_start + timedelta(hours=i) for i in range(num_data_points)]

            for zone_id, zone_data in zone_energy.items():
                zone_name = space_names.get(zone_id.upper(), zone_id)
                existing_space = session.query(Space).filter(Space.space_id == zone_name).first()
                if not existing_space:
                    # Auto-create space record so simulation results are persisted cleanly
                    existing_space = Space(
                        space_id=zone_name,
                        building_id=building_id,
                        latitude=space_record.latitude,
                        longitude=space_record.longitude
                    )
                    session.add(existing_space)
                    session.flush()

                energy_space = EnergySpace(
                    energy_building_id=energy_building.energy_building_id,
                    space_id=zone_name,
                    zone_id=zone_id,
                    zone_name=zone_name,
                    heating_kwh=zone_data.get('heating_kwh', 0.0),
                    cooling_kwh=zone_data.get('cooling_kwh', 0.0),
                    total_kwh=zone_data.get('heating_kwh', 0.0) + zone_data.get('cooling_kwh', 0.0)
                )
                session.add(energy_space)
                session.flush()

                h_data = zone_data.get('hourly_heating', [])
                c_data = zone_data.get('hourly_cooling', [])
                min_len = min(len(timestamps), max(len(h_data), len(c_data)))

                ts_objects = []
                for i in range(min_len):
                    h_val = h_data[i] if i < len(h_data) else 0.0
                    c_val = c_data[i] if i < len(c_data) else 0.0
                    ts_objects.append(EnergyTimeSeries(
                        energy_space_id=energy_space.energy_space_id,
                        timestamp=timestamps[i],
                        heating_power_w=h_val * 1000.0,
                        cooling_power_w=c_val * 1000.0,
                        heating_energy_kwh=h_val,
                        cooling_energy_kwh=c_val
                    ))

                if ts_objects:
                    session.bulk_save_objects(ts_objects)

            session.commit()
            logger.info("Successfully stored energy simulation results in database")
            return True

    except Exception as e:
        logger.exception(f"Error storing energy simulation results: {e}")
        return False
