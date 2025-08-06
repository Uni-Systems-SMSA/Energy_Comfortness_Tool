-- ---------------------------------------------------------------------------
--  Energy Comfortness Tool — Core DB Schema
--  VERSION: 2.0.0
--  DATE   : 2025-08-04
--  UPDATES: Enhanced ComfortLevel table with occupant profiles and comprehensive comfort metrics
-- ---------------------------------------------------------------------------

/******************************************************************
 * TABLE: measurements  – indoor sensor data & (optional) targets *
 ******************************************************************/
CREATE TABLE IF NOT EXISTS measurements (
    measurement_id  SERIAL PRIMARY KEY,
    time_end        TIMESTAMP      NOT NULL,
    sensor_id       VARCHAR        NOT NULL,
    window_seconds  NUMERIC,
    time_stored     TIMESTAMP      DEFAULT now(),
    data_type       VARCHAR(20)    NOT NULL  DEFAULT 'train',

    /* target features – all nullable */
    temperature_c        NUMERIC,
    energy_kwh           NUMERIC,
    co2_ppm              NUMERIC,
    rh_percent           NUMERIC,
    luminance_lux        NUMERIC,
    average_noise_db     NUMERIC,
    pm2_5_ugm3           NUMERIC,
    tvoc_ppb             NUMERIC,
    peak_db              NUMERIC,
    co_ppm               NUMERIC,
    pm10_ugm3            NUMERIC,

    /* unique per sensor & timestamp */
    CONSTRAINT uq_meas_time_end_sensor UNIQUE (time_end, sensor_id)
);
CREATE INDEX IF NOT EXISTS idx_meas_time ON measurements(time_end);



/********************************************************
 * TABLE: weather  – outdoor data fetched from Open-Meteo *
 ********************************************************/
CREATE TABLE IF NOT EXISTS weather (
    weather_id   SERIAL PRIMARY KEY,

    time_end     TIMESTAMP   NOT NULL,
    sensor_id    VARCHAR     NOT NULL,              -- “virtual sensor” / site tag

    outdoor_temperature_2m        DOUBLE PRECISION,
    outdoor_relative_humidity_2m  DOUBLE PRECISION,
    outdoor_windspeed_10m         DOUBLE PRECISION,
    outdoor_pressure_msl          DOUBLE PRECISION,
    wind_speed_10m                DOUBLE PRECISION,
    shortwave_radiation           DOUBLE PRECISION,
    direct_radiation              DOUBLE PRECISION,
    precipitation                 DOUBLE PRECISION,
    cloud_cover                   DOUBLE PRECISION,

    src        VARCHAR(12)  DEFAULT 'api',          -- 'archive' | 'forecast' | 'api'
    fetched_at TIMESTAMP    DEFAULT now(),

    CONSTRAINT uq_wx_time_end_sensor UNIQUE (time_end, sensor_id)
);
CREATE INDEX IF NOT EXISTS idx_wx_time ON weather(time_end);



/*************************************************
 * TABLE: trained_models  – one row per artefact *
 *************************************************/
CREATE TABLE IF NOT EXISTS trained_models (
    model_id       SERIAL PRIMARY KEY,
    target         VARCHAR(65)  NOT NULL,
    algorithm      VARCHAR(50)  NOT NULL,
    hyperparams    JSONB,
    metrics        JSONB,
    train_started  TIMESTAMP,
    train_finished TIMESTAMP,
    version        VARCHAR(20)  NOT NULL,
    model_path     TEXT         NOT NULL,

    CONSTRAINT uq_model_version UNIQUE (target, version)
);



/***********************************************************
 * TABLE: predictions  – model output for each weather row *
 ***********************************************************/
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id SERIAL PRIMARY KEY,

    model_id   INTEGER NOT NULL REFERENCES trained_models(model_id) ON DELETE CASCADE,
    weather_id INTEGER NOT NULL REFERENCES weather(weather_id)      ON DELETE CASCADE,

    predicted_at TIMESTAMP DEFAULT now(),

    /* predicted targets */
    predicted_temperature_c    NUMERIC,
    predicted_energy_kwh       NUMERIC,
    predicted_co2_ppm          NUMERIC,
    predicted_rh_percent       NUMERIC,
    predicted_luminance_lux    NUMERIC,
    predicted_average_noise_db NUMERIC,
    predicted_pm2_5_ugm3       NUMERIC,
    predicted_tvoc_ppb         NUMERIC,
    predicted_peak_db          NUMERIC,
    predicted_co_ppm           NUMERIC,
    predicted_pm10_ugm3        NUMERIC,

    /* legacy comfort metrics (maintained for backward compatibility) */
    pmv_value                  NUMERIC,  -- Predicted Mean Vote
    ppd_value                  NUMERIC,  -- Predicted Percentage Dissatisfied (%)
    thermal_comfort_class      VARCHAR(2),  -- A, B, C, NC
    visual_comfort_class       VARCHAR(2),  -- A, B, C, NC  
    acoustic_comfort_class     VARCHAR(2),  -- A, B, C, D, NC
    visual_comfort_score       NUMERIC,   -- Yong visual comfort score
    acoustic_annoyance_level   NUMERIC,   -- Age-dependent annoyance level
    co2_comfort_class          VARCHAR(2),  -- A, B, C, D, NC
    co_comfort_class           VARCHAR(2),  -- A, B, NC
    tvoc_comfort_class         VARCHAR(2),  -- A, B, NC
    pm25_comfort_class         VARCHAR(2),  -- A, B, NC
    pm10_comfort_class         VARCHAR(2),  -- A, B, NC
    overall_comfort            NUMERIC,    -- Weighted average of all comfort classes (0-4 scale)
    overall_comfort_class      VARCHAR(2)  -- A, B, C, D, NC
);
CREATE INDEX IF NOT EXISTS idx_pred_model ON predictions(model_id);
CREATE INDEX IF NOT EXISTS idx_pred_time  ON predictions(predicted_at);



/*************************************************************
 * TABLE: comfort_levels  – profile-specific comfort analysis *
 *************************************************************/
CREATE TABLE IF NOT EXISTS comfort_levels (
    comfort_id    SERIAL PRIMARY KEY,

    prediction_id  INTEGER REFERENCES predictions(prediction_id) ON DELETE CASCADE,
    measurement_id INTEGER REFERENCES measurements(measurement_id) ON DELETE CASCADE,
    
    /* Occupant profile for age-dependent comfort calculations */
    occupant_profile VARCHAR(50) NOT NULL,  -- e.g., 'young', 'middle_aged', 'elderly', 'default'
    
    estimated_at TIMESTAMP DEFAULT now(),

    /* PMV/PPD thermal comfort metrics */
    pmv                   NUMERIC,  -- Predicted Mean Vote
    ppd                   NUMERIC,  -- Predicted Percentage Dissatisfied (%)
    
    /* Comfort class predictions for each domain */
    thermal_comfort_class      VARCHAR(2),  -- A, B, C, NC
    visual_comfort_class       VARCHAR(2),  -- A, B, C, NC  
    acoustic_comfort_class     VARCHAR(2),  -- A, B, C, D, NC
    co2_comfort_class          VARCHAR(2),  -- A, B, C, D, NC
    co_comfort_class           VARCHAR(2),  -- A, B, NC
    tvoc_comfort_class         VARCHAR(2),  -- A, B, NC
    pm25_comfort_class         VARCHAR(2),  -- A, B, NC
    pm10_comfort_class         VARCHAR(2),  -- A, B, NC
    
    /* Numeric comfort scores */
    visual_comfort_score       NUMERIC,   -- Yong visual comfort score
    acoustic_annoyance_level   NUMERIC,   -- Age-dependent annoyance level
    overall_comfort            NUMERIC,    -- Weighted average of all comfort classes (0-4 scale)
    overall_comfort_class      VARCHAR(2),  -- A, B, C, D, NC
    
    /* Constraints */
    CONSTRAINT chk_comfort_source CHECK (
        (prediction_id IS NOT NULL AND measurement_id IS NULL) OR
        (prediction_id IS NULL AND measurement_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_comf_pred ON comfort_levels(prediction_id);
CREATE INDEX IF NOT EXISTS idx_comf_meas ON comfort_levels(measurement_id);
CREATE INDEX IF NOT EXISTS idx_comf_profile ON comfort_levels(occupant_profile);
CREATE INDEX IF NOT EXISTS idx_comf_time ON comfort_levels(estimated_at);



/*********************************************************************
 * TABLE: energy_buildings  – building-level EnergyPlus simulation results *
 *********************************************************************/
CREATE TABLE IF NOT EXISTS energy_buildings (
    building_id    SERIAL PRIMARY KEY,
    
    simulation_timestamp TIMESTAMP NOT NULL,  -- When the simulation was run
    
    /* Simulation metadata */
    simulation_start_date  TIMESTAMP NOT NULL,  -- Simulated period start
    simulation_end_date    TIMESTAMP NOT NULL,  -- Simulated period end
    weather_file_path      TEXT,                -- Path to EPW file used
    ifc_file_path         TEXT,                -- Path to IFC file used  
    eplus_results_path    TEXT,                -- Path to EnergyPlus results directory
    
    /* Building-level totals (kWh) */
    total_heating_kwh     NUMERIC NOT NULL DEFAULT 0,
    total_cooling_kwh     NUMERIC NOT NULL DEFAULT 0,
    total_energy_kwh      NUMERIC NOT NULL DEFAULT 0,
    
    /* Peak power rates (W) */
    peak_heating_w        NUMERIC DEFAULT 0,
    peak_cooling_w        NUMERIC DEFAULT 0,
    
    /* Number of thermal zones detected */
    zones_count           INTEGER DEFAULT 0,
    
    /* Time series data (JSON arrays of hourly values) */
    heating_timeseries    JSONB,  -- Array of hourly heating values in Watts
    cooling_timeseries    JSONB,  -- Array of hourly cooling values in Watts
    
    /* Metadata */
    created_at            TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_energy_building_time ON energy_buildings(simulation_timestamp);



/*******************************************************************
 * TABLE: energy_spaces  – space/zone-level energy data from EnergyPlus *
 *******************************************************************/
CREATE TABLE IF NOT EXISTS energy_spaces (
    space_id      SERIAL PRIMARY KEY,
    building_id   INTEGER NOT NULL 
        REFERENCES energy_buildings(building_id) ON DELETE CASCADE,
    sensor_id     VARCHAR NOT NULL,  -- Links to the sensor associated with this space
    
    /* Zone identification */
    zone_id       VARCHAR NOT NULL,  -- EnergyPlus zone ID (e.g., "Zone1", "Office_1")
    zone_name     VARCHAR,           -- Human-readable name from space.csv
    zone_type     VARCHAR,           -- Space type if available
    
    /* Zone-level energy totals (kWh) */
    heating_kwh   NUMERIC NOT NULL DEFAULT 0,
    cooling_kwh   NUMERIC NOT NULL DEFAULT 0,
    total_kwh     NUMERIC NOT NULL DEFAULT 0,
    
    /* Percentage of building energy */
    heating_percentage NUMERIC DEFAULT 0,  -- % of total building heating
    cooling_percentage NUMERIC DEFAULT 0,  -- % of total building cooling
    
    /* Zone geometry (if available from IFC) */
    floor_area_m2 NUMERIC,
    volume_m3     NUMERIC,
    
    /* Energy intensity metrics */
    heating_intensity_kwh_m2 NUMERIC,  -- kWh/m² for heating
    cooling_intensity_kwh_m2 NUMERIC,  -- kWh/m² for cooling
    
    /* Metadata */
    created_at    TIMESTAMP DEFAULT now(),
    
    CONSTRAINT uq_energy_space_building_zone UNIQUE (building_id, zone_id)
);
CREATE INDEX IF NOT EXISTS idx_energy_space_building ON energy_spaces(building_id);
CREATE INDEX IF NOT EXISTS idx_energy_space_zone ON energy_spaces(zone_id);
CREATE INDEX IF NOT EXISTS idx_energy_space_sensor ON energy_spaces(sensor_id);



/*******************************************************************
 * TABLE: energy_timeseries  – timestamped energy data from EnergyPlus *
 *******************************************************************/
CREATE TABLE IF NOT EXISTS energy_timeseries (
    timeseries_id   SERIAL PRIMARY KEY,
    space_id        INTEGER NOT NULL 
        REFERENCES energy_spaces(space_id) ON DELETE CASCADE,
    
    /* Timestamp for this data point */
    timestamp       TIMESTAMP NOT NULL,  -- Simulation datetime
    
    /* Energy consumption at this timestep (Watts) */
    heating_power_w NUMERIC DEFAULT 0,     -- Instantaneous heating power
    cooling_power_w NUMERIC DEFAULT 0,     -- Instantaneous cooling power
    
    /* Cumulative energy consumption (kWh) up to this point */
    heating_energy_kwh NUMERIC DEFAULT 0,  -- Cumulative heating energy
    cooling_energy_kwh NUMERIC DEFAULT 0,  -- Cumulative cooling energy
    
    /* Metadata */
    created_at      TIMESTAMP DEFAULT now(),
    
    CONSTRAINT uq_energy_timeseries_space_timestamp UNIQUE (space_id, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_energy_timeseries_space ON energy_timeseries(space_id);
CREATE INDEX IF NOT EXISTS idx_energy_timeseries_time ON energy_timeseries(timestamp);


/* ------------------------------------------------------------------------
   End of schema
   --------------------------------------------------------------------- */
