
"""
ece.utils.epw
=============

Utility functions for generating EPW (EnergyPlus Weather) files from weather data.
This module provides functionality to convert weather data into the EPW format
required by EnergyPlus building simulation software.
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from typing import Union


def compute_relative_humidity(df: pd.DataFrame) -> Union[np.ndarray, pd.Series]:
    """
    Compute relative humidity from temperature and dew point.
    
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing 'temperature_2m' and 'dewpoint_2m' columns
        
    Returns
    -------
    Union[np.ndarray, pd.Series]
        Relative humidity values (0-100%)
    """
    if 'relative_humidity_2m' in df.columns:
        return df['relative_humidity_2m']
    
    # Calculate from temperature and dew point if RH not available
    T = df['temperature_2m'] + 273.15  # Convert to Kelvin
    Td = df['dewpoint_2m'] + 273.15    # Convert to Kelvin
    
    # Magnus-Tetens approximation
    rh = 100 * np.exp((17.625 * (Td - 273.15)) / (243.04 + (Td - 273.15))) / \
         np.exp((17.625 * (T - 273.15)) / (243.04 + (T - 273.15)))
    
    return np.clip(rh, 0, 100)


def compute_extraterrestrial_radiation(df: pd.DataFrame, config: dict) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute extraterrestrial solar radiation components.
    
    Parameters
    ----------
    df : pd.DataFrame
        Weather data with datetime index
    config : dict
        Configuration dictionary containing header info with latitude
        
    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        Horizontal and normal extraterrestrial radiation (W/m²)
    """
    print("Computing extraterrestrial radiation...")
    
    lat = np.radians(config['header']['latitude'])
    doy = df.index.dayofyear.values
    hour = df.index.hour.values + 0.5  # mid-hour
    
    # Solar constant and earth-sun distance correction
    I_sc = 1367  # W/m² - solar constant
    ecc = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    
    # Solar declination angle
    delta = np.radians(23.45) * np.sin(2 * np.pi * (284 + doy) / 365)
    
    # Hour angle
    omega = np.radians(15 * (hour - 12))
    
    # Cosine of solar zenith angle
    cos_theta = np.clip(
        np.sin(lat) * np.sin(delta) + np.cos(lat) * np.cos(delta) * np.cos(omega),
        0, None
    )
    
    # Extraterrestrial radiation
    I0n = I_sc * ecc  # Normal
    I0h = I0n * cos_theta  # Horizontal
    
    return I0h, np.full_like(I0h, I0n)


def convert_units(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Convert weather data units to EPW format requirements.
    
    Parameters
    ----------
    df : pd.DataFrame
        Raw weather data with standard column names
    config : dict
        Configuration dictionary containing missing value marker
        
    Returns
    -------
    pd.DataFrame
        Weather data formatted for EPW file with proper units and columns
    """
    print("Converting units to EPW format...")
    
    mv = config['missing_value']
    out = pd.DataFrame(index=df.index)
    
    # Basic meteorological variables
    out['dry_bulb'] = df['temperature_2m']  # °C
    out['dew_point'] = df['dewpoint_2m']    # °C
    out['rh'] = compute_relative_humidity(df)  # %
    out['pressure'] = df['surface_pressure'] * 100  # hPa -> Pa
    
    # Solar radiation components
    i0h, i0n = compute_extraterrestrial_radiation(df, config)
    out['e_rad_h'] = i0h  # W/m²
    out['e_rad_n'] = i0n  # W/m²
    out['ghrad'] = df['shortwave_radiation']  # W/m²
    
    # Direct and diffuse radiation (placeholders)
    out['dnrad'] = mv
    out['dfrad'] = mv
    
    # Cloud cover (convert percentage to oktas 0-10)
    octas = np.clip(np.round(df['cloudcover'] / 10), 0, 10)
    out['sky_cover'] = octas
    out['opaque_sky'] = octas
    
    # Wind conditions
    out['wind_dir'] = df['winddirection_10m']  # degrees
    out['wind_spd'] = df['windspeed_10m']      # m/s
    
    # Precipitation
    out['precip_depth'] = df['precipitation']  # mm
    out['precip_qty'] = df['precipitation']    # mm
    
    # EPW format placeholders for missing data
    extras = [
        'infrared', 'ghi_lux', 'dni_lux', 'dhi_lux', 'zenith_lum',
        'visibility', 'ceiling', 'present_weather_1', 'present_weather_2',
        'snow_depth', 'days_snow', 'albedo', 'liq_precip'
    ]
    for col in extras:
        out[col] = mv
    
    # Fill any remaining NaN values with missing value marker
    out.fillna(mv, inplace=True)
    
    print("Unit conversion complete.")
    return out


def load_header(template_path: Union[str, Path]) -> list[str]:
    """
    Load EPW header template from file.
    
    Parameters
    ----------
    template_path : Union[str, Path]
        Path to EPW template file containing header information
        
    Returns
    -------
    list[str]
        List of header lines up to and including DATA PERIODS line
    """
    print(f"Loading EPW header template from '{template_path}'...")
    
    template_path = Path(template_path)
    header_lines = []
    
    with open(template_path, 'r', encoding='utf-8') as f:
        for line in f:
            header_lines.append(line)
            if line.strip().startswith('DATA PERIODS'):
                break
    
    print(f"Header template loaded: {len(header_lines)} lines.")
    return header_lines