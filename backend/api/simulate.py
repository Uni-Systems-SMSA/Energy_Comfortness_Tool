"""
Simulation endpoint and Celery task for async EnergyPlus simulations.

This module provides the POST /simulate endpoint that accepts simulation requests,
queues them to Celery, and returns a job_id for async processing.
"""

import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError

from backend.models import SimulateRequest, JobSubmissionResponse, JobStatus
from backend.queue import celery_app
from backend.config import settings
from backend.db.jobs import create_job, update_job_status, store_result

logger = logging.getLogger(__name__)

# Create router for simulation endpoints
router = APIRouter()

# Configuration
SIMULATE_TASK_PRIORITY = 3  # Lower priority than predictions
SIMULATE_TASK_TIMEOUT = 7200  # 2 hours in seconds
SIMULATE_TASK_MAX_RETRIES = 3


@router.post(
    "/simulate",
    response_model=JobSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["simulate"],
    summary="Submit a simulation job",
    description="Submit a simulation request for async processing"
)
async def submit_simulation(request: SimulateRequest) -> JobSubmissionResponse:
    """
    Submit a simulation job.

    This endpoint accepts a simulation request, validates the input,
    creates a job record in the database, and queues it to Celery.

    Args:
        request: SimulateRequest with building_id, ifc_file_id, weather_data_id, and parameters

    Returns:
        JobSubmissionResponse with job_id, status, and estimated_wait_time_seconds

    Raises:
        HTTPException: If validation fails or job creation fails
    """
    try:
        logger.info(f"Received simulation request for building {request.building_id}, IFC {request.ifc_file_id}")

        # Validate input
        if not request.building_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="building_id is required"
            )

        if not request.ifc_file_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ifc_file_id is required"
            )

        if not request.weather_data_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="weather_data_id is required"
            )

        # Prepare input parameters for database
        input_params = {
            "building_id": request.building_id,
            "ifc_file_id": request.ifc_file_id,
            "weather_data_id": request.weather_data_id,
            "parameters": request.parameters or {},
        }

        # Create job record in database
        try:
            job_id = create_job(
                job_type="eplus_simulate",
                input_params=input_params,
                user_id=None,  # TODO: Add user tracking when auth is implemented
            )
            logger.info(f"Created job {job_id} in database")
        except Exception as e:
            logger.error(f"Failed to create job in database: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create job record"
            )

        # Queue task to Celery
        try:
            task = simulate_task.apply_async(
                args=[job_id, request.building_id, request.ifc_file_id, request.weather_data_id, request.parameters or {}],
                task_id=job_id,
                priority=SIMULATE_TASK_PRIORITY,
                timeout=SIMULATE_TASK_TIMEOUT,
            )
            logger.info(f"Queued simulation task {job_id} to Celery")
        except Exception as e:
            logger.error(f"Failed to queue task to Celery: {e}")
            # Update job status to failed
            update_job_status(
                job_id=job_id,
                status="failed",
                error_message=f"Failed to queue task: {str(e)}"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to queue simulation task"
            )

        # Calculate estimated wait time (mock calculation)
        estimated_wait_time_seconds = 300  # TODO: Implement queue depth calculation

        return JobSubmissionResponse(
            job_id=job_id,
            status=JobStatus.PENDING,
            estimated_wait_time_seconds=estimated_wait_time_seconds
        )

    except ValidationError as e:
        logger.error(f"Request validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Request validation failed: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in submit_simulation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@celery_app.task(
    name="simulate_task",
    bind=True,
    max_retries=SIMULATE_TASK_MAX_RETRIES,
    time_limit=SIMULATE_TASK_TIMEOUT,
    acks_late=True,
)
def simulate_task(
    self,
    job_id: str,
    building_id: str,
    ifc_file_id: str,
    weather_data_id: str,
    parameters: dict
) -> dict:
    """
    Celery task for async EnergyPlus simulation.

    This task handles the actual simulation logic:
    1. Update job status to "running"
    2. Call EnergyPlus simulation pipeline
    3. Store results in database
    4. Update job status to "completed"
    5. Handle errors and retry

    Args:
        self: Celery task context (for retry)
        job_id: Unique job identifier
        building_id: Building identifier for simulation
        ifc_file_id: IFC file identifier
        weather_data_id: Weather data identifier
        parameters: Simulation parameters dictionary

    Returns:
        Dictionary with simulation results

    Raises:
        Exception: If simulation fails (will trigger retry)
    """
    try:
        logger.info(f"Starting simulation task {job_id} for building {building_id}, IFC {ifc_file_id}")

        # Update job status to "running"
        update_job_status(
            job_id=job_id,
            status="running",
            progress=10
        )

        # TODO: Call EnergyPlus simulation pipeline
        # When ece.pipeline_eplus module is available, uncomment:
        # from ece.pipeline_eplus import simulate
        # simulation_results = simulate(
        #     building_id=building_id,
        #     ifc_file_id=ifc_file_id,
        #     weather_data_id=weather_data_id,
        #     parameters=parameters
        # )

        # For now, mock simulation results
        logger.info(f"Calling EnergyPlus simulation pipeline (currently mocked) for {building_id}/{ifc_file_id}")
        simulation_results = {
            "building_id": building_id,
            "ifc_file_id": ifc_file_id,
            "weather_data_id": weather_data_id,
            "parameters": parameters,
            "simulation_output": {"status": "mocked"},  # Mock: placeholder simulation output
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Update progress
        update_job_status(
            job_id=job_id,
            status="running",
            progress=50
        )

        # Store results in database
        success = store_result(
            job_id=job_id,
            result_data=simulation_results
        )

        if not success:
            logger.error(f"Failed to store results for job {job_id}")
            raise Exception("Failed to store results in database")

        # Update job status to "completed"
        update_job_status(
            job_id=job_id,
            status="completed",
            progress=100
        )

        logger.info(f"Completed simulation task {job_id}")
        return {
            "job_id": job_id,
            "status": "completed",
            "results": simulation_results
        }

    except Exception as e:
        logger.error(f"Error in simulate_task {job_id}: {e}", exc_info=True)

        # Update job status to "failed"
        update_job_status(
            job_id=job_id,
            status="failed",
            error_message=str(e)
        )

        # Retry with exponential backoff
        try:
            raise self.retry(exc=e, countdown=min(2 ** self.request.retries, 300))
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for job {job_id}")
            # Final failure - already marked as failed above
            return {
                "job_id": job_id,
                "status": "failed",
                "error": str(e)
            }
