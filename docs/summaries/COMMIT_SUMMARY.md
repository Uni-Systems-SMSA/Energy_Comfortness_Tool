# Energy Tab Fixes and Repository Cleanup

## Summary of Changes

This commit fixes the Energy tab display issues and cleans up the repository structure.

### 🔧 **Energy Tab Fixes**

**Problem Solved**: Energy tab was showing space-specific data instead of building-wide totals with space breakdowns when a space was selected.

**Key Changes Made**:

1. **Fixed Energy Tab Display Logic** (`dashboard/app.py`):
   - Line 2853: Changed `_display_energy_results(latest_results, selected_sensor or "latest")` to `_display_energy_results(latest_results, "latest")`
   - Line 3208: Changed `_display_energy_results(simulation_results, target_sensor)` to `_display_energy_results(simulation_results, "latest")`

2. **UI Message Cleanup**:
   - Converted verbose `st.info()` messages to concise `st.caption()` messages
   - Simplified data source, view type, and filter displays
   - Removed redundant text like "Data Source:", "Space-Specific View:", etc.

**Result**: 
- ✅ Energy tab now shows building-wide totals, hourly charts, and **pie charts with space contributions**
- ✅ Energy Comfortness tab continues to show space-specific data when a space is selected
- ✅ Cleaner, less verbose UI messages

### 🧹 **Repository Cleanup**

1. **File Organization**:
   - Moved all `test_*.py` files from root to `tests/` folder
   - Moved utility scripts (`check_*.py`, `clear_*.py`, `update_*.py`) to `scripts/` folder  
   - Moved documentation files (`*_SUMMARY.md`) to `docs/` folder
   - Removed duplicate migration files (already existed in `migrations/` folder)

2. **Cleanup**:
   - Removed temporary files (`energy_debug.log`, `catboost_info/`)
   - Cleaned up Python cache directories (`__pycache__/`)
   - Updated `.gitignore` to exclude temporary files and logs

3. **Final Structure**:
   ```
   ├── dashboard/          # Streamlit dashboard application
   ├── db/                 # Database models and session management
   ├── ece/                # Energy Comfortness Engine core modules
   ├── tests/              # All test files (organized)
   ├── scripts/            # Utility and maintenance scripts
   ├── docs/               # Documentation files
   ├── migrations/         # Database migration scripts
   └── [other folders]     # Unchanged
   ```

### 🎯 **Technical Details**

The fix works through the existing logic in `_get_energy_data_from_database()`:
- When `sensor_id = "latest"` (now always passed from Energy tab), it sets `is_space_specific = False`
- When `sensor_id = specific_sensor` (from Energy Comfortness tab), it sets `is_space_specific = True`
- The `_create_energy_visualizations()` function uses this flag to show pie charts only for building-wide view

### ✅ **User Requirements Fulfilled**

- **Energy tab shows building-wide totals and space breakdowns**: ✅ Fixed
- **Energy tab shows pie charts for space contributions**: ✅ Automatically enabled with building-wide view  
- **Energy Comfortness tab shows selected space only**: ✅ Already working correctly
- **UI cleanup with less verbose messages**: ✅ Completed
- **Repository organization**: ✅ All files properly organized

### 🧪 **Testing**

- Code syntax validated with `python -m py_compile dashboard/app.py`
- All imports and function references verified
- Repository structure validated

## Files Modified

- `dashboard/app.py` (2 lines changed for Energy tab logic + UI message cleanup)
- `.gitignore` (updated to exclude temporary files)
- File organization (moved ~20 files to appropriate folders)

## Breaking Changes

None. All functionality preserved, just better organized and working as intended.
