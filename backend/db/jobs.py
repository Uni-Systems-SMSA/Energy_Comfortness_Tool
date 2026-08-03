"""
Database operations for job tracking and management.

This module provides CRUD operations for async jobs, handling creation,
status updates, result storage, and job retrieval.
"""

import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy import create_engine, Column, String, Integer, DateTime, JSON, Text, Index
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from db.session import SessionLocal, engine

logger = logging.getLogger(__name__)

# Use the existing Base from db.models
from db.models import Base


class Job(Base):
    """ORM model for tracking async job execution."""

    __tablename__ = "jobs"

    # Primary key: job_id (String(50))
    id = Column(String(50), primary_key=True, nullable=False)

    # User tracking (nullable)
    user_id = Column(String(50), nullable=True)

    # Job status (default: "queued")
    # Valid values: queued, running, completed, failed, cancelled
    status = Column(String(20), nullable=False, default="queued")

    # Job type (required)
    # Valid values: "ml_predict", "eplus_simulate", "weather_process"
    job_type = Column(String(50), nullable=False)

    # Input parameters (JSON)
    input_params = Column(JSON, nullable=False)

    # Results when completed (nullable JSON)
    result_data = Column(JSON, nullable=True)

    # Progress tracking (0-100, default 0)
    progress = Column(Integer, nullable=False, default=0)

    # Error message (nullable Text)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        # Indexes for common queries
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_user_id", "user_id"),
        Index("ix_jobs_created_at", "created_at"),
    )


def create_job(
    job_type: str,
    input_params: Dict[str, Any],
    user_id: Optional[str] = None,
    session: Optional[Session] = None
) -> str:
    """
    Create a new job record in the database.

    Args:
        job_type: Type of job (e.g., "ml_predict", "eplus_simulate")
        input_params: Input parameters as dictionary
        user_id: Optional user identifier
        session: Optional database session (creates new if not provided)

    Returns:
        job_id: Unique job identifier

    Raises:
        Exception: If job creation fails
    """
    try:
        if session is None:
            session = SessionLocal()
            should_close = True
        else:
            should_close = False

        # Generate unique job_id
        job_id = str(uuid.uuid4())[:50]

        # Create job record
        job = Job(
            id=job_id,
            user_id=user_id,
            status="queued",
            job_type=job_type,
            input_params=input_params,
            progress=0,
            created_at=datetime.utcnow(),
        )

        session.add(job)
        session.commit()

        logger.info(f"Created job {job_id} with type {job_type}")
        return job_id

    except Exception as e:
        logger.error(f"Error creating job: {e}")
        session.rollback()
        raise

    finally:
        if should_close:
            session.close()


def get_job(job_id: str, session: Optional[Session] = None) -> Optional[Job]:
    """
    Retrieve a job record by ID.

    Args:
        job_id: Job identifier
        session: Optional database session (creates new if not provided)

    Returns:
        Job record or None if not found
    """
    try:
        if session is None:
            session = SessionLocal()
            should_close = True
        else:
            should_close = False

        job = session.query(Job).filter(Job.id == job_id).first()
        return job

    finally:
        if should_close:
            session.close()


def update_job_status(
    job_id: str,
    status: str,
    progress: Optional[int] = None,
    error_message: Optional[str] = None,
    session: Optional[Session] = None
) -> bool:
    """
    Update job status and optional progress/error.

    Args:
        job_id: Job identifier
        status: New status (queued, running, completed, failed, cancelled)
        progress: Optional progress percentage (0-100)
        error_message: Optional error message
        session: Optional database session (creates new if not provided)

    Returns:
        True if successful, False otherwise
    """
    try:
        if session is None:
            session = SessionLocal()
            should_close = True
        else:
            should_close = False

        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.warning(f"Job {job_id} not found")
            return False

        job.status = status
        if progress is not None:
            job.progress = progress
        if error_message is not None:
            job.error_message = error_message

        if status == "running" and job.started_at is None:
            job.started_at = datetime.utcnow()
        elif status in ("completed", "failed", "cancelled") and job.completed_at is None:
            job.completed_at = datetime.utcnow()

        session.commit()
        logger.info(f"Updated job {job_id} status to {status}")
        return True

    except Exception as e:
        logger.error(f"Error updating job {job_id}: {e}")
        session.rollback()
        return False

    finally:
        if should_close:
            session.close()


def store_result(
    job_id: str,
    result_data: Dict[str, Any],
    session: Optional[Session] = None
) -> bool:
    """
    Store result data for a completed job.

    Args:
        job_id: Job identifier
        result_data: Result data as dictionary
        session: Optional database session (creates new if not provided)

    Returns:
        True if successful, False otherwise
    """
    try:
        if session is None:
            session = SessionLocal()
            should_close = True
        else:
            should_close = False

        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.warning(f"Job {job_id} not found")
            return False

        job.result_data = result_data
        job.status = "completed"
        job.completed_at = datetime.utcnow()
        job.progress = 100

        session.commit()
        logger.info(f"Stored results for job {job_id}")
        return True

    except Exception as e:
        logger.error(f"Error storing result for job {job_id}: {e}")
        session.rollback()
        return False

    finally:
        if should_close:
            session.close()


def get_jobs_by_status(
    status: str,
    limit: int = 100,
    session: Optional[Session] = None
) -> List[Job]:
    """
    Retrieve jobs by status.

    Args:
        status: Job status to filter by
        limit: Maximum number of jobs to return
        session: Optional database session (creates new if not provided)

    Returns:
        List of Job records
    """
    try:
        if session is None:
            session = SessionLocal()
            should_close = True
        else:
            should_close = False

        jobs = session.query(Job).filter(Job.status == status).limit(limit).all()
        return jobs

    finally:
        if should_close:
            session.close()


def get_job_status(job_id: str, session: Optional[Session] = None) -> Optional[str]:
    """
    Get the status of a job.

    Args:
        job_id: Job identifier
        session: Optional database session (creates new if not provided)

    Returns:
        Job status or None if not found
    """
    try:
        if session is None:
            session = SessionLocal()
            should_close = True
        else:
            should_close = False

        job = session.query(Job).filter(Job.id == job_id).first()
        if job:
            return job.status
        return None

    finally:
        if should_close:
            session.close()
