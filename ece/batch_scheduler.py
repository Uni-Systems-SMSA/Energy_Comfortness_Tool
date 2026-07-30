# -*- coding: utf-8 -*-
"""
ece.batch_scheduler
===================

Automated, database-driven multi-building IFC job scheduler and pipeline.
Scans etc/ifc/ subfolders, tracks execution statuses in PostgreSQL (ifc_simulation_jobs),
validates physical eplusout.csv export, and executes headless EnergyPlus runs.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "dashboard"))

from db.session import SessionLocal
from db.models import IFCSimulationJob, Space, Measurement
from ece.utils.logging import init_logger
from ece.pipeline_weather import generate_epw_for_location

logger = init_logger(__name__)

BASE_DIR = Path(__file__).parent.parent
ETC_IFC_DIR = BASE_DIR / "etc" / "ifc"
LOGS_SIM_DIR = BASE_DIR / "logs" / "simulations"


def _extract_gps_from_ifc(ifc_path: Path) -> tuple:
    """Extract decimal (latitude, longitude) from IfcSite in the given IFC file, defaulting to (40.6401, 22.9444) if missing."""
    try:
        import ifcopenshell
        ifc = ifcopenshell.open(str(ifc_path))
        sites = ifc.by_type('IfcSite')
        if sites:
            site = sites[0]
            lat_dms = getattr(site, 'RefLatitude', None)
            lon_dms = getattr(site, 'RefLongitude', None)

            def dms_to_decimal(dms):
                if not dms or len(dms) < 3:
                    return None
                deg, m, s = dms[0], dms[1], dms[2]
                micro = dms[3] if len(dms) > 3 else 0
                sign = -1 if deg < 0 else 1
                abs_deg = abs(deg)
                val = sign * (abs_deg + m / 60.0 + (s + micro / 1e6) / 3600.0)
                return val

            lat_dec = dms_to_decimal(lat_dms)
            lon_dec = dms_to_decimal(lon_dms)
            if lat_dec is not None and lon_dec is not None:
                return lat_dec, lon_dec
    except Exception as e:
        logger.warning(f"Could not extract GPS coordinates from IFC file {ifc_path}: {e}")
    return 40.6401, 22.9444


def discover_and_sync_ifc_jobs(session) -> List[IFCSimulationJob]:
    """
    Scan etc/ifc/*/ for subfolders containing .ifc files and upsert entries into ifc_simulation_jobs.
    """
    ETC_IFC_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_SIM_DIR.mkdir(parents=True, exist_ok=True)

    discovered_jobs: List[IFCSimulationJob] = []

    # Find all direct subdirectories under etc/ifc/
    building_folders = [d for d in ETC_IFC_DIR.iterdir() if d.is_dir()]
    logger.info(f"Discovered {len(building_folders)} potential building folders in {ETC_IFC_DIR}")

    for b_folder in building_folders:
        folder_name = b_folder.name
        ifc_files = list(b_folder.glob("*.ifc"))

        if not ifc_files:
            logger.warning(f"No .ifc file found in {b_folder}, skipping")
            continue

        ifc_path = ifc_files[0]
        config_path = b_folder / "config.json"
        
        # Building name is strictly the folder_name
        building_name = folder_name

        rel_ifc_path = str(ifc_path.relative_to(BASE_DIR))
        rel_config_path = str(config_path.relative_to(BASE_DIR)) if config_path.exists() else None

        # Check existing job record
        job = session.query(IFCSimulationJob).filter(IFCSimulationJob.folder_name == folder_name).first()

        if not job:
            logger.info(f"Registering new IFC job for building: '{building_name}' ({folder_name})")
            job = IFCSimulationJob(
                building_name=building_name,
                folder_name=folder_name,
                ifc_file_path=rel_ifc_path,
                config_file_path=rel_config_path,
                status="PENDING"
            )
            session.add(job)
            session.flush()
        else:
            # Update paths if changed
            job.building_name = building_name
            job.ifc_file_path = rel_ifc_path
            job.config_file_path = rel_config_path

        discovered_jobs.append(job)

    session.commit()
    return discovered_jobs


def validate_config(b_folder: Path, ifc_path: Path) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    """
    Validate config.json or generate a template file if missing/incomplete.
    Returns (is_valid, config_dict, error_reason).
    """
    config_path = b_folder / "config.json"
    template_path = b_folder / "config.json.template"

    default_config = {
        "building_name": b_folder.name.replace("_", " ").title(),
        "construction_year": 2006,
        "building_index": 1,
        "hvac_template": 1,
        "weather_file": "GRC_Thessaloniki.epw",
        "heating_setpoint_c": 21.0,
        "cooling_setpoint_c": 25.0
    }

    if not config_path.exists():
        # Write template for administrator
        template_config = {
            "building_name": default_config["building_name"],
            "construction_year": "<REQUIRED_INT_YEAR_e.g._2006>",
            "building_index": "<OPTIONAL_INT_INDEX_default_1>",
            "hvac_template": "<OPTIONAL_INT_TEMPLATE_default_1>",
            "weather_file": default_config["weather_file"],
            "heating_setpoint_c": 21.0,
            "cooling_setpoint_c": 25.0
        }
        with open(template_path, "w", encoding="utf-8") as f:
            json.dump(template_config, f, indent=2)
        logger.warning(f"No config.json found in {b_folder}. Created {template_path.name}")
        
        # Check if fallback config is sufficient or if missing required fields
        return True, default_config, None

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        # Check for unconfigured template tags
        for k, v in cfg.items():
            if isinstance(v, str) and "<REQUIRED" in v:
                return False, cfg, f"Unconfigured template tag in config.json: {k}={v}"

        # Merge defaults for any missing keys
        merged = {**default_config, **cfg}
        return True, merged, None

    except Exception as e:
        return False, {}, f"Invalid JSON format in {config_path.name}: {str(e)}"


def run_batch_scheduler(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Execute all pending, failed, or outdated IFC simulation jobs headlessly.
    """
    start_time = time.time()
    LOGS_SIM_DIR.mkdir(parents=True, exist_ok=True)
    summary = {"total": 0, "ran": 0, "skipped": 0, "failed": 0, "details": []}

    # Default to 2026 through current date + 14 days
    now = datetime.now()
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d")

    if not start_date:
        start_date = datetime(2026, 1, 1)
    if not end_date:
        end_date = now + timedelta(days=14)

    with SessionLocal() as session:
        jobs = discover_and_sync_ifc_jobs(session)
        summary["total"] = len(jobs)
        today = date.today()

        for job in jobs:
            b_folder = BASE_DIR / "etc" / "ifc" / job.folder_name
            ifc_path = BASE_DIR / job.ifc_file_path

            if not ifc_path.exists():
                job.status = "FAILED"
                job.error_message = f"IFC file does not exist: {ifc_path}"
                session.commit()
                summary["failed"] += 1
                summary["details"].append({"building": job.building_name, "status": "FAILED", "reason": "Missing IFC file"})
                continue

            # Check Smart Skip (Already attempted today)
            if job.last_run_timestamp and job.last_run_timestamp.date() == today and job.status in ["OK", "FAILED"]:
                logger.info(f"[SKIP] Job for '{job.building_name}' already attempted today ({today}, status={job.status})")
                summary["skipped"] += 1
                summary["details"].append({"building": job.building_name, "status": "SKIPPED", "reason": f"Already {job.status} today"})
                continue

            # Validate config
            is_valid_cfg, cfg, cfg_err = validate_config(b_folder, ifc_path)
            if not is_valid_cfg:
                job.status = "FAILED"
                job.error_message = f"Configuration error: {cfg_err}"
                session.commit()
                logger.error(f"[FAILED] Job for '{job.building_name}' failed config validation: {cfg_err}")
                summary["failed"] += 1
                summary["details"].append({"building": job.building_name, "status": "FAILED", "reason": cfg_err})
                continue

            # Setup isolated log file in etc/ifc/{building}/logs/
            b_logs_dir = b_folder / "logs"
            b_logs_dir.mkdir(parents=True, exist_ok=True)
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_filename = f"{job.folder_name}_{timestamp_str}.log"
            log_file_path = b_logs_dir / log_filename
            job.log_file_path = str(log_file_path.relative_to(BASE_DIR))
            job.status = "RUNNING"
            session.commit()

            logger.info(f"[RUNNING] Starting simulation for '{job.building_name}' ({start_date.date()} to {end_date.date()})...")

            job_start_time = time.time()
            try:
                with open(log_file_path, "w", encoding="utf-8") as log_f:
                    log_f.write(f"=== Simulation Job Log for {job.building_name} ({job.folder_name}) ===\n")
                    log_f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                    log_f.write(f"Requested Period: {start_date.date()} to {end_date.date()}\n")
                    log_f.write(f"IFC File: {ifc_path}\n")
                    log_f.write(f"Config: {json.dumps(cfg, indent=2)}\n\n")

                    # Import storage module completely decoupled from Streamlit
                    from ece.pipeline_eplus_wrapper import run_eplus_simulation_async
                    from ece.energy_storage import _parse_energyplus_outputs, _store_energy_simulation_results

                    # Use building name as the target identifier for weather generation & project naming
                    target_sensor = job.building_name

                    # Extract location coordinates: config.json > IFC file extraction > default fallback
                    lat = cfg.get("latitude")
                    lon = cfg.get("longitude")
                    if lat is None or lon is None:
                        ifc_lat, ifc_lon = _extract_gps_from_ifc(ifc_path)
                        lat = lat if lat is not None else ifc_lat
                        lon = lon if lon is not None else ifc_lon

                    logger.info(f"Using location coordinates for '{job.building_name}': lat={lat:.4f}, lon={lon:.4f}")

                    # Ensure target_sensor exists in Space table to satisfy weather foreign key constraint
                    from db.models import Space
                    space_record = session.query(Space).filter(Space.space_id == target_sensor).first()
                    if not space_record:
                        space_record = Space(
                            space_id=target_sensor,
                            building_id=job.building_name,
                            latitude=lat,
                            longitude=lon
                        )
                        session.add(space_record)
                        session.commit()

                    # Generate weather EPW for requested period and location
                    epw_path = generate_epw_for_location(
                        space_id=target_sensor,
                        latitude=lat,
                        longitude=lon,
                        start=start_date,
                        end=end_date,
                        full_year=True
                    )

                    # Execute simulation
                    sim_result = run_eplus_simulation_async(
                        ifc_file_path=ifc_path,
                        weather_file_path=Path(epw_path),
                        sensor_id=target_sensor
                    )

                    # --- SUCCESS VERIFICATION GATE: Verify eplusout.csv existence ---
                    export_dir = None
                    if "eplus_results_path" in sim_result:
                        export_dir = Path(sim_result["eplus_results_path"])
                    elif "project_path" in sim_result:
                        p_dir = Path(sim_result["project_path"]) / "export" / "EnergyPlus" / "SimResults"
                        if p_dir.exists():
                            res_subdirs = [d for d in p_dir.iterdir() if d.is_dir()]
                            if res_subdirs:
                                export_dir = res_subdirs[0]

                    if not export_dir or not export_dir.exists():
                        raise RuntimeError(f"EnergyPlus export directory not found: {export_dir}")

                    eplusout_csv = export_dir / "eplusout.csv"
                    if not eplusout_csv.exists() or eplusout_csv.stat().st_size == 0:
                        raise RuntimeError(f"EnergyPlus failed to export valid eplusout.csv at: {eplusout_csv}")

                    log_f.write(f"SUCCESS Verified physical eplusout.csv export: {eplusout_csv} ({eplusout_csv.stat().st_size} bytes)\n")

                    # Store results in database - strictly truncated to end_date
                    storage_ok = _store_energy_simulation_results(
                        simulation_results=sim_result,
                        space_id=target_sensor,
                        building_id=job.building_name,
                        ifc_file_path=str(ifc_path),
                        epw_file_path=str(epw_path),
                        end_date=end_date
                    )

                    if not storage_ok:
                        raise RuntimeError("Failed to store energy simulation results in database")

                    job_duration = time.time() - job_start_time
                    job.status = "OK"
                    job.last_run_timestamp = datetime.now()
                    job.last_run_duration_sec = job_duration
                    job.error_message = None
                    session.commit()

                    log_f.write(f"\nSUCCESS Job completed successfully in {job_duration:.1f} seconds.\n")
                    logger.info(f"[OK] Job for '{job.building_name}' completed successfully in {job_duration:.1f}s")
                    summary["ran"] += 1
                    summary["details"].append({"building": job.building_name, "status": "OK", "duration_sec": job_duration})

            except Exception as e:
                job_duration = time.time() - job_start_time
                error_trace = traceback.format_exc()
                job.status = "FAILED"
                job.last_run_duration_sec = job_duration
                job.error_message = error_trace
                session.commit()

                # Write error to log file
                try:
                    with open(log_file_path, "a", encoding="utf-8") as log_f:
                        log_f.write(f"\n❌ SIMULATION FAILED:\n{error_trace}\n")
                except Exception:
                    pass

                logger.error(f"[FAILED] Job for '{job.building_name}' failed after {job_duration:.1f}s: {e}")
                summary["failed"] += 1
                summary["details"].append({"building": job.building_name, "status": "FAILED", "error": str(e)})

    summary["total_duration_sec"] = time.time() - start_time
    logger.info(f"Batch scheduler execution complete: {summary}")
    return summary


if __name__ == "__main__":
    print("=== Running EnergyPlus Multi-IFC Batch Scheduler ===")
    res = run_batch_scheduler()
    print("Results Summary:", json.dumps(res, indent=2))
