"""
Job lifecycle management endpoints.

This module provides endpoints for checking job status, canceling jobs,
and retrieving job results.
"""

import logging
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, status

from backend.models import JobStatusResponse, JobResultsResponse, JobStatus
from backend.queue import celery_app
from backend.db.jobs import get_job, update_job_status

logger = logging.getLogger(__name__)

# Create router for job endpoints
router = APIRouter()


@router.get(
    "/status/{job_id}",
    response_model=JobStatusResponse,
    status_code=status.HTTP_200_OK,
    tags=["jobs"],
    summary="Get job status",
    description="Retrieve the current status and progress of a job"
)
async def get_status(job_id: str) -> JobStatusResponse:
    """
    Get the status of a job.

    This endpoint retrieves the current status, progress, and timestamps
    of a job. If the job is completed, includes a URL to retrieve results.

    Args:
        job_id: Unique job identifier

    Returns:
        JobStatusResponse with job status and progress information

    Raises:
        HTTPException: If job not found (404)
    """
    try:
        logger.info(f"Fetching status for job {job_id}")

        # Fetch job from database
        job = get_job(job_id)

        if not job:
            logger.warning(f"Job {job_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found"
            )

        # Convert job status string to JobStatus enum
        job_status = JobStatus(job.status)

        # Build response
        response_data: Dict[str, Any] = {
            "job_id": job.id,
            "status": job_status,
            "progress": job.progress,
            "error_message": job.error_message,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
        }

        # Add result_url if job is completed
        if job_status == JobStatus.COMPLETED:
            response_data["result_url"] = f"/api/v1/results/{job_id}"

        logger.info(f"Successfully retrieved status for job {job_id}: {job_status}")
        return JobStatusResponse(**response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error retrieving status for job {job_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.delete(
    "/cancel/{job_id}",
    status_code=status.HTTP_200_OK,
    tags=["jobs"],
    summary="Cancel a job",
    description="Cancel a queued or running job"
)
async def cancel_job(job_id: str) -> Dict[str, str]:
    """
    Cancel a job.

    This endpoint cancels a job if it is currently queued or running.
    It revokes the Celery task and updates the job status to "cancelled".

    Args:
        job_id: Unique job identifier

    Returns:
        Message confirming job cancellation

    Raises:
        HTTPException: If job not found (404) or operation invalid (400)
    """
    try:
        logger.info(f"Attempting to cancel job {job_id}")

        # Fetch job from database
        job = get_job(job_id)

        if not job:
            logger.warning(f"Job {job_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found"
            )

        # Check if job can be cancelled (only queued or running)
        current_status = job.status
        if current_status not in ["queued", "running"]:
            logger.warning(
                f"Cannot cancel job {job_id}: current status is {current_status}, "
                f"only queued/running jobs can be cancelled"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot cancel job with status '{current_status}'. "
                        f"Only queued or running jobs can be cancelled."
            )

        # Revoke the Celery task
        try:
            celery_app.control.revoke(job_id, terminate=True)
            logger.info(f"Revoked Celery task for job {job_id}")
        except Exception as e:
            logger.error(f"Failed to revoke Celery task for job {job_id}: {e}")
            # Continue anyway - still update database status

        # Update job status to "cancelled"
        success = update_job_status(
            job_id=job_id,
            status="cancelled"
        )

        if not success:
            logger.error(f"Failed to update job {job_id} status to cancelled")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update job status"
            )

        logger.info(f"Successfully cancelled job {job_id}")
        return {"message": f"Job {job_id} cancelled"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error cancelling job {job_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.get(
    "/results/{job_id}",
    response_model=JobResultsResponse,
    status_code=status.HTTP_200_OK,
    tags=["jobs"],
    summary="Get job results",
    description="Retrieve the results of a completed job"
)
async def get_results(job_id: str) -> JobResultsResponse:
    """
    Get the results of a completed job.

    This endpoint retrieves the results of a job that has completed.
    The job must have status "completed" to retrieve results.

    Args:
        job_id: Unique job identifier

    Returns:
        JobResultsResponse with job results data

    Raises:
        HTTPException: If job not found (404) or job not completed (400)
    """
    try:
        logger.info(f"Fetching results for job {job_id}")

        # Fetch job from database
        job = get_job(job_id)

        if not job:
            logger.warning(f"Job {job_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found"
            )

        # Check if job is completed
        if job.status != "completed":
            logger.warning(
                f"Cannot retrieve results for job {job_id}: status is {job.status}, "
                f"job must be completed"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Job is not completed. Current status: {job.status}"
            )

        # Convert job status string to JobStatus enum
        job_status = JobStatus(job.status)

        # Build response
        response = JobResultsResponse(
            job_id=job.id,
            status=job_status,
            data=job.result_data,
            created_at=job.created_at,
            completed_at=job.completed_at
        )

        logger.info(f"Successfully retrieved results for job {job_id}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error retrieving results for job {job_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )
