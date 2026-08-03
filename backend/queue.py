"""
Celery app configuration and async task definitions for ECE.

This module sets up the Celery app instance for distributed task processing
using Redis as the message broker and result backend.
"""

from celery import Celery
from backend.config import settings

# Create Celery app instance
celery_app = Celery(
    "ece_tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# Configure Celery app
celery_app.conf.update(
    # Task serialization
    task_serializer="json",
    accept_content=["json"],

    # Timezone configuration
    timezone="UTC",
    enable_utc=True,

    # Task acknowledgment and prefetching
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # Task timeout configuration (1 hour)
    task_time_limit=3600,
    task_soft_time_limit=3600,

    # Broker connection configuration
    broker_connection_retry_on_startup=True,
)


@celery_app.task
def example_task(x: int, y: int) -> int:
    """
    Example task for testing Celery configuration.

    This task demonstrates a simple async operation that can be queued
    and executed by Celery workers.

    Args:
        x: First integer operand
        y: Second integer operand

    Returns:
        The sum of x and y
    """
    return x + y
