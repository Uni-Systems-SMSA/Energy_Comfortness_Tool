# -*- coding: utf-8 -*-
"""
Test suite for EnergyPlus cross-year split-run functionality.

Tests cover:
- Date range splitting across years
- Timestamp normalization with edge cases
- RunPeriod configuration
- Result merging and validation
- Error handling and edge cases
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, date
from unittest.mock import MagicMock, patch, mock_open
import pandas as pd
import json

from ece.utils.split_run import (
    split_into_subperiods,
    configure_runperiod,
    normalize_timestamp_add_year,
    merge_runs,
    process_cross_year
)


class TestSplitIntoSubperiods:
    """Test the date range splitting functionality."""
    
    def test_single_year_range(self):
        """Test that single-year ranges return one period."""
        start_date = "2024-06-01"
        end_date = "2024-08-31"
        
        periods = split_into_subperiods(start_date, end_date)
        
        assert len(periods) == 1
        assert periods[0]["start_date"] == "2024-06-01"
        assert periods[0]["end_date"] == "2024-08-31"
        assert periods[0]["year"] == 2024
    
    def test_cross_year_range(self):
        """Test cross-year range splitting."""
        start_date = "2024-11-15"
        end_date = "2025-03-20"
        
        periods = split_into_subperiods(start_date, end_date)
        
        assert len(periods) == 2
        
        # First period: 2024-11-15 to 2024-12-31
        assert periods[0]["start_date"] == "2024-11-15"
        assert periods[0]["end_date"] == "2024-12-31"
        assert periods[0]["year"] == 2024
        
        # Second period: 2025-01-01 to 2025-03-20
        assert periods[1]["start_date"] == "2025-01-01"
        assert periods[1]["end_date"] == "2025-03-20"
        assert periods[1]["year"] == 2025
    
    def test_multi_year_range(self):
        """Test range spanning multiple full years."""
        start_date = "2023-09-03"
        end_date = "2025-11-07"
        
        periods = split_into_subperiods(start_date, end_date)
        
        assert len(periods) == 3
        
        # First period: 2023-09-03 to 2023-12-31
        assert periods[0]["start_date"] == "2023-09-03"
        assert periods[0]["end_date"] == "2023-12-31"
        assert periods[0]["year"] == 2023
        
        # Second period: 2024-01-01 to 2024-12-31
        assert periods[1]["start_date"] == "2024-01-01"
        assert periods[1]["end_date"] == "2024-12-31"
        assert periods[1]["year"] == 2024
        
        # Third period: 2025-01-01 to 2025-11-07
        assert periods[2]["start_date"] == "2025-01-01"
        assert periods[2]["end_date"] == "2025-11-07"
        assert periods[2]["year"] == 2025
    
    def test_invalid_date_format(self):
        """Test handling of invalid date formats."""
        with pytest.raises(ValueError):
            split_into_subperiods("2024/06/01", "2024-08-31")
    
    def test_end_before_start(self):
        """Test handling of end date before start date."""
        with pytest.raises(ValueError):
            split_into_subperiods("2024-08-31", "2024-06-01")


class TestConfigureRunperiod:
    """Test RunPeriod configuration for BIM2SIM."""
    
    @patch('ece.utils.split_run.Path')
    def test_configure_runperiod_success(self, mock_path):
        """Test successful RunPeriod configuration."""
        # Setup mock file system
        mock_project_path = MagicMock()
        mock_path.return_value = mock_project_path
        mock_project_path.exists.return_value = True
        
        # Mock glob to return IDF file
        mock_idf_file = Path("/mock/project/model.idf")
        mock_project_path.glob.return_value = [mock_idf_file]
        
        # Mock BIM2SIM Project
        mock_project = MagicMock()
        mock_project.sim_settings.output_manager.sim_settings = {}
        
        with patch('ece.utils.split_run.Project', return_value=mock_project):
            result = configure_runperiod("/mock/project", 6, 1, 8, 31)
            
            assert result["success"] is True
            assert mock_project.sim_settings.output_manager.sim_settings["begin_month"] == 6
            assert mock_project.sim_settings.output_manager.sim_settings["begin_day_of_month"] == 1
            assert mock_project.sim_settings.output_manager.sim_settings["end_month"] == 8
            assert mock_project.sim_settings.output_manager.sim_settings["end_day_of_month"] == 31
    
    @patch('ece.utils.split_run.Path')
    def test_configure_runperiod_no_idf(self, mock_path):
        """Test RunPeriod configuration when no IDF file exists."""
        mock_project_path = MagicMock()
        mock_path.return_value = mock_project_path
        mock_project_path.exists.return_value = True
        mock_project_path.glob.return_value = []  # No IDF files
        
        result = configure_runperiod("/mock/project", 6, 1, 8, 31)
        
        assert result["success"] is False
        assert "No IDF file found" in result["error"]
    
    def test_configure_runperiod_invalid_dates(self):
        """Test RunPeriod configuration with invalid dates."""
        # Test invalid month
        result = configure_runperiod("/mock/project", 13, 1, 8, 31)
        assert result["success"] is False
        assert "Invalid month" in result["error"]
        
        # Test invalid day
        result = configure_runperiod("/mock/project", 6, 32, 8, 31)
        assert result["success"] is False
        assert "Invalid day" in result["error"]


class TestNormalizeTimestampAddYear:
    """Test timestamp normalization functionality."""
    
    def test_normal_timestamp(self):
        """Test normal timestamp normalization."""
        df = pd.DataFrame({
            'Date/Time': ['01/15  01:00:00', '01/15  12:30:00'],
            'Temperature': [20.5, 22.1]
        })
        
        result = normalize_timestamp_add_year(df, 2024)
        
        expected_timestamps = [
            '2024-01-15 01:00:00',
            '2024-01-15 12:30:00'
        ]
        
        assert result['Date/Time'].tolist() == expected_timestamps
    
    def test_midnight_edge_case(self):
        """Test 24:00:00 timestamp handling."""
        df = pd.DataFrame({
            'Date/Time': ['01/15  24:00:00', '01/16  01:00:00'],
            'Temperature': [20.5, 22.1]
        })
        
        result = normalize_timestamp_add_year(df, 2024)
        
        expected_timestamps = [
            '2024-01-16 00:00:00',  # 24:00:00 becomes next day 00:00:00
            '2024-01-16 01:00:00'
        ]
        
        assert result['Date/Time'].tolist() == expected_timestamps
    
    def test_leap_year_february(self):
        """Test leap year February handling."""
        df = pd.DataFrame({
            'Date/Time': ['02/28  23:00:00', '02/29  12:00:00'],
            'Temperature': [18.5, 19.2]
        })
        
        # Leap year
        result = normalize_timestamp_add_year(df, 2024)
        expected_timestamps = [
            '2024-02-28 23:00:00',
            '2024-02-29 12:00:00'
        ]
        assert result['Date/Time'].tolist() == expected_timestamps
        
        # Non-leap year (should skip Feb 29)
        result = normalize_timestamp_add_year(df, 2023)
        expected_timestamps = [
            '2023-02-28 23:00:00'
            # Feb 29 should be filtered out
        ]
        assert result['Date/Time'].tolist() == expected_timestamps
    
    def test_year_boundary_handling(self):
        """Test year boundary edge cases."""
        df = pd.DataFrame({
            'Date/Time': ['12/31  23:00:00', '12/31  24:00:00'],
            'Temperature': [15.5, 16.1]
        })
        
        result = normalize_timestamp_add_year(df, 2024)
        
        expected_timestamps = [
            '2024-12-31 23:00:00',
            '2025-01-01 00:00:00'  # 24:00:00 on Dec 31 becomes Jan 1 next year
        ]
        
        assert result['Date/Time'].tolist() == expected_timestamps
    
    def test_invalid_date_handling(self):
        """Test handling of invalid dates."""
        df = pd.DataFrame({
            'Date/Time': ['13/01  12:00:00', '02/30  15:00:00'],  # Invalid dates
            'Temperature': [20.5, 22.1]
        })
        
        result = normalize_timestamp_add_year(df, 2024)
        
        # Should return empty DataFrame after filtering invalid dates
        assert len(result) == 0


class TestMergeRuns:
    """Test result merging functionality."""
    
    def test_successful_merge(self):
        """Test successful merging of multiple runs."""
        # Create mock run results
        run_results = [
            {
                "success": True,
                "csv_file": "/mock/run1/results.csv",
                "metadata": {"year": 2024, "start_date": "2024-11-15", "end_date": "2024-12-31"}
            },
            {
                "success": True,
                "csv_file": "/mock/run2/results.csv",
                "metadata": {"year": 2025, "start_date": "2025-01-01", "end_date": "2025-03-20"}
            }
        ]
        
        # Mock CSV data
        csv_data_1 = pd.DataFrame({
            'Date/Time': ['2024-11-15 01:00:00', '2024-11-15 02:00:00'],
            'Temperature': [18.5, 19.2]
        })
        
        csv_data_2 = pd.DataFrame({
            'Date/Time': ['2025-01-01 01:00:00', '2025-01-01 02:00:00'],
            'Temperature': [15.1, 16.8]
        })
        
        with patch('pandas.read_csv') as mock_read_csv:
            mock_read_csv.side_effect = [csv_data_1, csv_data_2]
            
            result = merge_runs(run_results, "merged_sensor_123")
        
        assert result["success"] is True
        assert "merged_csv_file" in result
        assert result["total_records"] == 4
        assert result["metadata"]["spans_years"] is True
        assert len(result["metadata"]["subperiods"]) == 2
    
    def test_merge_with_failed_run(self):
        """Test merging when one run failed."""
        run_results = [
            {
                "success": True,
                "csv_file": "/mock/run1/results.csv",
                "metadata": {"year": 2024}
            },
            {
                "success": False,
                "error": "Simulation failed",
                "metadata": {"year": 2025}
            }
        ]
        
        result = merge_runs(run_results, "sensor_123")
        
        assert result["success"] is False
        assert "Run for year 2025 failed" in result["error"]
    
    def test_merge_empty_results(self):
        """Test merging with empty results."""
        result = merge_runs([], "sensor_123")
        
        assert result["success"] is False
        assert "No run results to merge" in result["error"]
    
    def test_timestamp_monotonicity_validation(self):
        """Test timestamp monotonicity validation."""
        run_results = [
            {
                "success": True,
                "csv_file": "/mock/run1/results.csv",
                "metadata": {"year": 2024}
            }
        ]
        
        # CSV with non-monotonic timestamps
        csv_data = pd.DataFrame({
            'Date/Time': ['2024-11-15 02:00:00', '2024-11-15 01:00:00'],  # Wrong order
            'Temperature': [18.5, 19.2]
        })
        
        with patch('pandas.read_csv', return_value=csv_data):
            result = merge_runs(run_results, "sensor_123")
        
        assert result["success"] is False
        assert "not monotonically increasing" in result["error"]


class TestProcessCrossYear:
    """Test the main cross-year processing function."""
    
    @patch('ece.utils.split_run.merge_runs')
    @patch('ece.utils.split_run.configure_runperiod')
    def test_process_cross_year_success(self, mock_configure, mock_merge):
        """Test successful cross-year processing."""
        # Setup mocks
        mock_configure.return_value = {"success": True}
        mock_merge.return_value = {
            "success": True,
            "merged_csv_file": "/mock/merged.csv",
            "total_records": 1000
        }
        
        # Mock EnergyPlus wrapper function
        mock_eplus_func = MagicMock()
        mock_eplus_func.return_value = {
            "success": True,
            "csv_file": "/mock/results.csv",
            "message": "Simulation completed"
        }
        
        result = process_cross_year(
            ifc_file_path=Path("/mock/model.ifc"),
            weather_file_path=Path("/mock/weather.epw"),
            sensor_id="test_sensor",
            start_date="2024-11-15",
            end_date="2025-03-20",
            eplus_wrapper_func=mock_eplus_func
        )
        
        assert result["success"] is True
        assert result["split_run_used"] is True
        assert "merged_csv_file" in result
        
        # Verify EnergyPlus function was called for each subperiod
        assert mock_eplus_func.call_count == 2
        
        # Verify RunPeriod configuration was called
        assert mock_configure.call_count == 2
    
    @patch('ece.utils.split_run.configure_runperiod')
    def test_process_cross_year_config_failure(self, mock_configure):
        """Test cross-year processing with configuration failure."""
        mock_configure.return_value = {
            "success": False,
            "error": "Failed to configure RunPeriod"
        }
        
        mock_eplus_func = MagicMock()
        
        result = process_cross_year(
            ifc_file_path=Path("/mock/model.ifc"),
            weather_file_path=Path("/mock/weather.epw"),
            sensor_id="test_sensor",
            start_date="2024-11-15",
            end_date="2025-03-20",
            eplus_wrapper_func=mock_eplus_func
        )
        
        assert result["success"] is False
        assert "Failed to configure RunPeriod" in result["error"]
        
        # EnergyPlus function should not be called if configuration fails
        assert mock_eplus_func.call_count == 0
    
    def test_process_cross_year_invalid_dates(self):
        """Test cross-year processing with invalid date range."""
        mock_eplus_func = MagicMock()
        
        result = process_cross_year(
            ifc_file_path=Path("/mock/model.ifc"),
            weather_file_path=Path("/mock/weather.epw"),
            sensor_id="test_sensor",
            start_date="2025-03-20",  # End before start
            end_date="2024-11-15",
            eplus_wrapper_func=mock_eplus_func
        )
        
        assert result["success"] is False
        assert "End date must be after start date" in result["error"]


class TestEdgeCases:
    """Test various edge cases and error conditions."""
    
    def test_leap_year_boundary(self):
        """Test leap year boundaries."""
        start_date = "2024-02-28"
        end_date = "2025-03-01"
        
        periods = split_into_subperiods(start_date, end_date)
        
        assert len(periods) == 2
        assert periods[0]["end_date"] == "2024-12-31"
        assert periods[1]["start_date"] == "2025-01-01"
    
    def test_single_day_cross_year(self):
        """Test single day spanning years (Dec 31 to Jan 1)."""
        start_date = "2024-12-31"
        end_date = "2025-01-01"
        
        periods = split_into_subperiods(start_date, end_date)
        
        assert len(periods) == 2
        assert periods[0]["start_date"] == "2024-12-31"
        assert periods[0]["end_date"] == "2024-12-31"
        assert periods[1]["start_date"] == "2025-01-01"
        assert periods[1]["end_date"] == "2025-01-01"
    
    def test_same_day_range(self):
        """Test single day range."""
        start_date = "2024-07-15"
        end_date = "2024-07-15"
        
        periods = split_into_subperiods(start_date, end_date)
        
        assert len(periods) == 1
        assert periods[0]["start_date"] == "2024-07-15"
        assert periods[0]["end_date"] == "2024-07-15"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
