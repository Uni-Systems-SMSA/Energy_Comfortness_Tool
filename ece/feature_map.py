# indoor_ieq/feature_map.py
"""Plain dict: output → list of *raw* driver names."""

TIME_DRIVERS = ["hour_sin", "hour_cos", "doy_sin", "doy_cos"]

MAP = {       
    "temperature_c": [
        # weather drivers
        "outdoor_temperature_2m", 
        "outdoor_relative_humidity_2m",
        "cloud_cover",
        # "shortwave_radiation", 
        # "direct_radiation",
        # "wind_speed_10m", 
        # "wind_gusts_10m", 
        # "precipitation",
        # engineered
        "outdoor_temperature_2m_mean_12h",
        # "global_rad_pos_change", "global_rad_neg_change",
        # time
         *TIME_DRIVERS,
        # NEW autoregressive feature(s)
        # "temperature_c_lag1",
        # "temperature_c_lag2",
        # "temperature_c_lag6",
    ],

    "rh_percent": [                
        "outdoor_temperature_2m",
        "outdoor_relative_humidity_2m",
        "cloud_cover",
        "precipitation",
         *TIME_DRIVERS,
        # "outdoor_temperature_2m_mean_12h",
        # "outdoor_relative_humidity_2m_mean_12h",
        # "rh_percent_lag1",
        # "rh_percent_lag6",
    ],
    "average_noise_db": [
        *TIME_DRIVERS
        ],
    "peak_db": [
        *TIME_DRIVERS
        ],
    "luminance_lux": [
        *TIME_DRIVERS,
        "shortwave_radiation", 
        "direct_radiation", 
        "cloud_cover"
        ],
    "co2_ppm": [
         "wind_speed_10m",
         *TIME_DRIVERS
         ],
    "tvoc_ppb": [
        *TIME_DRIVERS,
        "outdoor_temperature_2m", 
        "outdoor_relative_humidity_2m", 
        "shortwave_radiation"
        ],
    "pm2_5_ugm3": [
        *TIME_DRIVERS,
        "wind_speed_10m", 
        "precipitation", 
        "cloud_cover"
        ],
    # "peak_db":       ["wind_gusts_10m", "rain"],
    # "average_noise_db": ["wind_gusts_10m", "rain"],
    # "luminance_lux": ["shortwave_radiation", "direct_radiation", "cloud_cover"],
    # "co2_ppm":       [ "wind_speed_10m"],
    # "co_ppm":        ["temperature_c", "rh_percent", "shortwave_radiation"],
    # "tvoc_ppb":      ["temperature_c", "rh_percent", "shortwave_radiation"],
    # "pm2_5_ugm3":    ["pm2_5", "wind_speed_10m", "precipitation", "cloud_cover"],
    # "pm10_ugm3":     ["pm10",  "wind_speed_10m", "precipitation", "cloud_cover"],
}


NUM_FEATURES = {k: len(v) for k, v in MAP.items()}
__all__ = ["MAP", "NUM_FEATURES"]