# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from dotenv import load_dotenv
import datetime as dt
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Float,
    JSON,
    MetaData,
    ForeignKey,
    Text,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

# ---------------------------------------------------------------------------
# 1️⃣  GLOBAL NAMING-CONVENTION  (avoids duplicate-name errors!)
# ---------------------------------------------------------------------------
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",        # <- change here
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)
Base = declarative_base(metadata=metadata)

# ---------------------------------------------------------------------------
# 2️⃣  ORM CLASSES
# ---------------------------------------------------------------------------

class Space(Base):
    """
    Represents spaces with building information.
    Each space belongs to a building and has location coordinates.
    """
    __tablename__ = "spaces"

    space_id    = Column(String, primary_key=True)  # From CSV: space identifier (was sensor_id)
    building_id = Column(String, nullable=False)    # From CSV: building identifier
    latitude    = Column(Float, nullable=False)     # From CSV: building latitude in decimal degrees N
    longitude   = Column(Float, nullable=False)     # From CSV: building longitude in decimal degrees E
    created_at  = Column(DateTime, server_default=text("now()"))
    updated_at  = Column(DateTime, server_default=text("now()"))

    # relationships
    measurements = relationship("Measurement", back_populates="space", cascade="all, delete-orphan")
    weather_data = relationship("Weather", back_populates="space", cascade="all, delete-orphan")


class Measurement(Base):
    __tablename__ = "measurements"
    __table_args__ = (
        UniqueConstraint("time_end", "space_id", name="uq_meas_time_end_space"),
    )

    measurement_id = Column(Integer, primary_key=True)
    time_end       = Column(DateTime, nullable=False)
    space_id       = Column(String, ForeignKey("spaces.space_id", ondelete="CASCADE"), nullable=False)
    window_seconds = Column(Numeric)
    time_stored    = Column(DateTime, server_default=text("now()"))
    data_type      = Column(String(20), nullable=False, server_default="train")

    # targets (nullable)
    temperature_c        = Column(Numeric)
    energy_kwh           = Column(Numeric)
    co2_ppm              = Column(Numeric)
    rh_percent           = Column(Numeric)
    luminance_lux        = Column(Numeric)
    average_noise_db     = Column(Numeric)
    pm2_5_ugm3           = Column(Numeric)
    tvoc_ppb             = Column(Numeric)
    peak_db              = Column(Numeric)
    co_ppm               = Column(Numeric)
    pm10_ugm3            = Column(Numeric)

    # relationships
    space = relationship("Space", back_populates="measurements")


class Weather(Base):
    __tablename__ = "weather"
    __table_args__ = (
        UniqueConstraint("time_end", "space_id", name="uq_wx_time_end_space"),
    )

    weather_id  = Column(Integer, primary_key=True)
    time_end    = Column(DateTime, nullable=False)
    space_id    = Column(String, ForeignKey("spaces.space_id", ondelete="CASCADE"), nullable=False)

    outdoor_temperature_2m        = Column(Float)
    outdoor_relative_humidity_2m  = Column(Float)
    wind_speed_10m                = Column(Float)
    shortwave_radiation           = Column(Float)
    direct_radiation              = Column(Float)
    precipitation                 = Column(Float)
    cloud_cover                   = Column(Float)

    src        = Column(String(12), server_default="api")  # 'archive' | 'forecast' | 'api'
    fetched_at = Column(DateTime, server_default=text("now()"))

    # relationships
    space = relationship("Space", back_populates="weather_data")
    predictions = relationship("Prediction", back_populates="weather", cascade="all, delete-orphan")


class TrainedModel(Base):
    __tablename__ = "trained_models"
    __table_args__ = (
        UniqueConstraint("target", "version", "space_id", name="uq_trained_models_target_version_space"),
    )

    model_id        = Column(Integer, primary_key=True)
    target          = Column(String(65), nullable=False)
    space_id        = Column(String, ForeignKey("spaces.space_id", ondelete="CASCADE"))
    algorithm       = Column(String(50), nullable=False)
    hyperparams     = Column(JSON)
    metrics         = Column(JSON)
    train_started   = Column(DateTime)
    train_finished  = Column(DateTime)
    version         = Column(String(20), nullable=False)
    model_path      = Column(String,      nullable=False)

    predictions = relationship("Prediction", back_populates="model", cascade="all, delete-orphan")
    space = relationship("Space", backref="trained_models")


class Prediction(Base):
    __tablename__ = "predictions"

    prediction_id = Column(Integer, primary_key=True)

    model_id   = Column(Integer, ForeignKey("trained_models.model_id", ondelete="CASCADE"), nullable=False)
    weather_id = Column(Integer, ForeignKey("weather.weather_id",        ondelete="CASCADE"), nullable=False)

    predicted_at = Column(DateTime, server_default=text("now()"))

    # predicted targets
    predicted_temperature_c    = Column(Numeric)
    predicted_energy_kwh       = Column(Numeric)
    predicted_co2_ppm          = Column(Numeric)
    predicted_rh_percent       = Column(Numeric)
    predicted_luminance_lux    = Column(Numeric)
    predicted_average_noise_db = Column(Numeric)
    predicted_pm2_5_ugm3       = Column(Numeric)
    predicted_tvoc_ppb         = Column(Numeric)
    predicted_peak_db          = Column(Numeric)
    predicted_co_ppm           = Column(Numeric)
    predicted_pm10_ugm3        = Column(Numeric)

    # comfort-related fields (from former ComfortLevel table)
    occupant_profile = Column(String(50), nullable=True)  # Occupant profile name (e.g., 'young', 'elderly', 'default')
    
    # PMV/PPD thermal comfort metrics
    pmv                   = Column(Numeric)  # Predicted Mean Vote
    ppd                   = Column(Numeric)  # Predicted Percentage Dissatisfied (%)
    
    # Comfort class predictions for each domain
    thermal_comfort_class      = Column(String(2))  # A, B, C, NC
    visual_comfort_class       = Column(String(2))  # A, B, C, NC  
    acoustic_comfort_class     = Column(String(2))  # A, B, C, D, NC
    co2_comfort_class          = Column(String(2))  # A, B, C, D, NC
    co_comfort_class           = Column(String(2))  # A, B, NC
    tvoc_comfort_class         = Column(String(2))  # A, B, NC
    pm25_comfort_class         = Column(String(2))  # A, B, NC
    pm10_comfort_class         = Column(String(2))  # A, B, NC
    
    # Numeric comfort scores
    visual_comfort_score       = Column(Numeric)   # Yong visual comfort score
    acoustic_annoyance_level   = Column(Numeric)   # Age-dependent annoyance level
    overall_comfort            = Column(Numeric)    # Weighted average of all comfort classes (0-4 scale)
    overall_comfort_class      = Column(String(2))  # A, B, C, D, NC

    # relationships
    model   = relationship("TrainedModel", back_populates="predictions")
    weather = relationship("Weather",      back_populates="predictions")


class EnergyBuilding(Base):
    """
    Stores building-level energy simulation results from EnergyPlus.
    Each record represents one complete building simulation.
    """
    __tablename__ = "energy_buildings"

    energy_building_id = Column(Integer, primary_key=True)
    building_id = Column(String, nullable=False)  # Building identifier from spaces
    simulation_timestamp = Column(DateTime, nullable=False)  # When the simulation was run
    
    # Simulation metadata
    simulation_start_date = Column(DateTime, nullable=False)  # Simulated period start
    simulation_end_date = Column(DateTime, nullable=False)    # Simulated period end
    weather_file_path = Column(String)  # Path to EPW file used
    ifc_file_path = Column(String)      # Path to IFC file used
    eplus_results_path = Column(String) # Path to EnergyPlus results directory
    
    # Building-level totals (kWh)
    total_heating_kwh = Column(Numeric, nullable=False, server_default="0")
    total_cooling_kwh = Column(Numeric, nullable=False, server_default="0")
    total_energy_kwh = Column(Numeric, nullable=False, server_default="0")
    
    # Peak power rates (W)
    peak_heating_w = Column(Numeric, server_default="0")
    peak_cooling_w = Column(Numeric, server_default="0")
    
    # Number of thermal zones detected
    zones_count = Column(Integer, server_default="0")
    
    # Time series data (JSON arrays of hourly values)
    heating_timeseries = Column(JSON)  # Array of hourly heating values in Watts
    cooling_timeseries = Column(JSON)  # Array of hourly cooling values in Watts
    
    # Metadata
    created_at = Column(DateTime, server_default=text("now()"))
    
    # Relationships
    spaces = relationship("EnergySpace", back_populates="building", cascade="all, delete-orphan")


class EnergySpace(Base):
    """
    Stores space/zone-level energy data from EnergyPlus simulations.
    Each record represents one thermal zone within a building simulation.
    """
    __tablename__ = "energy_spaces"
    __table_args__ = (
        UniqueConstraint("energy_building_id", "zone_id", name="uq_energy_space_building_zone"),
    )

    energy_space_id = Column(Integer, primary_key=True)
    energy_building_id = Column(Integer, ForeignKey("energy_buildings.energy_building_id", ondelete="CASCADE"), nullable=False)
    space_id = Column(String, ForeignKey("spaces.space_id", ondelete="CASCADE"), nullable=False)
    
    # Zone identification
    zone_id = Column(String, nullable=False)    # EnergyPlus zone ID (e.g., "Zone1", "Office_1")
    zone_name = Column(String)                  # Human-readable name from space.csv
    zone_type = Column(String)                  # Space type if available
    
    # Zone-level energy totals (kWh) - aggregated from timestamped data
    heating_kwh = Column(Numeric, nullable=False, server_default="0")
    cooling_kwh = Column(Numeric, nullable=False, server_default="0")
    total_kwh = Column(Numeric, nullable=False, server_default="0")
    
    # Percentage of building energy
    heating_percentage = Column(Numeric, server_default="0")  # % of total building heating
    cooling_percentage = Column(Numeric, server_default="0")  # % of total building cooling
    
    # Zone geometry (if available from IFC)
    floor_area_m2 = Column(Numeric)
    volume_m3 = Column(Numeric)
    
    # Energy intensity metrics
    heating_intensity_kwh_m2 = Column(Numeric)  # kWh/m² for heating
    cooling_intensity_kwh_m2 = Column(Numeric)  # kWh/m² for cooling
    
    # Metadata
    created_at = Column(DateTime, server_default=text("now()"))
    
    # Relationships
    building = relationship("EnergyBuilding", back_populates="spaces")
    space = relationship("Space")
    energy_timeseries = relationship("EnergyTimeSeries", back_populates="space", cascade="all, delete-orphan")


class EnergyTimeSeries(Base):
    """
    Stores timestamped energy data points from EnergyPlus simulations.
    Each record represents one time step (typically hourly) of energy consumption for one zone.
    """
    __tablename__ = "energy_timeseries"
    __table_args__ = (
        UniqueConstraint("energy_space_id", "timestamp", name="uq_energy_timeseries_space_timestamp"),
    )

    timeseries_id = Column(Integer, primary_key=True)
    energy_space_id = Column(Integer, ForeignKey("energy_spaces.energy_space_id", ondelete="CASCADE"), nullable=False)
    
    # Timestamp for this data point
    timestamp = Column(DateTime, nullable=False)  # Simulation datetime
    
    # Energy consumption at this timestep (Watts)
    heating_power_w = Column(Numeric, server_default="0")     # Instantaneous heating power
    cooling_power_w = Column(Numeric, server_default="0")     # Instantaneous cooling power
    
    # Cumulative energy consumption (kWh) up to this point
    heating_energy_kwh = Column(Numeric, server_default="0")  # Cumulative heating energy
    cooling_energy_kwh = Column(Numeric, server_default="0")  # Cumulative cooling energy
    
    # Metadata
    created_at = Column(DateTime, server_default=text("now()"))
    
    # Relationships
    space = relationship("EnergySpace", back_populates="energy_timeseries")


class IFCSimulationJob(Base):
    """
    Tracks automated execution jobs for IFC building models.
    """
    __tablename__ = "ifc_simulation_jobs"

    job_id = Column(Integer, primary_key=True)
    building_name = Column(String, nullable=False)     # Human-readable name (e.g. "CERTH Smart House")
    folder_name = Column(String, nullable=False, unique=True) # Directory name under etc/ifc/
    ifc_file_path = Column(String, nullable=False)     # Relative path to IFC file
    config_file_path = Column(String, nullable=True)   # Relative path to config.json (if present)
    status = Column(String(20), nullable=False, default="PENDING") # PENDING, RUNNING, OK, FAILED
    last_run_timestamp = Column(DateTime, nullable=True)
    last_run_duration_sec = Column(Float, nullable=True)
    log_file_path = Column(String, nullable=True)     # Path to execution log file
    error_message = Column(Text, nullable=True)        # Full error stacktrace on failure
    created_at = Column(DateTime, server_default=text("now()"))
    updated_at = Column(DateTime, server_default=text("now()"), onupdate=dt.datetime.now)


# ---------------------------------------------------------------------------
# 3️⃣   Session / engine helper  (db/session.py)
# ---------------------------------------------------------------------------
# db/session.py
import dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# >>> adapt the URL to your local / env settings
load_dotenv()

DATABASE_URL = (
    f"postgresql+psycopg2://{os.environ['POSTGRES_USER']}:"
    f"{os.environ['POSTGRES_PASSWORD']}@"
    f"{os.environ['POSTGRES_HOST']}:{os.environ.get('POSTGRES_PORT',5432)}/"
    f"{os.environ['POSTGRES_DB']}"
)

# echo=False silences SQL chatter; set to True when debugging
engine = create_engine(DATABASE_URL, echo=False, future=True, pool_pre_ping=True)

# create_all only once at startup (keep it here or in db/__init__.py)
from db.models import Base  # noqa: E402
Base.metadata.create_all(bind=engine)

# session factory
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
