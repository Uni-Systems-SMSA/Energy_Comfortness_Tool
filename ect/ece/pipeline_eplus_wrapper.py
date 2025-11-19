# -*- coding: utf-8 -*-
"""
ece.pipeline_eplus_wrapper
=========================

Wrapper functions to call the EnergyPlus pipeline from the main application
using conda run to execute in the bim2sim environment.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Dict, Any

from ece.utils.logging import init_logger

logger = init_logger(__name__)


def _get_conda_executable() -> str:
    """
    Get the path to the conda executable.
    
    Returns
    -------
    str
        Path to conda executable
    """
    # First check CONDA_EXE environment variable
    conda_exe = os.environ.get('CONDA_EXE')
    if conda_exe and Path(conda_exe).exists():
        return conda_exe
    
    # Try to find conda in common locations
    common_paths = [
        '/home/ect/miniconda3/bin/conda',
        os.path.expanduser('~/miniconda3/bin/conda'),
        os.path.expanduser('~/anaconda3/bin/conda'),
        '/opt/conda/bin/conda',
        '/usr/local/bin/conda'
    ]
    
    for conda_path in common_paths:
        if Path(conda_path).exists():
            logger.info(f"Found conda at: {conda_path}")
            return conda_path
    
    # Fallback to 'conda' and let the system PATH resolve it
    logger.warning("Could not find conda in common locations, using 'conda' from PATH")
    return 'conda'


def _sanitize_path_for_subprocess(path_str: str) -> str:
    """
    Sanitize file paths to avoid Unicode issues in subprocess calls.
    
    Parameters
    ----------
    path_str : str
        Original path string
        
    Returns
    -------
    str
        Sanitized path string safe for subprocess
    """
    # Replace Unicode replacement character (U+FFFD) which might cause "ffd" errors
    sanitized = path_str.replace('\ufffd', '?')
    
    # Replace other problematic Unicode characters
    sanitized = sanitized.encode('ascii', errors='replace').decode('ascii')
    
    return sanitized


def run_eplus_simulation_async(
    ifc_file_path: Path,
    weather_file_path: Path,
    sensor_id: str,
    project_base_dir: Optional[Path] = None,
    ep_install_path: str = '/usr/local/EnergyPlus-9-4-0',
    conda_env_name: str = 'bim2sim'
) -> Dict[str, Any]:
    """
    Run EnergyPlus simulation asynchronously using conda run.
    
    This function calls the pipeline_eplus.py script in the bim2sim conda
    environment and returns the results.
    
    Parameters
    ----------
    ifc_file_path : Path
        Path to IFC building model file
    weather_file_path : Path
        Path to EPW weather file
    sensor_id : str
        Sensor identifier for organizing simulation results
    project_base_dir : Optional[Path]
        Base directory for simulation project
    ep_install_path : str
        Path to EnergyPlus installation directory
    conda_env_name : str
        Name of the conda environment containing bim2sim
        
    Returns
    -------
    Dict[str, Any]
        Dictionary containing simulation results and status
    """
    # Convert paths to absolute paths and sanitize for subprocess
    ifc_file_path = Path(ifc_file_path).resolve()
    weather_file_path = Path(weather_file_path).resolve()
    
    # Sanitize paths to prevent Unicode issues
    ifc_path_sanitized = _sanitize_path_for_subprocess(str(ifc_file_path))
    weather_path_sanitized = _sanitize_path_for_subprocess(str(weather_file_path))
    sensor_id_sanitized = _sanitize_path_for_subprocess(sensor_id)
    
    logger.info(f"Original paths:")
    logger.info(f"  IFC: {ifc_file_path}")
    logger.info(f"  Weather: {weather_file_path}")
    logger.info(f"  Sensor: {sensor_id}")
    
    if str(ifc_file_path) != ifc_path_sanitized:
        logger.warning(f"IFC path sanitized: {ifc_path_sanitized}")
    if str(weather_file_path) != weather_path_sanitized:
        logger.warning(f"Weather path sanitized: {weather_path_sanitized}")
    if sensor_id != sensor_id_sanitized:
        logger.warning(f"Sensor ID sanitized: {sensor_id_sanitized}")
    
    # Get the pipeline script path
    pipeline_script = Path(__file__).parent / "pipeline_eplus.py"
    pipeline_script = pipeline_script.resolve()  # Get absolute path
    
    # Get conda executable path
    conda_exe = _get_conda_executable()
    logger.info(f"Using conda executable: {conda_exe}")
    
    # Build the conda run command with proper output capture
    # Ensure all paths are properly quoted and encoded
    cmd = [
        conda_exe, "run", 
        "-n", conda_env_name,
        "python", str(pipeline_script),
        "--ifc", ifc_path_sanitized,
        "--weather", weather_path_sanitized,
        "--sensor", sensor_id_sanitized,
        "--ep-path", ep_install_path
    ]
    
    # Add project directory if specified
    if project_base_dir:
        project_dir_sanitized = _sanitize_path_for_subprocess(str(Path(project_base_dir).resolve()))
        cmd.extend(["--project-dir", project_dir_sanitized])
    
    logger.info(f"Running EnergyPlus simulation for sensor {sensor_id}")
    logger.info(f"IFC file: {ifc_file_path}")
    logger.info(f"Weather file: {weather_file_path}")
    logger.info(f"Project base dir: {project_base_dir}")
    logger.info(f"EP install path: {ep_install_path}")
    logger.info(f"Command: {' '.join(cmd)}")
    
    # DEBUG: Log more details about paths
    logger.info(f"DEBUG: IFC file absolute path: {Path(ifc_file_path).resolve()}")
    logger.info(f"DEBUG: Weather file absolute path: {Path(weather_file_path).resolve()}")
    if project_base_dir:
        logger.info(f"DEBUG: Project dir absolute path: {Path(project_base_dir).resolve()}")
    
    # Log command arguments separately for Unicode debugging
    logger.info("Command arguments for Unicode debugging:")
    for i, arg in enumerate(cmd):
        try:
            arg_ascii = arg.encode('ascii', errors='replace').decode('ascii')
            logger.info(f"  [{i}] {arg} (ASCII: {arg_ascii})")
        except Exception as e:
            logger.warning(f"  [{i}] {arg} (encoding issue: {e})")
    
    try:
        # Run the subprocess with real-time output capture
        logger.info("Starting EnergyPlus simulation subprocess...")
        
        # Debug: Log the working directory
        working_dir = Path(__file__).parent.parent
        logger.info(f"DEBUG: BIM2SIM subprocess working directory: {working_dir}")
        logger.info(f"DEBUG: BIM2SIM subprocess working directory exists: {working_dir.exists()}")
        logger.info(f"DEBUG: Current Python working directory: {os.getcwd()}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',  # Replace problematic Unicode characters
            timeout=3600,  # 1 hour timeout
            cwd=working_dir,  # Run from project root
            env={
                **os.environ, 
                'PYTHONIOENCODING': 'utf-8',  # Force UTF-8 encoding for Python subprocess
                'PYTHONPATH': '/app/bim2sim'  # Add bim2sim to Python path for conda environment
            }
        )
        
        # Log all subprocess output for debugging
        logger.info(f"Process return code: {result.returncode}")
        
        # Log stdout (this contains bim2sim logs)
        if result.stdout:
            logger.info("=== SUBPROCESS STDOUT (includes bim2sim logs) ===")
            for i, line in enumerate(result.stdout.split('\n')):
                if line.strip():  # Only log non-empty lines
                    logger.info(f"STDOUT[{i:03d}]: {line}")
            logger.info("=== END SUBPROCESS STDOUT ===")
        
        # Log stderr (this contains error messages)
        if result.stderr:
            logger.info("=== SUBPROCESS STDERR ===")
            for i, line in enumerate(result.stderr.split('\n')):
                if line.strip():  # Only log non-empty lines
                    logger.error(f"STDERR[{i:03d}]: {line}")
            logger.info("=== END SUBPROCESS STDERR ===")
        
        # Parse the JSON output from the simulation
        output_lines = result.stdout.strip().split('\n')
        error_lines = result.stderr.strip().split('\n') if result.stderr else []
        
        json_start = -1
        
        # Find the start of JSON output
        for i, line in enumerate(output_lines):
            if line.strip().startswith('{'):
                json_start = i
                break
        
        if json_start >= 0:
            json_output = '\n'.join(output_lines[json_start:])
            try:
                simulation_results = json.loads(json_output)
            except json.JSONDecodeError:
                simulation_results = {
                    "success": False,
                    "error": "Failed to parse simulation results",
                    "raw_output": result.stdout
                }
        else:
            simulation_results = {
                "success": False,
                "error": "No JSON output found",
                "raw_output": result.stdout
            }
        
        # Add process information
        simulation_results.update({
            "process_returncode": result.returncode,
            "process_stdout": result.stdout,
            "process_stderr": result.stderr
        })
        
        if result.returncode != 0:
            simulation_results["success"] = False
            error_msg = result.stderr or "Process failed with no stderr output"
            
            # Check for specific bim2sim import error
            if "bim2sim not available" in error_msg:
                error_msg += "\n\nTroubleshooting steps:"
                error_msg += "\n1. Verify bim2sim environment exists: conda env list"
                error_msg += "\n2. Test bim2sim import: conda run -n bim2sim python -c 'import bim2sim'"
                error_msg += f"\n3. Check conda path: {cmd[0]}"
            
            if "error" not in simulation_results:
                simulation_results["error"] = f"Process failed with return code {result.returncode}: {error_msg}"
        
        logger.info(f"Simulation completed with return code: {result.returncode}")
        
        return simulation_results
        
    except subprocess.TimeoutExpired:
        error_msg = "Simulation timed out after 1 hour"
        logger.exception(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "message": "Simulation timed out"
        }
        
    except FileNotFoundError as e:
        error_msg = f"Failed to run simulation: {str(e)}"
        if 'conda' in str(e).lower():
            error_msg += f"\n\nConda executable not found. Tried: {cmd[0]}"
            error_msg += "\nPlease ensure conda is installed and accessible."
            error_msg += f"\nCurrent CONDA_EXE: {os.environ.get('CONDA_EXE', 'Not set')}"
            error_msg += f"\nCurrent PATH: {os.environ.get('PATH', 'Not set')}"
        logger.exception(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "message": "Pipeline execution failed - executable not found"
        }
    
    except Exception as e:
        error_msg = f"Failed to run simulation: {str(e)}"
        logger.exception(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "message": "Pipeline execution failed"
        }


def test_bim2sim_environment(conda_env_name: str = 'bim2sim') -> bool:
    """
    Test if the bim2sim conda environment is available and working.
    
    Parameters
    ----------
    conda_env_name : str
        Name of the conda environment to test
        
    Returns
    -------
    bool
        True if environment is available and bim2sim can be imported
    """
    try:
        # Get conda executable path
        conda_exe = _get_conda_executable()
        
        cmd = [
            conda_exe, "run", 
            "-n", conda_env_name,
            "python", "-c", "import bim2sim; print('bim2sim available')"
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',  # Replace problematic Unicode characters
            timeout=30
        )
        
        return result.returncode == 0 and "bim2sim available" in result.stdout
        
    except Exception as e:
        logger.warning(f"Failed to test bim2sim environment: {e}")
        return False


def get_simulation_status(project_path: Path) -> Dict[str, Any]:
    """
    Check the status of a simulation project.
    
    Parameters
    ----------
    project_path : Path
        Path to the simulation project directory
        
    Returns
    -------
    Dict[str, Any]
        Dictionary containing simulation status information
    """
    project_path = Path(project_path)
    
    status = {
        "project_exists": project_path.exists(),
        "project_path": str(project_path)
    }
    
    if project_path.exists():
        # Check for common EnergyPlus output files
        output_files = {
            "idf_file": list(project_path.glob("**/*.idf")),
            "epw_file": list(project_path.glob("**/*.epw")),
            "csv_results": list(project_path.glob("**/*.csv")),
            "html_results": list(project_path.glob("**/*.html")),
            "err_files": list(project_path.glob("**/*.err"))
        }
        
        status["output_files"] = {
            key: [str(f) for f in files] 
            for key, files in output_files.items()
        }
        
        # Check if simulation completed successfully
        err_files = output_files["err_files"]
        if err_files:
            # Check the last error file for completion status
            latest_err = max(err_files, key=lambda x: x.stat().st_mtime)
            try:
                with open(latest_err, 'r') as f:
                    err_content = f.read()
                    status["simulation_complete"] = "EnergyPlus Completed Successfully" in err_content
                    status["has_errors"] = "** Severe **" in err_content or "** Fatal **" in err_content
            except Exception:
                status["simulation_complete"] = False
                status["has_errors"] = True
        else:
            status["simulation_complete"] = False
            status["has_errors"] = False
    
    return status


def run_user_request(
    ifc_file_path: Path,
    weather_file_path: Path,
    sensor_id: str,
    start_date: str,
    end_date: str,
    project_base_dir: Optional[Path] = None,
    ep_install_path: str = '/usr/local/EnergyPlus-9-4-0',
    conda_env_name: str = 'bim2sim'
) -> Dict[str, Any]:
    """
    Run user request with automatic cross-year split-run support.
    
    This is the main facade function that determines whether to run a single 
    simulation or split across multiple years based on the date range.
    
    Parameters
    ----------
    ifc_file_path : Path
        Path to IFC building model file
    weather_file_path : Path
        Path to EPW weather file
    sensor_id : str
        Sensor identifier for organizing simulation results
    start_date : str
        Start date in format 'YYYY-MM-DD'
    end_date : str
        End date in format 'YYYY-MM-DD'
    project_base_dir : Optional[Path]
        Base directory for simulation project
    ep_install_path : str
        Path to EnergyPlus installation directory
    conda_env_name : str
        Name of the conda environment containing bim2sim
        
    Returns
    -------
    Dict[str, Any]
        Dictionary containing simulation results and status
    """
    from datetime import datetime
    from ece.utils.split_run import process_cross_year
    
    logger.info(f"Processing user request for sensor {sensor_id}")
    logger.info(f"Date range: {start_date} to {end_date}")
    
    try:
        # Parse dates to determine if cross-year split is needed
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        # Check if simulation spans multiple years
        if start_dt.year != end_dt.year:
            logger.info(f"Cross-year simulation detected ({start_dt.year} to {end_dt.year})")
            logger.info("Using split-run approach with EnergyPlus year normalization")
            
            # Use split-run functionality
            return process_cross_year(
                ifc_file_path=ifc_file_path,
                weather_file_path=weather_file_path,
                sensor_id=sensor_id,
                start_date=start_date,
                end_date=end_date,
                project_base_dir=project_base_dir,
                ep_install_path=ep_install_path,
                conda_env_name=conda_env_name,
                eplus_wrapper_func=run_eplus_simulation_async
            )
        else:
            logger.info(f"Single-year simulation for {start_dt.year}")
            logger.info("Using standard EnergyPlus pipeline")
            
            # Use existing single-year simulation
            result = run_eplus_simulation_async(
                ifc_file_path=ifc_file_path,
                weather_file_path=weather_file_path,
                sensor_id=sensor_id,
                project_base_dir=project_base_dir,
                ep_install_path=ep_install_path,
                conda_env_name=conda_env_name
            )
            
            # Add metadata to indicate this was a single-year run
            if isinstance(result, dict):
                result["split_run_used"] = False
                result["date_range"] = {
                    "start_date": start_date,
                    "end_date": end_date,
                    "spans_years": False
                }
            
            return result
            
    except ValueError as e:
        error_msg = f"Invalid date format: {str(e)}"
        logger.exception(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "message": "Date parsing failed - expected format: YYYY-MM-DD"
        }
        
    except Exception as e:
        error_msg = f"User request processing failed: {str(e)}"
        logger.exception(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "message": "Request processing failed"
        }
