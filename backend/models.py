"""
Pydantic models for request/response validation.
"""
from enum import Enum
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime


class JobStatus(str, Enum):
    """Job status enumeration."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PredictRequest(BaseModel):
    """Request model for prediction jobs."""
    model_config = ConfigDict(protected_namespaces=())

    building_id: str = Field(..., description="Identifier for the building")
    space_id: str = Field(..., description="Identifier for the space")
    date_range: Dict[str, str] = Field(..., description="Date range with 'start' and 'end' keys (ISO format)")
    model_type: str = Field(..., description="Type of model to use for prediction")


class SimulateRequest(BaseModel):
    """Request model for simulation jobs."""
    model_config = ConfigDict(protected_namespaces=())

    building_id: str = Field(..., description="Identifier for the building")
    ifc_file_id: str = Field(..., description="Identifier for the IFC file")
    weather_data_id: str = Field(..., description="Identifier for the weather data")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Simulation parameters")


class JobSubmissionResponse(BaseModel):
    """Response model for job submission."""
    job_id: str = Field(..., description="Unique job identifier")
    status: JobStatus = Field(..., description="Initial job status")
    estimated_wait_time_seconds: Optional[int] = Field(None, description="Estimated wait time in seconds for job completion")


class JobStatusResponse(BaseModel):
    """Response model for job status query."""
    job_id: str = Field(..., description="Unique job identifier")
    status: JobStatus = Field(..., description="Current job status")
    progress: int = Field(default=0, description="Progress percentage (0-100)")
    error_message: Optional[str] = Field(None, description="Error message if job failed")
    created_at: datetime = Field(..., description="Job creation timestamp")
    started_at: Optional[datetime] = Field(None, description="Job start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Job completion timestamp")
    result_url: Optional[str] = Field(None, description="URL to retrieve results if job completed")


class JobResultsResponse(BaseModel):
    """Response model for job results."""
    job_id: str = Field(..., description="Unique job identifier")
    status: JobStatus = Field(..., description="Final job status")
    data: Optional[Dict[str, Any]] = Field(None, description="Job results data")
    created_at: datetime = Field(..., description="Job creation timestamp")
    completed_at: Optional[datetime] = Field(None, description="Job completion timestamp")
