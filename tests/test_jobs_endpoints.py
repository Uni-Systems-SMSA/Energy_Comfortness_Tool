"""
Tests for job lifecycle management endpoints (Task 6).

This module tests the GET /status/{job_id}, DELETE /cancel/{job_id},
and GET /results/{job_id} endpoints.
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.models import JobStatus


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_job_queued():
    """Create a mock queued job."""
    job = MagicMock()
    job.id = "test-job-001"
    job.status = "queued"
    job.progress = 0
    job.error_message = None
    job.created_at = datetime(2024, 1, 1, 12, 0, 0)
    job.started_at = None
    job.completed_at = None
    job.result_data = None
    return job


@pytest.fixture
def mock_job_running():
    """Create a mock running job."""
    job = MagicMock()
    job.id = "test-job-002"
    job.status = "running"
    job.progress = 50
    job.error_message = None
    job.created_at = datetime(2024, 1, 1, 12, 0, 0)
    job.started_at = datetime(2024, 1, 1, 12, 0, 5)
    job.completed_at = None
    job.result_data = None
    return job


@pytest.fixture
def mock_job_completed():
    """Create a mock completed job with results."""
    job = MagicMock()
    job.id = "test-job-003"
    job.status = "completed"
    job.progress = 100
    job.error_message = None
    job.created_at = datetime(2024, 1, 1, 12, 0, 0)
    job.started_at = datetime(2024, 1, 1, 12, 0, 5)
    job.completed_at = datetime(2024, 1, 1, 12, 5, 0)
    job.result_data = {"predictions": [1.0, 2.0, 3.0]}
    return job


class TestGetStatus:
    """Test cases for GET /status/{job_id} endpoint."""

    def test_get_status_queued_job(self, client, mock_job_queued):
        """Test getting status of a queued job."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_queued):
            response = client.get("/api/v1/status/test-job-001")

            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "test-job-001"
            assert data["status"] == "queued"
            assert data["progress"] == 0
            assert data["error_message"] is None
            assert "result_url" not in data or data.get("result_url") is None

    def test_get_status_running_job(self, client, mock_job_running):
        """Test getting status of a running job."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_running):
            response = client.get("/api/v1/status/test-job-002")

            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "test-job-002"
            assert data["status"] == "running"
            assert data["progress"] == 50
            assert data["started_at"] is not None

    def test_get_status_completed_job_includes_result_url(self, client, mock_job_completed):
        """Test that completed job status includes result_url."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_completed):
            response = client.get("/api/v1/status/test-job-003")

            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "test-job-003"
            assert data["status"] == "completed"
            assert data["progress"] == 100
            assert "result_url" in data
            assert data["result_url"] == "/api/v1/results/test-job-003"

    def test_get_status_job_not_found(self, client):
        """Test getting status of non-existent job returns 404."""
        with patch("backend.api.jobs.get_job", return_value=None):
            response = client.get("/api/v1/status/non-existent-job")

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()


class TestCancelJob:
    """Test cases for DELETE /cancel/{job_id} endpoint."""

    def test_cancel_queued_job_success(self, client, mock_job_queued):
        """Test successfully canceling a queued job."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_queued), \
             patch("backend.api.jobs.celery_app.control.revoke") as mock_revoke, \
             patch("backend.api.jobs.update_job_status", return_value=True):

            response = client.delete("/api/v1/cancel/test-job-001")

            assert response.status_code == 200
            data = response.json()
            assert "cancelled" in data["message"].lower()
            assert "test-job-001" in data["message"]
            mock_revoke.assert_called_once_with("test-job-001", terminate=True)

    def test_cancel_running_job_success(self, client, mock_job_running):
        """Test successfully canceling a running job."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_running), \
             patch("backend.api.jobs.celery_app.control.revoke") as mock_revoke, \
             patch("backend.api.jobs.update_job_status", return_value=True):

            response = client.delete("/api/v1/cancel/test-job-002")

            assert response.status_code == 200
            data = response.json()
            assert "cancelled" in data["message"].lower()
            mock_revoke.assert_called_once()

    def test_cancel_completed_job_fails_with_400(self, client, mock_job_completed):
        """Test canceling a completed job returns 400."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_completed):
            response = client.delete("/api/v1/cancel/test-job-003")

            assert response.status_code == 400
            data = response.json()
            assert "cannot" in data["detail"].lower() or "not" in data["detail"].lower()

    def test_cancel_job_not_found(self, client):
        """Test canceling non-existent job returns 404."""
        with patch("backend.api.jobs.get_job", return_value=None):
            response = client.delete("/api/v1/cancel/non-existent-job")

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()


class TestGetResults:
    """Test cases for GET /results/{job_id} endpoint."""

    def test_get_results_completed_job_success(self, client, mock_job_completed):
        """Test retrieving results from a completed job."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_completed):
            response = client.get("/api/v1/results/test-job-003")

            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "test-job-003"
            assert data["status"] == "completed"
            assert data["data"] == {"predictions": [1.0, 2.0, 3.0]}
            assert data["completed_at"] is not None

    def test_get_results_queued_job_fails_with_400(self, client, mock_job_queued):
        """Test retrieving results from a queued job returns 400."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_queued):
            response = client.get("/api/v1/results/test-job-001")

            assert response.status_code == 400
            data = response.json()
            assert "not completed" in data["detail"].lower()

    def test_get_results_running_job_fails_with_400(self, client, mock_job_running):
        """Test retrieving results from a running job returns 400."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_running):
            response = client.get("/api/v1/results/test-job-002")

            assert response.status_code == 400
            data = response.json()
            assert "not completed" in data["detail"].lower()

    def test_get_results_job_not_found(self, client):
        """Test retrieving results from non-existent job returns 404."""
        with patch("backend.api.jobs.get_job", return_value=None):
            response = client.get("/api/v1/results/non-existent-job")

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
