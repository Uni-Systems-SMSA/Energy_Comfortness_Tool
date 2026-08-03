"""
Pytest configuration and fixtures for ECE backend tests.

Note: These tests use mocked database and Celery calls, so no real database
connection is required. The tests verify API behavior without infrastructure.
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup test environment variables BEFORE importing any modules
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost/test_db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["API_HOST"] = "0.0.0.0"
os.environ["API_PORT"] = "8000"
os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
os.environ["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/0"

# Now we can safely import pytest
import pytest
from unittest.mock import MagicMock, patch


# Note: These are unit tests using mocked database and Celery.
# To run integration tests with a real database:
# 1. Start PostgreSQL: docker-compose up -d
# 2. Run: pytest tests/integration/ -v
