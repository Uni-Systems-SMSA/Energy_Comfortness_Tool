"""
Prediction endpoint and Celery task for async ML predictions.

This module provides the POST /predict endpoint that accepts prediction requests,
queues them to Celery, and returns a job_id for async processing.
"""

import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError

from backend.models import PredictRequest, JobSubmissionResponse, JobStatus
from backend.queue import celery_app
from backend.config import settings
from backend.db.jobs import create_job, update_job_status, store_result

logger = logging.getLogger(__name__)

# Create router for prediction endpoints
router = APIRouter()

# Configuration
PREDICT_TASK_PRIORITY = 5  # Medium priority
PREDICT_TASK_TIMEOUT = 3600  # 1 hour in seconds
PREDICT_TASK_MAX_RETRIES = 3


@router.post(
    "/predict",
    response_model=JobSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["predict"],
    summary="Submit a prediction job",
    description="Submit a prediction request for async processing"
)
async def submit_prediction(request: PredictRequest) -> JobSubmissionResponse:
    """
    Submit a prediction job.

    This endpoint accepts a prediction request, validates the input,
    creates a job record in the database, and queues it to Celery.

    Args:
        request: PredictRequest with building_id, space_id, date_range, and model_type

    Returns:
        JobSubmissionResponse with job_id, status, and estimated_wait_time_seconds

    Raises:
        HTTPException: If validation fails or job creation fails
    """
    try:
        logger.info(f"Received prediction request for building {request.building_id}, space {request.space_id}")

        # Validate input
        if not request.building_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="building_id is required"
            )

        if not request.space_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="space_id is required"
            )

        if not request.date_range or not isinstance(request.date_range, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="date_range is required and must be a dictionary"
            )

        if "start" not in request.date_range or "end" not in request.date_range:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="date_range must contain 'start' and 'end' keys"
            )

        if not request.model_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="model_type is required"
            )

        # Prepare input parameters for database
        input_params = {
            "building_id": request.building_id,
            "space_id": request.space_id,
            "date_range": request.date_range,
            "model_type": request.model_type,
        }

        # Create job record in database
        try:
            job_id = create_job(
                job_type="ml_predict",
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
            task = predict_task.apply_async(
                args=[job_id, request.building_id, request.space_id, request.date_range, request.model_type],
                task_id=job_id,
                priority=PREDICT_TASK_PRIORITY,
                timeout=PREDICT_TASK_TIMEOUT,
            )
            logger.info(f"Queued prediction task {job_id} to Celery")
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
                detail="Failed to queue prediction task"
            )

        # Calculate estimated wait time (mock calculation)
        estimated_wait_time_seconds = 30  # TODO: Implement queue depth calculation

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
        logger.error(f"Unexpected error in submit_prediction: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@celery_app.task(
    name="predict_task",
    bind=True,
    max_retries=PREDICT_TASK_MAX_RETRIES,
    time_limit=PREDICT_TASK_TIMEOUT,
    acks_late=True,
)
def predict_task(
    self,
    job_id: str,
    building_id: str,
    space_id: str,
    date_range: dict,
    model_type: str
) -> dict:
    """
    Celery task for async ML prediction.

    This task handles the actual prediction logic:
    1. Update job status to "running"
    2. Call ECE pipeline to get predictions
    3. Store results in database
    4. Update job status to "completed"
    5. Handle errors and retry

    Args:
        self: Celery task context (for retry)
        job_id: Unique job identifier
        building_id: Building identifier for prediction
        space_id: Space identifier for prediction
        date_range: Date range dictionary with 'start' and 'end' keys
        model_type: Type of model to use for prediction

    Returns:
        Dictionary with prediction results

    Raises:
        Exception: If prediction fails (will trigger retry)
    """
    try:
        logger.info(f"Starting prediction task {job_id} for building {building_id}, space {space_id}, model {model_type}")

        # Update job status to "running"
        update_job_status(
            job_id=job_id,
            status="running",
            progress=10
        )

        # TODO: Call ECE pipeline to get predictions
        # When ece.pipeline_ml module is available, uncomment:
        # from ece.pipeline_ml import predict
        # predictions = predict(
        #     building_id=building_id,
        #     space_id=space_id,
        #     date_range=date_range,
        #     model_type=model_type
        # )

        # For now, mock prediction results
        logger.info(f"Calling ECE pipeline for predictions (currently mocked) for {building_id}/{space_id}")
        predictions = {
            "building_id": building_id,
            "space_id": space_id,
            "date_range": date_range,
            "model_type": model_type,
            "predictions": {"status": "mocked"},  # Mock: placeholder predictions
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
            result_data=predictions
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

        logger.info(f"Completed prediction task {job_id}")
        return {
            "job_id": job_id,
            "status": "completed",
            "results": predictions
        }

    except Exception as e:
        logger.error(f"Error in predict_task {job_id}: {e}", exc_info=True)

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
