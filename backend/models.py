"""
Pydantic models for request/response validation.
"""
from enum import Enum
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field
from datetime import datetime


class JobStatus(str, Enum):
    """Job status enumeration."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PredictRequest(BaseModel):
    """Request model for prediction jobs."""
    space_id: str = Field(..., description="Identifier for the space")
    features: Dict[str, Any] = Field(..., description="Feature dictionary for prediction")
    model_version: Optional[str] = Field(None, description="Model version to use")


class SimulateRequest(BaseModel):
    """Request model for simulation jobs."""
    space_id: str = Field(..., description="Identifier for the space")
    parameters: Dict[str, Any] = Field(..., description="Simulation parameters")
    duration: int = Field(..., description="Simulation duration in minutes")
    model_version: Optional[str] = Field(None, description="Model version to use")


class JobSubmissionResponse(BaseModel):
    """Response model for job submission."""
    job_id: str = Field(..., description="Unique job identifier")
    status: JobStatus = Field(..., description="Initial job status")
    message: str = Field(..., description="Human-readable message")


class JobStatusResponse(BaseModel):
    """Response model for job status query."""
    job_id: str = Field(..., description="Unique job identifier")
    status: JobStatus = Field(..., description="Current job status")
    progress: int = Field(default=0, description="Progress percentage (0-100)")
    created_at: datetime = Field(..., description="Job creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class JobResultsResponse(BaseModel):
    """Response model for job results."""
    job_id: str = Field(..., description="Unique job identifier")
    status: JobStatus = Field(..., description="Final job status")
    results: Optional[Dict[str, Any]] = Field(None, description="Job results")
    error_message: Optional[str] = Field(None, description="Error message if job failed")
    created_at: datetime = Field(..., description="Job creation timestamp")
    completed_at: Optional[datetime] = Field(None, description="Job completion timestamp")
