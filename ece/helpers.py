"""
ece.helpers
==================

Utility functions shared by Streamlit dashboard & training scripts:
  • Thermal comfort (PMV / PPD ISO)
  • Acoustic annoyance model (age-dependent)
  • Visual comfort score (Yong et al., 2024)
  • KPI threshold dictionary for quick compliance checks
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from typing import Sequence, Union
Union[np.ndarray, pd.Series, list]


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# THERMAL COMFORT
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
try:
    # pythermalcomfort >= 3.0
    from pythermalcomfort.models import pmv_ppd_iso as _pmv_iso
    def pmv_ppd(tdb, rh, *, vr=0.1, met=1.1, clo=0.7):
        """Vectorised PMV & PPD (returns 2-tuple of np.ndarray)."""
        res = _pmv_iso(tdb=tdb, tr=tdb, vr=vr, rh=rh, met=met, clo=clo)
        return res.pmv, res.ppd
except ImportError:
    # fallback for pythermalcomfort 2.x
    from pythermalcomfort.models import pmv as _pmv_old
    def _ppd_from_pmv(pmv):
        return 100 - 95 * np.exp(-0.03353 * pmv**4 - 0.2179 * pmv**2)
    def pmv_ppd(tdb, rh, *, vr=0.1, met=1.1, clo=0.7):
        pmv = _pmv_old(tdb=tdb, tr=tdb, vr=vr, rh=rh, met=met, clo=clo)
        return pmv, _ppd_from_pmv(pmv)

def classify_thermal_category(
    pmv_array: Union[np.ndarray, pd.Series, list], 
    ppd_array: Union[np.ndarray, pd.Series, list]
) -> np.ndarray:
    """
    Classify comfort category based on PMV and PPD arrays, following ISO 7730.

    Parameters
    ----------
    pmv_array : Union[np.ndarray, list]
        Array or list of PMV values.
    ppd_array : Union[np.ndarray, list]
        Array or list of PPD values (in %).

    Returns
    -------
    np.ndarray
        Array of strings indicating category ('A', 'B', 'C', 'NC').
    """
    pmv_array = np.asarray(pmv_array)
    ppd_array = np.asarray(ppd_array)
    
    categories = np.full(pmv_array.shape, 'NC', dtype='<U2')  # Default "NC" (Not Classified)
    
    # Category A
    mask_a = (np.abs(pmv_array) <= 0.2) & (ppd_array <= 6)
    categories[mask_a] = 'A'
    
    # Category B
    mask_b = (np.abs(pmv_array) <= 0.5) & (ppd_array <= 10) & ~mask_a
    categories[mask_b] = 'B'
    
    # Category C
    mask_c = (np.abs(pmv_array) <= 0.7) & (ppd_array <= 15) & ~mask_a & ~mask_b
    categories[mask_c] = 'C'
    
    return categories

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ACOUSTIC COMFORT  (age-dependent annoyance)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _annoy_ref(age: int) -> float | None:
    """Reference annoyance level vs. age [11,55]  (Yilmaz et al.)."""
    if 11 <= age <= 16:
        return 0.944 * age - 9.014
    if 16 < age <= 22:
        return -0.353 * age + 11.738
    if 22 < age <= 55:
        return -0.044 * age + 4.658
    return None   # age outside model range

def annoyance_level(dB: np.ndarray | float, age: int, k: float = 2.0):
    """
    Annoyance level from sound level in dB(A) and occupant age.
    Exponential model suggested in your spec.
    """
    ref = _annoy_ref(age)
    return None if ref is None else ref * np.exp(k * np.asarray(dB))

def classify_acoustic_category(
    noise_db: Union[np.ndarray, pd.Series, list]
) -> np.ndarray:
    """
    ISO-style acoustic-comfort categories from indoor LAeq (dB).
    Adapted from NF S31-080:2006.

    Limits
    -------
    • A :  < 35 dB  
    • B :  35 ≤ dB < 45  
    • C :  45 ≤ dB < 65  
    • D :  ≥ 65 dB
    """
    n = np.asarray(noise_db, dtype=float)
    cat = np.full(n.shape, "NC", dtype="<U2")

    cat[n < 35]                              = "A"
    cat[(n >= 35) & (n < 45)]                = "B"
    cat[(n >= 45) & (n < 65)]                = "C"
    cat[n >= 65]                             = "D"

    return cat

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# VISUAL COMFORT 
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _yong_raw(lux):
    lux = np.asarray(lux)
    raw = np.full_like(lux, np.nan, dtype=float)

    mask1 = (125 <= lux) & (lux < 391)
    raw[mask1] = 10 ** (0.0012 * lux[mask1] + 0.85)

    mask2 = (lux >= 391) & (lux <= 2000)
    raw[mask2] = 10 ** 1.32
    return raw

def yong_score(lux, *, min_score=10, max_score=70):
    """
    Transformed visual comfort score on 1-5 scale.
    Returns np.nan for lux outside 125-2000 range.
    """
    raw = _yong_raw(lux)
    score = 1 + (raw - min_score) / (max_score - min_score) * 4
    return score

def kpi_vis_score(lux: pd.Series) -> pd.Series:
    """
    KPI-based visual comfort, 1 = best (450-550 lx), larger = worse.
    Outside the band the penalty grows linearly with the distance.
    """
    center = 500
    band   = 50 
    idx = (lux < center - band) | (lux > center + band)
    score = lux.copy()
    score.loc[idx] = 1
    score.loc[~idx] = 10
    return score

def classify_visual_category(
    lux_array: Union[np.ndarray, pd.Series, list]
) -> np.ndarray:
    """
    Classify visual-comfort category from (illuminance) luminance.
    Adapted from EN 12464-1:2021.

    Limits (lux)
    ------------
    • A : 300 – 500  
    • B : 200 – 300  **or** 500 – 700  
    • C : < 200  or  ≥ 700  
    """
    lux = np.asarray(lux_array, dtype=float)
    cat = np.full(lux.shape, "NC", dtype="<U2")      # default “NC”

    mask_a = (lux >= 300) & (lux < 500)
    cat[mask_a] = "A"

    mask_b = ((lux >= 200) & (lux < 300)) | ((lux >= 500) & (lux < 700))
    cat[mask_b & ~mask_a] = "B"

    mask_c = (lux < 200) | (lux >= 700)
    cat[mask_c & ~(mask_a | mask_b)] = "C"

    return cat

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# IAQ ESTIMATE
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def band_to_class(
    x: Union[np.ndarray, pd.Series, list],
    edges: Sequence[float],     # ascending, without ±inf
    labels: Sequence[str],      # must be len(edges)+1
) -> np.ndarray:
    """
    Vectorised: assign each x a class label; NaN / out-of-range ->'NC'.
    """
    arr   = np.asarray(x, dtype=float)
    class_arr = np.full(arr.shape, "NC", dtype="<U2")          # default NC
    bands = np.digitize(arr, bins=edges, right=False)          # 0 … n
    valid = ~np.isnan(arr)                                     # ignore NaN
    class_arr[valid] = np.array(labels, dtype="<U2")[bands[valid]]
    return class_arr

def classify_co2_category(ppm: Union[np.ndarray, pd.Series, list]) -> np.ndarray:
    return band_to_class(ppm, [550, 800, 1350], ["A", "B", "C", "D"])

def classify_co_category(ppm: Union[np.ndarray, pd.Series, list]) -> np.ndarray:
    return band_to_class(ppm, [35], ["A", "B"])

def classify_tvoc_category(ppb: Union[np.ndarray, pd.Series, list]) -> np.ndarray:
    return band_to_class(ppb, [100], ["A", "B"])

def classify_pm10_category(ugm3: Union[np.ndarray, pd.Series, list]) -> np.ndarray:
    return band_to_class(ugm3, [2.083], ["A", "B"])

def classify_pm25_category(ugm3: Union[np.ndarray, pd.Series, list]) -> np.ndarray:
    return band_to_class(ugm3, [0.003], ["A", "B"])

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# metabolic rate helpers
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def get_human_surf_area(weight_kg: float, height_cm: float) -> float:
    """DuBois body surface area [m²]."""
    return 0.20247 * (height_cm / 100) ** 0.725 * weight_kg ** 0.425

def basal_metabolic_rate(row) -> float:
    """Simplified Harris–Benedict (kcal day⁻¹) ->convert to W."""
    if row["gender"].lower().startswith("m"):
        kcal = 66.47 + 13.75 * row["weight_kg"] + 5 * row["height_cm"] - 6.76 * row["age"]
    else:
        kcal = 655.1 + 9.56 * row["weight_kg"] + 1.85 * row["height_cm"] - 4.68 * row["age"]
    return kcal * 0.048425  # kcal/d ->W

def metabolic_rate_fanger(bmr_W: float, area_m2: float) -> float:
    """Metabolic rate in W m⁻²."""
    return bmr_W / area_m2

def wm2_to_met(W_m2: float) -> float:
    return W_m2 / 58.0
