"""
FastAPI backend configuration.

Reads from environment variables using python-dotenv.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Settings:
    """Application settings."""

    # Database configuration
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://user:password@localhost:5432/ece_db"
    )

    # Redis configuration
    REDIS_URL: str = os.getenv(
        "REDIS_URL",
        "redis://localhost:6379/0"
    )

    # Job configuration
    JOB_TIMEOUT: int = 3600  # 1 hour in seconds

    # API configuration
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # Celery configuration
    CELERY_BROKER_URL: str = os.getenv(
        "CELERY_BROKER_URL",
        REDIS_URL
    )
    CELERY_RESULT_BACKEND: str = os.getenv(
        "CELERY_RESULT_BACKEND",
        REDIS_URL
    )


settings = Settings()
