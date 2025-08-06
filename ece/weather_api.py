# -- coding: utf-8 -*-

from __future__ import annotations

import requests, datetime as dt
import pandas as pd
from typing import Literal

BASE_URL = "https://archive-api.open-meteo.com/v1/archive"
BASE_FC  = "https://api.open-meteo.com/v1/forecast"   #   forecast endpoint

_HOURLY = ",".join([
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_gusts_10m",
    "shortwave_radiation",
    "direct_radiation",
    "precipitation",
    "cloud_cover",
])

def fetch_open_meteo(
    lat: float,
    lon: float,
    *,
    start: dt.datetime,
    end: dt.datetime,
) -> pd.DataFrame:
    """
    Return a tidy DF (UTC) with all requested weather fields covering
    [start, end] inclusive.  If *end* >= today the range is split:   
    • past → archive endpoint  
    • today & future hours → forecast endpoint
    """
    def _query(base: str, s: dt.datetime, e: dt.datetime, src: Literal["archive","forecast"]):
        url = (
            f"{base}?latitude={lat}&longitude={lon}"
            f"&start_date={s.date():%Y-%m-%d}&end_date={e.date():%Y-%m-%d}"
            f"&hourly={_HOURLY}&timezone=UTC"
        )
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()["hourly"]
        df = pd.DataFrame(data)
        df.rename(columns={"time": "time_end"}, inplace=True)
        df["time_end"] = pd.to_datetime(df["time_end"], utc=False)  # already UTC
        df["src"] = src
        return df

    today = dt.datetime.now(tz=dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # convert to offset-aware datetimes
    start = pd.Timestamp(start).tz_convert(tz="UTC")
    end   = pd.Timestamp(end).tz_convert(tz="UTC")
    today = pd.Timestamp(today).tz_convert(tz="UTC")

    parts: list[pd.DataFrame] = []
    if start < today:
        hist_end = min(end, today - dt.timedelta(hours=1))
        parts.append(_query(BASE_URL, start, hist_end, "archive"))
    if end >= today:
        fc_start = max(start, today)
        parts.append(_query(BASE_FC, fc_start, end, "forecast"))

    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
