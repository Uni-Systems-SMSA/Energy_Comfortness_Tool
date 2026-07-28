# -*- coding: utf-8 -*-
"""ECT energy simulation pipeline using bim2sim for IFC to IDF conversion and EnergyPlus execution."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional

# Monkeypatch collections/eppy for compatibility with Python 3.10+ and older eppy versions
import collections
import collections.abc
collections.MutableSequence = collections.abc.MutableSequence
collections.Iterable = collections.abc.Iterable
collections.Mapping = collections.abc.Mapping
collections.MutableMapping = collections.abc.MutableMapping
collections.Sequence = collections.abc.Sequence

import eppy.modeleditor
if not hasattr(eppy.modeleditor.IDF, 'removeallidfobjects'):
    def removeallidfobjects(self, idfobject):
        key = idfobject.key if hasattr(idfobject, 'key') else idfobject
        if isinstance(key, str):
            key = key.upper()
        while len(self.idfobjects[key]) > 0:
            self.popidfobject(key, 0)
    eppy.modeleditor.IDF.removeallidfobjects = removeallidfobjects

try:
    import bim2sim
    from bim2sim import Project, run_project, ConsoleDecisionHandler
    from bim2sim.utilities.types import IFCDomain
except ImportError:
    print("ERROR: bim2sim not available. Make sure you're running in the bim2sim conda environment.")
    sys.exit(1)


def run_energy_simulation(
    ifc_file_path: Path,
    weather_file_path: Path,
    sensor_id: str,
    project_base_dir: Optional[Path] = None,
    ep_install_path: str = '/usr/local/EnergyPlus-9-4-0',
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> dict:
    """
    Run a building performance simulation with the EnergyPlus backend.
    
    This function converts an IFC file to IDF format using bim2sim and runs
    an EnergyPlus simulation with the specified weather file.
    
    Parameters
    ----------
    ifc_file_path : Path
        Path to the IFC building model file
    weather_file_path : Path
        Path to the EPW weather file
    sensor_id : str
        Sensor identifier for organizing simulation results
    project_base_dir : Optional[Path]
        Base directory for simulation project. If None, uses eplus_sim directory
    ep_install_path : str
        Path to EnergyPlus installation directory
        
    Returns
    -------
    dict
        Dictionary containing simulation results and paths
    """
    # Convert to Path objects
    ifc_file_path = Path(ifc_file_path)
    weather_file_path = Path(weather_file_path)
    
    # Set up project directory structure
    if project_base_dir is None:
        project_base_dir = Path(__file__).parent.parent / "eplus_sim"
    else:
        project_base_dir = Path(project_base_dir)
    
    # Create sensor-specific project directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_name = f"sim_{sensor_id}_{timestamp}"
    project_path = project_base_dir / "results" / project_name
    project_path.mkdir(parents=True, exist_ok=True)
    
    # Validate input files
    if not ifc_file_path.exists():
        raise FileNotFoundError(f"IFC file not found: {ifc_file_path}")
    if not weather_file_path.exists():
        raise FileNotFoundError(f"Weather file not found: {weather_file_path}")
    
    # Set up IFC paths for bim2sim (architectural domain)
    ifc_paths = {
        IFCDomain.arch: ifc_file_path,
    }
    
    print(f"Creating EnergyPlus simulation project...")
    print(f"  Project directory: {project_path}")
    print(f"  IFC file: {ifc_file_path}")
    print(f"  Weather file: {weather_file_path}")
    print(f"  Sensor ID: {sensor_id}")
    
    try:
        # Create a bim2sim project with energyplus backend
        print(f"[bim2sim] Creating project with EnergyPlus backend...")
        project = Project.create(project_path, ifc_paths, 'energyplus')
        
        # Configure simulation settings
        print(f"[bim2sim] Configuring simulation settings...")
        project.sim_settings.weather_file_path = weather_file_path
        project.sim_settings.ep_install_path = ep_install_path
        
        if start_date and end_date:
            try:
                s_dt = datetime.strptime(start_date, "%Y-%m-%d")
                e_dt = datetime.strptime(end_date, "%Y-%m-%d")
                project.sim_settings.run_full_simulation = False
                project.sim_settings.set_run_period = True
                project.sim_settings.run_period_start_month = s_dt.month
                project.sim_settings.run_period_start_day = s_dt.day
                project.sim_settings.run_period_end_month = e_dt.month
                project.sim_settings.run_period_end_day = e_dt.day
                print(f"[bim2sim] Custom RunPeriod configured: {start_date} -> {end_date}")
            except Exception as e_date:
                print(f"[bim2sim] WARNING: Failed to parse dates ({start_date}, {end_date}): {e_date}. Falling back to full run.")
                project.sim_settings.run_full_simulation = True
        else:
            project.sim_settings.run_full_simulation = True

        # Use DesignDay sizing instead of Typical (SummerTypical/WinterTypical).
        # The 'Typical' mode requires TypicalExtremeWeeks sections in the EPW file
        # which are absent in Open-Meteo / programmatically generated EPW files.
        project.sim_settings.system_weather_sizing = 'DesignDay'
        project.sim_settings.cooling_tz_overwrite = True
        print(f"[bim2sim] Weather file: {weather_file_path}")
        print(f"[bim2sim] EnergyPlus path: {ep_install_path}")
        print(f"[bim2sim] Starting simulation...")
        print(f"[bim2sim] This may take several minutes depending on model complexity...")
        
        # Enable verbose logging for bim2sim
        import logging
        logging.getLogger('bim2sim').setLevel(logging.INFO)
        
        # Run the project with ConsoleDecisionHandler for interactive input
        print(f"[bim2sim] Running project with ConsoleDecisionHandler...")
        ret_val = run_project(project, ConsoleDecisionHandler())
        if ret_val != 0:
            raise RuntimeError("bim2sim execution finished but was not successful")
        
        print(f"[bim2sim] ✅ Simulation completed successfully!")
        print(f"[bim2sim] Results saved to: {project_path}")
        
        # List generated files for debugging
        result_files = list(project_path.rglob("*"))
        print(f"[bim2sim] Generated {len(result_files)} files:")
        for f in result_files[:10]:  # Show first 10 files
            print(f"[bim2sim]   - {f.name}")
        if len(result_files) > 10:
            print(f"[bim2sim]   ... and {len(result_files) - 10} more files")
        
        # Return results dictionary
        results = {
            "success": True,
            "project_path": str(project_path),
            "sensor_id": sensor_id,
            "timestamp": timestamp,
            "ifc_file": str(ifc_file_path),
            "weather_file": str(weather_file_path),
            "message": "Simulation completed successfully",
            "generated_files": len(result_files)
        }
        
    except Exception as e:
        error_msg = f"Simulation failed: {str(e)}"
        print(f"[bim2sim] ❌ ERROR: {error_msg}")
        print(f"[bim2sim] Exception type: {type(e).__name__}")
        
        # Try to provide more detailed error information
        import traceback
        print(f"[bim2sim] Full traceback:")
        traceback.print_exc()
        
        results = {
            "success": False,
            "project_path": str(project_path),
            "sensor_id": sensor_id,
            "timestamp": timestamp,
            "error": error_msg,
            "error_type": type(e).__name__,
            "message": "Simulation failed"
        }
    
    return results


def run_example_simulation():
    """
    Run an example building performance simulation.
    
    This is the original example function, kept for backward compatibility
    and testing purposes.
    """
    # Create a temp directory for the project
    project_path = Path(
        tempfile.TemporaryDirectory(prefix='bim2sim_example1').name)

    # Set the ifc path to use and define which domain the IFC belongs to
    ifc_paths = {
        IFCDomain.arch:
            Path(bim2sim.__file__).parent.parent /
            'test/resources/arch/ifc/AC20-FZK-Haus.ifc',
    }

    # Create a project including the folder structure for the project with
    # energyplus as backend
    project = Project.create(project_path, ifc_paths, 'energyplus')

    # set weather file data
    project.sim_settings.weather_file_path = (
            # Path(bim2sim.__file__).parent.parent /
            # 'test/resources/weather_files/DEU_NW_Aachen.105010_TMYx.epw')
            r"C:\Software\github\unisystems\2024_H2020_AccesS\simulate_data\output.epw"
    )
    # Set the install path to your EnergyPlus installation according to your
    # system requirements
    project.sim_settings.ep_install_path = '/usr/local/EnergyPlus-9-4-0'

    # run annual simulation for EnergyPlus
    project.sim_settings.run_full_simulation = True

    # Set other simulation settings, otherwise all settings are set to default

    # Run the project with the ConsoleDecisionHandler. This allows interactive
    # input to answer upcoming questions regarding the imported IFC.
    run_project(project, ConsoleDecisionHandler())


def main():
    """
    CLI interface for running EnergyPlus simulations.
    
    This function allows the pipeline to be called from the command line
    with the bim2sim conda environment activated.
    """
    parser = argparse.ArgumentParser(
        description="Run EnergyPlus building simulation using bim2sim",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline_eplus.py --ifc building.ifc --weather weather.epw --sensor office_001
  python pipeline_eplus.py --ifc building.ifc --weather weather.epw --sensor office_001 --project-dir /path/to/sims
        """
    )
    
    parser.add_argument(
        "--ifc", 
        type=str, 
        required=True,
        help="Path to IFC building model file"
    )
    
    parser.add_argument(
        "--weather", 
        type=str, 
        required=True,
        help="Path to EPW weather file"
    )
    
    parser.add_argument(
        "--sensor", 
        type=str, 
        required=True,
        help="Sensor ID for organizing simulation results"
    )
    
    parser.add_argument(
        "--project-dir", 
        type=str, 
        default=None,
        help="Base directory for simulation project (default: eplus_sim)"
    )
    
    parser.add_argument(
        "--ep-path", 
        type=str, 
        default="/usr/local/EnergyPlus-9-4-0",
        help="Path to EnergyPlus installation (default: /usr/local/EnergyPlus-9-4-0)"
    )
    
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Simulation start date (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Simulation end date (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--output-json",
        type=str,
        default=None,
        help="Path to save JSON results file"
    )
    
    args = parser.parse_args()
    
    try:
        # Run the simulation
        results = run_energy_simulation(
            ifc_file_path=Path(args.ifc),
            weather_file_path=Path(args.weather),
            sensor_id=args.sensor,
            project_base_dir=Path(args.project_dir) if args.project_dir else None,
            ep_install_path=args.ep_path,
            start_date=args.start_date,
            end_date=args.end_date
        )
        
        # Output results as JSON
        print("\n" + "="*50)
        print("SIMULATION RESULTS:")
        print("="*50)
        print(json.dumps(results, indent=2))
        
        # Save results to JSON file if requested
        if args.output_json:
            output_path = Path(args.output_json)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\nResults saved to: {output_path}")
        
        # Exit with appropriate code
        sys.exit(0 if results["success"] else 1)
        
    except Exception as e:
        error_result = {
            "success": False,
            "error": str(e),
            "message": "Pipeline execution failed"
        }
        print("\n" + "="*50)
        print("PIPELINE ERROR:")
        print("="*50)
        print(json.dumps(error_result, indent=2))
        sys.exit(1)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        # No arguments, run example
        print("Running example simulation...")
        run_example_simulation()
    else:
        # CLI mode
        main()
