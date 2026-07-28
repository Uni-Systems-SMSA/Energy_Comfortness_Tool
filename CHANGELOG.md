# CHANGELOG - Energy Comfortness Tool

## [Unreleased] - 2026-07-23

### 🎨 UI & Dashboard Modifications (`dashboard/app.py`)
- **Energy Simulation Tab (`⚡ Energy Simulation`)**:
  - Rebound tab results to filter dynamically by selected building (`st.session_state["building_filter"]`) instead of fixed space-specific filtering.
  - Enabled **Building-Wide View**: Displays total energy footprint for the entire selected building and provides comparative visualization for all building spaces together.
- **Dev Tools Dynamic Space Energy Query**:
  - Updated sidebar Dev Tools button to dynamically read current selected space from `st.session_state["space_filter"]`.
  - Fixed query target label to display selected space (e.g. `🔋 Test Energy Query (Chapel)`).
- **Space Mapping & Resolution Logic**:
  - Updated `_load_space_names_from_csv` to dynamically locate `space.csv` directly inside the simulation results directory (`eplus_results_path`) associated with each building in PostgreSQL.
  - Replaced legacy session state key `"sensor_filter"` with `"space_filter"` across all UI query handlers.
- **Database Query Filtering (`_get_energy_data_from_database`)**:
  - Added support for `building_id` parameter to allow building-level DB queries without restricting results to single space IDs.
  - Fixed time-series calculation logic to handle single-mode (Heating only / Cooling only) EnergyPlus simulations.

### 🏛️ Multi-Building Codebase Support
- Extended application logic to support seamless switching and rendering for multiple buildings (`CERTH Smart House`, `Capella Brancacci_Florence`).
- Updated zone-name resolution and zone mapping logic to support multi-zone buildings with custom zone identifiers.

### ⚡ EnergyPlus Pipeline & Weather Simulation Fixes (`ece/`)
- **Dynamic Date Range Configuration (`ece/pipeline_eplus.py` & `ece/pipeline_eplus_wrapper.py`)**:
  - Added CLI arguments `--start-date` and `--end-date` to allow dynamic `RunPeriod` dates (`run_period_start_month`, `run_period_start_day`, `run_period_end_month`, `run_period_end_day`) matching the user's selected UI time window.
- **365-Day Weather File Padding (`ece/pipeline_weather.py`)**:
  - Updated `_build_full_year_epw` to reindex weather data to a complete 8,760-hour annual range using forward/backward fill (`.ffill().bfill()`). Ensures EnergyPlus `DesignDay` sizing pass passes without `12/21` rewind fatal errors.
- **Cross-Year Split-Run Enhancements (`ece/utils/split_run.py`)**:
  - Fixed space ID passing in `generate_weather_for_subperiod` to query exact sensor rows in DB.
  - Fixed `merge_runs` invocation to pass extracted subperiod CSV paths and year lists for multi-year cross-runs.

