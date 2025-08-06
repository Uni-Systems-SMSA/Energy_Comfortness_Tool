"""
ece.pipeline_eplus
==================

EnergyPlus building simulation pipeline for the Energy Comfortness Tool.
This module provides functionality to run building energy simulations using
EnergyPlus with IFC models and weather data from the ECT database.
"""

from __future__ import annotations
import os
import sys
import tempfile
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

import pandas as pd
import numpy as np

# Add project root to path for imports
sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

from db.session import SessionLocal
from db.models import Weather, Measurement
from ece.utils.logging import get_logger

# Building simulation imports
try:
    import bim2sim
    from bim2sim import Project, run_project, ConsoleDecisionHandler
    from bim2sim.utilities.types import IFCDomain
    BIM2SIM_AVAILABLE = True
except ImportError:
    BIM2SIM_AVAILABLE = False
    logging.warning("bim2sim not available. Some features will be limited.")

try:
    import eppy
    from eppy import modeleditor
    EPPY_AVAILABLE = True
except ImportError:
    EPPY_AVAILABLE = False
    logging.warning("eppy not available. IDF manipulation will be limited.")

# Initialize logger
logger = get_logger(__name__)

# Configuration
EPLUS_SIM_DIR = Path("./eplus_sim")
WEATHER_DIR = EPLUS_SIM_DIR / "weather"
MODELS_DIR = EPLUS_SIM_DIR / "models"
IDF_DIR = EPLUS_SIM_DIR / "idf"
RESULTS_DIR = EPLUS_SIM_DIR / "results"
TEMPLATES_DIR = EPLUS_SIM_DIR / "templates"
LOGS_DIR = EPLUS_SIM_DIR / "logs"

# Ensure directories exist
for directory in [WEATHER_DIR, MODELS_DIR, IDF_DIR, RESULTS_DIR, TEMPLATES_DIR, LOGS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)


class EnergyPlusSimulation:
    """
    Class for managing EnergyPlus building energy simulations.
    """
    
    def __init__(
        self,
        project_name: str,
        energyplus_install_path: Optional[str] = None,
        simulation_dir: Optional[Path] = None
    ):
        """
        Initialize EnergyPlus simulation manager.
        
        Parameters
        ----------
        project_name : str
            Name of the simulation project
        energyplus_install_path : Optional[str]
            Path to EnergyPlus installation directory
        simulation_dir : Optional[Path]
            Custom simulation directory (defaults to ./eplus_sim)
        """
        self.project_name = project_name
        self.simulation_dir = simulation_dir or EPLUS_SIM_DIR
        self.energyplus_install_path = energyplus_install_path or self._find_energyplus()
        self.results = {}
        
        logger.info(f"Initialized EnergyPlus simulation: {project_name}")
    
    def _find_energyplus(self) -> Optional[str]:
        """
        Attempt to automatically find EnergyPlus installation.
        
        Returns
        -------
        Optional[str]
            Path to EnergyPlus installation or None if not found
        """
        # Common EnergyPlus installation paths
        common_paths = [
            "C:/EnergyPlusV24-1-0/",
            "C:/EnergyPlusV23-2-0/",
            "C:/EnergyPlusV22-2-0/",
            "/usr/local/EnergyPlus-24-1-0/",
            "/usr/local/EnergyPlus-23-2-0/",
        ]
        
        for path in common_paths:
            if Path(path).exists():
                logger.info(f"Found EnergyPlus installation at: {path}")
                return path
        
        logger.warning("EnergyPlus installation not found automatically")
        return None
    
    def prepare_weather_file(
        self,
        sensor_id: str,
        start_date: datetime,
        end_date: datetime,
        latitude: float,
        longitude: float
    ) -> Path:
        """
        Prepare weather file for simulation.
        
        Parameters
        ----------
        sensor_id : str
            Sensor identifier for weather data
        start_date : datetime
            Simulation start date
        end_date : datetime
            Simulation end date
        latitude : float
            Location latitude
        longitude : float
            Location longitude
            
        Returns
        -------
        Path
            Path to the generated EPW file
        """
        from ece.pipeline_weather import generate_epw_for_location
        
        logger.info(f"Preparing weather file for sensor {sensor_id}")
        
        epw_path = generate_epw_for_location(
            sensor_id=sensor_id,
            latitude=latitude,
            longitude=longitude,
            start=start_date,
            end=end_date,
            output_dir=WEATHER_DIR
        )
        
        logger.info(f"Weather file prepared: {epw_path}")
        return epw_path
    
    def load_building_model(self, ifc_path: Path) -> Optional[Project]:
        """
        Load and prepare building model from IFC file.
        
        Parameters
        ----------
        ifc_path : Path
            Path to IFC building model file
            
        Returns
        -------
        Optional[Project]
            bim2sim project object or None if loading failed
        """
        if not BIM2SIM_AVAILABLE:
            logger.error("bim2sim not available. Cannot load building model.")
            return None
        
        if not ifc_path.exists():
            logger.error(f"IFC file not found: {ifc_path}")
            return None
        
        logger.info(f"Loading building model from: {ifc_path}")
        
        try:
            # Create temporary project directory
            project_path = Path(tempfile.mkdtemp(prefix=f'eplus_sim_{self.project_name}_'))
            
            # Set up IFC paths
            ifc_paths = {IFCDomain.arch: ifc_path}
            
            # Create bim2sim project
            project = Project.create(project_path, ifc_paths, 'energyplus')
            
            logger.info(f"Building model loaded successfully")
            return project
            
        except Exception as e:
            logger.error(f"Failed to load building model: {e}")
            return None
    
    def configure_simulation(
        self,
        project: Project,
        weather_file: Path,
        run_period_start: Optional[str] = None,
        run_period_end: Optional[str] = None,
        timestep: int = 4
    ) -> Project:
        """
        Configure simulation parameters.
        
        Parameters
        ----------
        project : Project
            bim2sim project object
        weather_file : Path
            Path to EPW weather file
        run_period_start : Optional[str]
            Simulation start date (MM/DD format)
        run_period_end : Optional[str]
            Simulation end date (MM/DD format)
        timestep : int
            Number of timesteps per hour (default: 4 = 15 minutes)
            
        Returns
        -------
        Project
            Configured project object
        """
        logger.info("Configuring simulation parameters")
        
        # Set weather file
        project.sim_settings.weather_file_path = weather_file
        
        # Set EnergyPlus installation path
        if self.energyplus_install_path:
            project.sim_settings.ep_install_path = self.energyplus_install_path
        
        # Configure simulation period
        if run_period_start:
            project.sim_settings.run_period_start = run_period_start
        if run_period_end:
            project.sim_settings.run_period_end = run_period_end
        
        # Set timestep
        project.sim_settings.timestep = timestep
        
        # Enable full simulation
        project.sim_settings.run_full_simulation = True
        
        logger.info("Simulation configuration complete")
        return project
    
    def run_simulation(self, project: Project) -> Dict[str, Any]:
        """
        Execute EnergyPlus simulation.
        
        Parameters
        ----------
        project : Project
            Configured bim2sim project
            
        Returns
        -------
        Dict[str, Any]
            Simulation results and metadata
        """
        logger.info(f"Starting EnergyPlus simulation: {self.project_name}")
        
        try:
            # Run the simulation
            start_time = datetime.now()
            
            # Use ConsoleDecisionHandler for automated decision making
            run_project(project, ConsoleDecisionHandler())
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # Collect results
            results = {
                'project_name': self.project_name,
                'start_time': start_time,
                'end_time': end_time,
                'duration_seconds': duration,
                'status': 'completed',
                'project_path': str(project.paths.base_path),
                'results_path': str(project.paths.results)
            }
            
            logger.info(f"Simulation completed in {duration:.1f} seconds")
            return results
            
        except Exception as e:
            logger.error(f"Simulation failed: {e}")
            return {
                'project_name': self.project_name,
                'status': 'failed',
                'error': str(e)
            }
    
    def process_results(self, simulation_results: Dict[str, Any]) -> Optional[pd.DataFrame]:
        """
        Process and extract simulation results.
        
        Parameters
        ----------
        simulation_results : Dict[str, Any]
            Results dictionary from run_simulation
            
        Returns
        -------
        Optional[pd.DataFrame]
            Processed simulation results or None if processing failed
        """
        if simulation_results.get('status') != 'completed':
            logger.error("Cannot process results from failed simulation")
            return None
        
        logger.info("Processing simulation results")
        
        try:
            results_path = Path(simulation_results['results_path'])
            
            # Look for CSV output files
            csv_files = list(results_path.glob("*.csv"))
            
            if not csv_files:
                logger.warning("No CSV output files found")
                return None
            
            # Process the main results file
            main_csv = csv_files[0]  # Take the first CSV file
            df = pd.read_csv(main_csv)
            
            # Add metadata
            df['simulation_name'] = self.project_name
            df['simulation_time'] = simulation_results['start_time']
            
            logger.info(f"Processed {len(df)} result records")
            return df
            
        except Exception as e:
            logger.error(f"Failed to process results: {e}")
            return None


def run_building_simulation(
    ifc_path: Path,
    sensor_id: str,
    latitude: float,
    longitude: float,
    start_date: datetime,
    end_date: datetime,
    project_name: Optional[str] = None,
    energyplus_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Complete building simulation workflow.
    
    Parameters
    ----------
    ifc_path : Path
        Path to IFC building model file
    sensor_id : str
        Sensor identifier for weather data
    latitude : float
        Location latitude
    longitude : float
        Location longitude
    start_date : datetime
        Simulation start date
    end_date : datetime
        Simulation end date
    project_name : Optional[str]
        Custom project name
    energyplus_path : Optional[str]
        Custom EnergyPlus installation path
        
    Returns
    -------
    Dict[str, Any]
        Complete simulation results and metadata
    """
    if not project_name:
        project_name = f"sim_{sensor_id}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
    
    logger.info(f"Starting complete building simulation: {project_name}")
    
    # Initialize simulation
    sim = EnergyPlusSimulation(project_name, energyplus_path)
    
    try:
        # Step 1: Prepare weather file
        weather_file = sim.prepare_weather_file(
            sensor_id, start_date, end_date, latitude, longitude
        )
        
        # Step 2: Load building model
        project = sim.load_building_model(ifc_path)
        if not project:
            return {'status': 'failed', 'error': 'Failed to load building model'}
        
        # Step 3: Configure simulation
        project = sim.configure_simulation(project, weather_file)
        
        # Step 4: Run simulation
        sim_results = sim.run_simulation(project)
        
        # Step 5: Process results
        if sim_results.get('status') == 'completed':
            results_df = sim.process_results(sim_results)
            sim_results['results_dataframe'] = results_df
        
        return sim_results
        
    except Exception as e:
        logger.error(f"Building simulation failed: {e}")
        return {'status': 'failed', 'error': str(e)}


# Example usage and testing
if __name__ == '__main__':
    # Test the pipeline with dummy data
    print("Testing EnergyPlus pipeline...")
    
    # This would be called with actual parameters
    # result = run_building_simulation(
    #     ifc_path=Path("./eplus_sim/models/example.ifc"),
    #     sensor_id="test_sensor",
    #     latitude=38.0,
    #     longitude=23.7,
    #     start_date=datetime(2025, 6, 15),
    #     end_date=datetime(2025, 7, 15)
    # )
    # print(f"Simulation result: {result}")
