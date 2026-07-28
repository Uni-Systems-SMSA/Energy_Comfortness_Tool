# -*- coding: utf-8 -*-
"""
pipeline_weather  –  create an EPW file **from the rows already stored**
in the `weather` table.

It relies on the same functions you already wrote in epw-generator.py
(convert_units, compute_relative_humidity, …) which we IMPORT instead
of copy-pasting.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np
import pytz

# --- original helpers reused -------------------------------------------
from ece.utils.epw import (
    convert_units,
)

# --- DB access ---------------------------------------------------------
import sys, os
sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))
from db.session import SessionLocal
from db.models  import Weather

from ece.utils.logging import init_logger
from ece.weather_api import fetch_open_meteo

logger = init_logger(__name__)

# Default paths
DEFAULT_EPW_TEMPLATE = Path(__file__).parent.parent / "etc" / "weather" / "template_fixed.epw"


# ---------------------------------------------------------------------
# Reverse geocoding utilities
# ---------------------------------------------------------------------
def get_location_info(latitude: float, longitude: float) -> dict:
    """
    Get location information from coordinates using reverse geocoding.
    Provides robust fallback handling for various failure scenarios.
    
    Args:
        latitude: Latitude in decimal degrees
        longitude: Longitude in decimal degrees
        
    Returns:
        dict: Location information with keys:
            - city: City name
            - state: State/province/region name  
            - country: Country name
            - country_code: 3-letter country code
            - wmo_id: WMO station identifier (generated)
    """
    # Default fallback values based on common coordinates
    fallback_info = {
        "city": "Unknown",
        "state": "Unknown", 
        "country": "Unknown",
        "country_code": "UNK",
        "wmo_id": "999999"
    }
    
    # Try to determine rough region from coordinates for better fallbacks
    if 35.0 <= latitude <= 42.0 and 19.0 <= longitude <= 28.0:
        # Greece region
        fallback_info.update({
            "city": "Greece_Location",
            "state": "Greece", 
            "country": "Greece",
            "country_code": "GRC",
            "wmo_id": "167140"  # Thessaloniki WMO ID
        })
    elif 40.0 <= latitude <= 45.0 and 19.0 <= longitude <= 30.0:
        # Balkans region
        fallback_info.update({
            "city": "Balkans_Location",
            "state": "Balkans",
            "country": "Balkan_Region", 
            "country_code": "EUR",
            "wmo_id": "150000"
        })
    
    try:
        # Attempt reverse geocoding with geopy
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderTimedOut, GeocoderUnavailable, GeocoderServiceError
        
        # Initialize with user agent and timeout
        geolocator = Nominatim(
            user_agent="energy_comfort_tool_epw_generator/1.0",
            timeout=10
        )
        
        logger.info(f"Attempting reverse geocoding for coordinates: {latitude:.4f}, {longitude:.4f}")
        
        # Perform reverse geocoding
        location = geolocator.reverse(f"{latitude}, {longitude}", language='en')
        
        if location and location.raw:
            address = location.raw.get('address', {})
            
            # Extract location components with fallbacks
            city = (address.get('city') or 
                   address.get('town') or 
                   address.get('village') or 
                   address.get('municipality') or
                   fallback_info['city'])
            
            state = (address.get('state') or 
                    address.get('region') or 
                    address.get('province') or
                    address.get('county') or
                    fallback_info['state'])
            
            country = address.get('country', fallback_info['country'])
            
            # Map country to ISO 3-letter code with fallbacks
            country_code = _get_country_code(country, fallback_info['country_code'])
            
            # Generate WMO-like ID from coordinates (not real WMO but valid format)
            wmo_id = _generate_wmo_id(latitude, longitude)
            
            result = {
                "city": city,
                "state": state,
                "country": country,
                "country_code": country_code,
                "wmo_id": wmo_id
            }
            
            logger.info(f"Reverse geocoding successful: {result}")
            return result
            
        else:
            logger.warning("Reverse geocoding returned no results, using fallback")
            
    except ImportError:
        logger.warning("geopy package not available, using fallback location info")
    except Exception as e:
        # Catch-all for any geocoding errors including timeout, unavailable, service errors
        logger.warning(f"Geocoding error: {e}, using fallback")
    
    # Generate WMO-like ID even for fallback
    fallback_info['wmo_id'] = _generate_wmo_id(latitude, longitude)
    logger.info(f"Using fallback location info: {fallback_info}")
    return fallback_info


def _get_country_code(country_name: str, fallback: str = "UNK") -> str:
    """Convert country name to 3-letter ISO code with fallbacks."""
    country_mapping = {
        'greece': 'GRC',
        'united states': 'USA', 
        'united kingdom': 'GBR',
        'germany': 'DEU',
        'france': 'FRA',
        'italy': 'ITA',
        'spain': 'ESP',
        'turkey': 'TUR',
        'bulgaria': 'BGR',
        'serbia': 'SRB',
        'albania': 'ALB',
        'north macedonia': 'MKD',
        'montenegro': 'MNE',
        'bosnia and herzegovina': 'BIH',
        'croatia': 'HRV',
        'slovenia': 'SVN',
    }
    
    country_lower = country_name.lower()
    return country_mapping.get(country_lower, fallback)


def _generate_wmo_id(latitude: float, longitude: float) -> str:
    """Generate a WMO-like 6-digit identifier from coordinates."""
    # Create a pseudo-WMO ID based on coordinates
    # Format: RRLLLL where RR is region code, LLLL is location-specific
    
    # Determine region code based on rough geographic regions
    if 35.0 <= latitude <= 70.0 and -10.0 <= longitude <= 50.0:
        region = "16"  # Europe
    elif 25.0 <= latitude <= 50.0 and 25.0 <= longitude <= 145.0:
        region = "38"  # Asia
    elif -40.0 <= latitude <= 40.0 and -20.0 <= longitude <= 55.0:
        region = "60"  # Africa
    elif 15.0 <= latitude <= 85.0 and -180.0 <= longitude <= -50.0:
        region = "70"  # North America
    elif -60.0 <= latitude <= 15.0 and -85.0 <= longitude <= -30.0:
        region = "80"  # South America
    else:
        region = "99"  # Other/Ocean
    
    # Generate location-specific 4-digit code from coordinates
    lat_code = int(abs(latitude * 100) % 100)
    lon_code = int(abs(longitude * 100) % 100) 
    location_code = f"{lat_code:02d}{lon_code:02d}"
    
    return f"{region}{location_code}"

# ---------------------------------------------------------------------
def create_epw_header(
    latitude: float,
    longitude: float,
    timezone: int = 2,  # UTC+2 for Greece
    elevation: float = 50.0,  # meters above sea level (Thessaloniki ~50m)
    location_name: str = None,
    country: str = None,
    data_source: str = "Open-Meteo API"
) -> list[str]:
    """
    Create proper EPW header lines that EnergyPlus can read.
    Uses reverse geocoding to get accurate location information.
    
    Args:
        latitude: Location latitude in decimal degrees
        longitude: Location longitude in decimal degrees  
        timezone: UTC offset (default 2 for Greece)
        elevation: Elevation above sea level in meters
        location_name: Override location name (if None, uses geocoding)
        country: Override country code (if None, uses geocoding)
        data_source: Description of data source
        
    Returns:
        List of header lines for EPW file
    """
    header_lines = []
    
    # Get location information via reverse geocoding with fallbacks
    if location_name is None or country is None:
        location_info = get_location_info(latitude, longitude)
        final_location_name = location_name or location_info['city']
        final_country = country or location_info['country_code']
        final_state = location_info['state']
        wmo_id = location_info['wmo_id']
    else:
        final_location_name = location_name
        final_country = country
        final_state = "Unknown"
        wmo_id = _generate_wmo_id(latitude, longitude)
    
    # Line 1: LOCATION - Fixed format with all 10 required fields
    # Format: LOCATION,City,State,Country,Source,WMO,Latitude,Longitude,TimeZone,Elevation
    header_lines.append(
        f"LOCATION,{final_location_name},{final_state},{final_country},TMY,{wmo_id},"
        f"{latitude:.4f},{longitude:.4f},{timezone:.1f},{elevation:.1f}\n"
    )
    
    # Line 2: DESIGN CONDITIONS - EnergyPlus requires proper format even if no data
    # Format: DESIGN CONDITIONS,1,heating design condition name,heating design drybulb,heating design dewpoint,heating design humidity,heating design pressure,cooling design condition name,cooling design drybulb,cooling design dewpoint,cooling design humidity,cooling design pressure
    header_lines.append("DESIGN CONDITIONS,1,Heating 99.6% Condns DB,-5.0,-999.9,-999.9,101325,Cooling .4% Condns DB=>MWB,35.0,22.0,65.5,101325\n")
    
    # Line 3: TYPICAL/EXTREME PERIODS - Provide minimal but valid structure
    header_lines.append("TYPICAL/EXTREME PERIODS,1,Summer,7/1,7/31,Summer Week Typical\n")
    
    # Line 4: GROUND TEMPERATURES - Use realistic values for Greece
    header_lines.append("GROUND TEMPERATURES,3,0.5,,,15.0,15.5,17.0,18.5,2.0,,,16.0,16.5,18.0,19.5,4.0,,,17.0,17.5,19.0,20.5\n")
    
    # Line 5: HOLIDAYS/DAYLIGHT SAVINGS
    header_lines.append("HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0\n")
    
    # Line 6: COMMENTS 1 (data source info)
    header_lines.append(f"COMMENTS 1,Weather data from {data_source} - Generated by ECE Weather Pipeline\n")
    
    # Line 7: COMMENTS 2 (additional info)
    header_lines.append("COMMENTS 2,Processed for building energy simulation - Full year real weather data\n")
    
    # Line 8: DATA PERIODS (1 period, starting Sunday)
    header_lines.append("DATA PERIODS,1,1,Data,Sunday,1/1,12/31\n")
    
    return header_lines


# ---------------------------------------------------------------------
def download_and_store_missing_weather(
    space_id: str,
    latitude: float,
    longitude: float,
    start: datetime,
    end: datetime
) -> None:
    """
    Download missing weather data from Open-Meteo API and store in database.
    
    Args:
        space_id: Space identifier for weather data
        latitude: Location latitude
        longitude: Location longitude
        start: Start datetime for missing data period
        end: End datetime for missing data period
    """
    logger.info(f"Downloading missing weather data for {space_id} from {start} to {end}")
    
    try:
        # Fetch data from Open-Meteo API
        # Ensure datetimes are timezone-aware (UTC)
        import pytz
        if start.tzinfo is None:
            start = pytz.UTC.localize(start)
        if end.tzinfo is None:
            end = pytz.UTC.localize(end)
            
        df = fetch_open_meteo(
            lat=latitude,
            lon=longitude,
            start=start,
            end=end
        )
        
        if df.empty:
            logger.warning(f"No weather data returned from API for period {start} to {end}")
            return
            
        logger.info(f"Downloaded {len(df)} weather records")
        logger.info(f"Temperature range: {df['temperature_2m'].min():.1f}°C to {df['temperature_2m'].max():.1f}°C")
        
        # Store in database
        with SessionLocal() as session:
            stored_count = 0
            for _, row in df.iterrows():
                try:
                    # Check if record already exists
                    existing = session.query(Weather).filter(
                        Weather.time_end == row['time_end'],
                        Weather.space_id == space_id
                    ).first()
                    
                    if existing is None:
                        # Create new record
                        weather_record = Weather(
                            time_end=row['time_end'],
                            space_id=space_id,
                            outdoor_temperature_2m=float(row['temperature_2m']),
                            outdoor_relative_humidity_2m=float(row['relative_humidity_2m']),
                            wind_speed_10m=float(row['wind_speed_10m']),
                            shortwave_radiation=float(row.get('shortwave_radiation', 0)),
                            direct_radiation=float(row.get('direct_radiation', 0)),
                            precipitation=float(row.get('precipitation', 0)),
                            cloud_cover=float(row.get('cloud_cover', 0)),
                            src=row.get('src', 'archive')
                        )
                        session.add(weather_record)
                        stored_count += 1
                    # If record exists, skip it (don't overwrite existing data)
                    
                except Exception as e:
                    logger.warning(f"Failed to store weather record for {row['time_end']}: {e}")
                    continue
            
            session.commit()
            logger.info(f"Successfully stored {stored_count} new weather records in database")
            
    except Exception as e:
        logger.exception(f"Failed to download weather data: {e}")
        raise


# ---------------------------------------------------------------------
def ensure_complete_weather_data(
    space_id: str,
    latitude: float,
    longitude: float,
    start: datetime,
    end: datetime
) -> None:
    """
    Ensure we have complete weather data for the requested period.
    Downloads missing data using both historical (archive) and forecast APIs.
    
    Args:
        space_id: Space identifier for weather data
        latitude: Location latitude  
        longitude: Location longitude
        start: Start datetime for required period
        end: End datetime for required period
    """
    logger.info(f"Ensuring complete weather data for {space_id} from {start} to {end}")
    
    # Open-Meteo supports:
    # - Archive API: any date before today
    # - Forecast API: today and up to ~15 days in the future
    today = datetime.now()
    max_forecast_date = today + pd.Timedelta(days=15)  # ~15 days forecast limit
    
    if start > max_forecast_date:
        logger.warning(f"Requested start date {start} is beyond forecast limit (~15 days). Cannot download data.")
        return
    
    # Limit end date to forecast API limits
    effective_end = min(end, max_forecast_date)
    if effective_end != end:
        logger.info(f"Limited end date from {end} to {effective_end} due to forecast API limits (~15 days)")
    
    with SessionLocal() as session:
        # Check what data we already have
        existing_count = (
            session.query(Weather)
            .filter(
                Weather.space_id == space_id,
                Weather.time_end.between(start, effective_end)
            )
            .count()
        )
        
        # Calculate expected hourly records
        expected_hours = int((effective_end - start).total_seconds() / 3600) + 1
        
        logger.info(f"Existing records: {existing_count}, Expected: {expected_hours}")
        
        if existing_count >= expected_hours * 0.95:  # Allow for 5% missing data
            logger.info("Sufficient weather data already exists")
            return
        
        # Download missing data (the fetch_open_meteo function handles archive vs forecast automatically)
        logger.info("Insufficient data found, downloading missing periods...")
        logger.info(f"Will use Archive API for dates before {today.date()} and Forecast API for {today.date()} onwards")
        
        download_and_store_missing_weather(
            space_id=space_id,
            latitude=latitude,
            longitude=longitude,
            start=start,
            end=effective_end
        )

# ---------------------------------------------------------------------
def _fetch_weather_rows(
        space_id: str,
        start: datetime,
        end:   datetime,
        ses
) -> pd.DataFrame:
    """
    Return a tidy DF whose **index is UTC time_end** and whose columns
    match the names your convert_units() function expects.
    """
    logger.info(f"Fetching weather data for space {space_id} from {start} to {end}")
    rows = (
        ses.query(Weather)
           .filter(Weather.space_id == space_id,
                   Weather.time_end.between(start, end))
           .order_by(Weather.time_end)
           .all()
    )
    if not rows:
        raise RuntimeError(f"No weather rows for space {space_id} in period {start} to {end}")

    logger.info(f"Found {len(rows)} weather rows")
    df = (
        pd.DataFrame([r.__dict__ for r in rows])
          .drop(columns=["_sa_instance_state", "weather_id", "space_id",
                         "src", "fetched_at"], errors='ignore')
          .rename(columns={
              # match names used in convert_units()
              "outdoor_temperature_2m":       "temperature_2m",
              "outdoor_relative_humidity_2m": "relative_humidity_2m",
              "wind_speed_10m":               "windspeed_10m",
          })
          .set_index("time_end")
          .sort_index()
    )
    
    # Fill missing columns with default values if they don't exist
    required_columns = [
        'temperature_2m', 'relative_humidity_2m', 'windspeed_10m', 
        'shortwave_radiation', 'direct_radiation', 'precipitation', 
        'cloud_cover', 'surface_pressure', 'dewpoint_2m', 'winddirection_10m', 'cloudcover'
    ]
    
    for col in required_columns:
        if col not in df.columns:
            if col == 'surface_pressure':
                df[col] = 1013.25  # standard atmospheric pressure in hPa
            elif col == 'dewpoint_2m':
                # Calculate dewpoint from temperature and RH if not available
                if 'temperature_2m' in df.columns and 'relative_humidity_2m' in df.columns:
                    df[col] = df['temperature_2m'] - ((100 - df['relative_humidity_2m']) / 5)
                else:
                    df[col] = 0
            elif col == 'winddirection_10m':
                df[col] = 0  # default wind direction
            elif col == 'cloudcover':
                df[col] = df.get('cloud_cover', 0)  # use cloud_cover if available, else 0
            else:
                df[col] = 0  # default value for missing columns
    
    logger.info(f"Weather dataframe shape: {df.shape}, columns: {list(df.columns)}")
    return df


# ---------------------------------------------------------------------
def build_epw_from_db(
        space_id: str,
        start: datetime,
        end: datetime,
        *,
        latitude: float,
        longitude: float,
        output_path: Path,
        epw_template: Optional[Path] = None,
        missing_value: int = 999999,
        data_flags: Optional[Dict[str, int]] = None,
) -> Path:
    """
    Generate an EPW file from weather data stored in the database.
    
    Args:
        space_id: Space identifier for weather data
        start: Start datetime for data period
        end: End datetime for data period
        latitude: Location latitude for solar calculations
        longitude: Location longitude (for future use)
        output_path: Path where EPW file will be written
        epw_template: Path to EPW header template (uses default if None)
        missing_value: Value to use for missing data fields
        data_flags: Dict with 'source' and 'uncertainty' flags
        
    Returns:
        Path to the generated EPW file
    """
    # Set default data flags
    if data_flags is None:
        data_flags = {"source": 0, "uncertainty": 0}
    
    # Create configuration dict for convert_units function
    cfg = {
        'missing_value': missing_value,
        'header': {
            'latitude': latitude,
            'longitude': longitude
        },
        'data_flags': data_flags
    }

    # ---- 1) DB - Fetch weather data -------------------------------------------------------
    with SessionLocal() as ses:
        df_raw = _fetch_weather_rows(space_id, start, end, ses)

    # ---- 2) Convert units / derived fields ---------------------------
    logger.info("Converting weather data to EPW format")
    df_epw = convert_units(df_raw, cfg)

    # ---- 3) Create EPW header from scratch ----------------------------------------------------
    logger.info(f"Creating EPW header for location: {latitude:.4f}, {longitude:.4f}")
    header_lines = create_epw_header(
        latitude=latitude,
        longitude=longitude,
        data_source="Database + Open-Meteo API"
    )

    # ---- 4) Write EPW file -------------------------------------------------
    output_path = Path(output_path).with_suffix(".epw")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Writing EPW file to: {output_path}")
    with output_path.open("w") as fh:
        fh.writelines(header_lines)

        for ts, row in df_epw.iterrows():
            year, month, day = ts.year, ts.month, ts.day
            hour = ts.hour + 1  # EPW is 1-based
            minute = 0  # EPW minute field should be 0 for hourly data
            
            # Generate proper data source string (EPW format requirement)
            data_source_string = "?9?9?9?9E0?9?9?9?9?9?9?9?9?9?9?9*9?9*9*9*9*9"
            
            # assemble EPW data line (same order as standard EPW format)
            parts = [
                year, month, day, hour, minute,
                data_source_string,  # Data source field (field 6)
                f"{row.dry_bulb:.1f}", f"{row.dew_point:.1f}",
                int(row.rh), int(row.pressure),
                int(row.e_rad_h), int(row.e_rad_n), int(row.ghrad), # Radiation fields
                0, 0, 0, 0, 0, 0, 0,  # Infrared and other radiation fields
                int(row.wind_dir), f"{row.wind_spd:.1f}",
                int(row.sky_cover), int(row.opaque_sky),
                missing_value, missing_value,  # Visibility and ceiling height
                missing_value, missing_value,  # Weather codes
                f"{row.precip_depth:.1f}", f"{row.precip_qty:.1f}",
                missing_value, missing_value, missing_value, missing_value,
            ]
            fh.write(",".join(map(str, parts)) + "\n")

    # Also save the numeric data to CSV for debugging
    csv_path = output_path.with_suffix(".csv")
    df_epw.to_csv(csv_path, index_label="timestamp", float_format="%.3f")
    logger.info(f"Also saved CSV data to: {csv_path}")

    logger.info(f"EPW generation complete: {output_path}")
    return output_path


# ---------------------------------------------------------------------
# Full year EPW generation
# ---------------------------------------------------------------------
def _build_full_year_epw(
    space_id: str,
    start: datetime,
    end: datetime,
    latitude: float,
    longitude: float,
    output_path: Path
) -> Path:
    """
    Generate a full-year EPW file with complete weather data.
    Downloads missing data automatically using both historical and forecast APIs.
    
    This function ensures we have real weather data for the entire year
    by downloading any missing periods from the weather API 
    (historical data from archive API, future data from forecast API).
    """
    logger.info(f"Building full-year EPW from data period {start} to {end}")
    
    # Create a full year date range starting from January 1 of the start year
    year = start.year
    full_year_start = datetime(year, 1, 1)
    full_year_end = datetime(year, 12, 31, 23, 0, 0)
    
    # Check if we can get data for the requested year
    today = datetime.now()
    max_forecast_date = today + pd.Timedelta(days=15)  # ~15 days forecast limit
    
    if full_year_start > max_forecast_date:
        # Requested year is too far in the future, use most recent historical year
        historical_year = today.year - 1
        logger.warning(f"Requested year {year} is beyond forecast limits. Using historical data from {historical_year}")
        full_year_start = datetime(historical_year, 1, 1)
        full_year_end = datetime(historical_year, 12, 31, 23, 0, 0)
    elif full_year_end > max_forecast_date:
        # Partial year available (some historical + some forecast)
        logger.info(f"Year {year} extends beyond forecast limits. Will use available data up to ~15 days forecast.")
        full_year_end = min(full_year_end, max_forecast_date.replace(hour=23, minute=0, second=0))
    
    logger.info(f"Effective date range: {full_year_start} to {full_year_end}")
    
    # Ensure we have complete weather data for the effective period
    logger.info("Checking for complete weather data coverage...")
    ensure_complete_weather_data(
        space_id=space_id,
        latitude=latitude,
        longitude=longitude,
        start=full_year_start,
        end=full_year_end
    )
    
    # Now fetch the complete weather data from database
    with SessionLocal() as ses:
        df_raw = _fetch_weather_rows(space_id, full_year_start, full_year_end, ses)
    
    if df_raw.empty:
        raise RuntimeError(f"No weather data available for space {space_id} even after download attempt")
    
    logger.info(f"Using {len(df_raw)} weather records for full year EPW")
    logger.info(f"Temperature range: {df_raw['temperature_2m'].min():.1f}°C to {df_raw['temperature_2m'].max():.1f}°C")
    
    # Generate hourly timestamps for the full calendar year (8760/8784 hours)
    target_full_year_start = datetime(year, 1, 1, 0, 0, 0)
    target_full_year_end = datetime(year, 12, 31, 23, 0, 0)
    full_year_timestamps = pd.date_range(
        start=target_full_year_start,
        end=target_full_year_end,
        freq='h'
    )
    
    logger.info(f"Creating full year EPW with {len(full_year_timestamps)} hours")
    
    # Reindex and forward/backward fill to guarantee complete 365-day coverage for EnergyPlus sizing
    df_raw = df_raw.reindex(full_year_timestamps).ffill().bfill()
    
    # Since we now have real data, we can use it directly
    # Just ensure all required columns exist with reasonable defaults
    required_columns = [
        'temperature_2m', 'relative_humidity_2m', 'windspeed_10m', 
        'shortwave_radiation', 'direct_radiation', 'precipitation', 
        'cloud_cover', 'surface_pressure', 'dewpoint_2m', 'winddirection_10m', 'cloudcover'
    ]
    
    for col in required_columns:
        if col not in df_raw.columns:
            if col == 'surface_pressure':
                df_raw[col] = 1013.25  # standard atmospheric pressure in hPa
            elif col == 'dewpoint_2m':
                # Calculate dewpoint from temperature and RH if not available
                if 'temperature_2m' in df_raw.columns and 'relative_humidity_2m' in df_raw.columns:
                    df_raw[col] = df_raw['temperature_2m'] - ((100 - df_raw['relative_humidity_2m']) / 5)
                else:
                    df_raw[col] = df_raw['temperature_2m'] - 5  # rough estimate
            elif col == 'winddirection_10m':
                df_raw[col] = 180  # default south wind direction
            elif col == 'cloudcover':
                df_raw[col] = df_raw.get('cloud_cover', 50.0)  # use cloud_cover if available, else 50%
            else:
                df_raw[col] = 0.0  # default value for missing columns
    
    # Create configuration for convert_units
    cfg = {
        'missing_value': 999999,
        'header': {
            'latitude': latitude,
            'longitude': longitude
        },
        'data_flags': {"source": 0, "uncertainty": 0}
    }
    
    # Convert to EPW format using the real data
    logger.info("Converting real weather data to EPW format")
    df_epw = convert_units(df_raw, cfg)
    
    # Create EPW header from scratch
    logger.info("Creating EPW header from scratch")
    header_lines = create_epw_header(
        latitude=latitude,
        longitude=longitude,
        data_source="Database + Open-Meteo API"
    )
    
    # Write full-year EPW file
    output_path = Path(output_path).with_suffix(".epw")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Writing full-year EPW file to: {output_path}")
    with output_path.open("w") as fh:
        fh.writelines(header_lines)
        
        for ts, row in df_epw.iterrows():
            year, month, day = ts.year, ts.month, ts.day
            hour = ts.hour + 1  # EPW is 1-based
            minute = 0  # EPW minute field should be 0 for hourly data
            
            # Generate proper data source string (EPW format requirement)
            data_source_string = "?9?9?9?9E0?9?9?9?9?9?9?9?9?9?9?9*9?9*9*9*9*9"
            
            parts = [
                year, month, day, hour, minute,
                data_source_string,  # Data source field (field 6)
                f"{row.dry_bulb:.1f}", f"{row.dew_point:.1f}",
                int(row.rh), int(row.pressure),
                int(row.e_rad_h), int(row.e_rad_n), int(row.ghrad), # Radiation fields
                0, 0, 0, 0, 0, 0, 0,  # Infrared and other radiation fields
                int(row.wind_dir), f"{row.wind_spd:.1f}",
                int(row.sky_cover), int(row.opaque_sky),
                cfg['missing_value'], cfg['missing_value'],  # Visibility and ceiling height
                cfg['missing_value'], cfg['missing_value'],  # Weather codes
                f"{row.precip_depth:.1f}", f"{row.precip_qty:.1f}",
                cfg['missing_value'], cfg['missing_value'], cfg['missing_value'], cfg['missing_value'],
            ]
            fh.write(",".join(map(str, parts)) + "\n")
    
    # Also save CSV for debugging
    csv_path = output_path.with_suffix(".csv")
    df_epw.to_csv(csv_path, index_label="timestamp", float_format="%.3f")
    
    logger.info(f"Full-year EPW generation complete: {output_path} ({len(df_epw)} hours)")
    return output_path


# ---------------------------------------------------------------------
# Example usage function
# ---------------------------------------------------------------------
def generate_epw_for_location(
    space_id: str,
    latitude: float,
    longitude: float,
    start: datetime,
    end: datetime,
    output_dir: Path = Path("./eplus_sim/weather"),
    full_year: bool = True
) -> Path:
    """
    Convenience function to generate EPW file for a specific location and time period.
    
    Args:
        space_id: Space identifier for weather data
        latitude: Location latitude
        longitude: Location longitude
        start: Start datetime for data period
        end: End datetime for data period
        output_dir: Directory where EPW file will be saved
        full_year: If True, extend data to create a full-year EPW (8760 hours)
        
    Returns:
        Path to the generated EPW file
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename based on location and date range
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")
    
    if full_year:
        # For full year EPW, use the year from start date
        filename = f"weather_{space_id}_{start.year}_full_year.epw"
    else:
        filename = f"weather_{space_id}_{start_str}_{end_str}.epw"
    
    output_path = output_dir / filename
    
    if full_year:
        return _build_full_year_epw(
            space_id=space_id,
            start=start,
            end=end,
            latitude=latitude,
            longitude=longitude,
            output_path=output_path
        )
    else:
        return build_epw_from_db(
            space_id=space_id,
            start=start,
            end=end,
            latitude=latitude,
            longitude=longitude,
            output_path=output_path
        )
