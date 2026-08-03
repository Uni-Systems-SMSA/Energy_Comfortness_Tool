"""
Task 9: Unit Tests for FastAPI Backend Endpoints

This module tests all API endpoints with mock jobs:
- POST /predict - Submit prediction jobs
- POST /simulate - Submit simulation jobs
- GET /status/{job_id} - Get job status
- DELETE /cancel/{job_id} - Cancel jobs
- GET /results/{job_id} - Get job results
- GET /health - Health check

Tests use mocked database and Celery tasks for unit testing.
"""

import pytest
import json
from datetime import datetime
from unittest.mock import patch, MagicMock, Mock
from fastapi.testclient import TestClient

from backend.main import app
from backend.models import JobStatus


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


# =====================================================================
# FIXTURES: Mock Jobs
# =====================================================================

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
    job.result_data = {"predictions": [1.0, 2.0, 3.0], "model": "lightgbm"}
    return job


@pytest.fixture
def mock_job_failed():
    """Create a mock failed job."""
    job = MagicMock()
    job.id = "test-job-004"
    job.status = "failed"
    job.progress = 25
    job.error_message = "Connection timeout to database"
    job.created_at = datetime(2024, 1, 1, 12, 0, 0)
    job.started_at = datetime(2024, 1, 1, 12, 0, 5)
    job.completed_at = datetime(2024, 1, 1, 12, 1, 0)
    job.result_data = None
    return job


# =====================================================================
# TEST: Health Check Endpoint
# =====================================================================

class TestHealthCheck:
    """Test cases for GET /health endpoint."""

    def test_health_check_returns_200(self, client):
        """Test health check endpoint returns 200."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_check_has_status_field(self, client):
        """Test health check response has status field."""
        response = client.get("/health")
        data = response.json()
        assert "status" in data


# =====================================================================
# TEST: Predict Endpoint (Task 9 - POST /predict)
# =====================================================================

class TestPredictEndpoint:
    """Test cases for POST /predict endpoint."""

    def test_submit_prediction_success(self, client):
        """Test submitting a valid prediction request."""
        request_data = {
            "building_id": "building-001",
            "space_id": "space-001",
            "date_range": {
                "start": "2024-01-01",
                "end": "2024-01-31"
            },
            "model_type": "lightgbm"
        }

        with patch("backend.api.predict.create_job", return_value="test-job-001"), \
             patch("backend.api.predict.predict_task.apply_async") as mock_apply:

            response = client.post("/api/v1/predict", json=request_data)

            assert response.status_code == 202
            data = response.json()
            assert data["job_id"] == "test-job-001"
            assert data["status"] == "queued"
            assert "estimated_wait_time_seconds" in data
            mock_apply.assert_called_once()

    def test_submit_prediction_missing_building_id(self, client):
        """Test prediction request without building_id returns 400."""
        request_data = {
            "space_id": "space-001",
            "date_range": {"start": "2024-01-01", "end": "2024-01-31"},
            "model_type": "lightgbm"
        }

        response = client.post("/api/v1/predict", json=request_data)
        assert response.status_code in [400, 422]

    def test_submit_prediction_missing_space_id(self, client):
        """Test prediction request without space_id returns 400."""
        request_data = {
            "building_id": "building-001",
            "date_range": {"start": "2024-01-01", "end": "2024-01-31"},
            "model_type": "lightgbm"
        }

        response = client.post("/api/v1/predict", json=request_data)
        assert response.status_code in [400, 422]

    def test_submit_prediction_missing_date_range(self, client):
        """Test prediction request without date_range returns 400."""
        request_data = {
            "building_id": "building-001",
            "space_id": "space-001",
            "model_type": "lightgbm"
        }

        response = client.post("/api/v1/predict", json=request_data)
        assert response.status_code in [400, 422]

    def test_submit_prediction_invalid_date_range(self, client):
        """Test prediction request with invalid date_range returns 400."""
        request_data = {
            "building_id": "building-001",
            "space_id": "space-001",
            "date_range": {"start": "2024-01-01"},  # Missing 'end'
            "model_type": "lightgbm"
        }

        response = client.post("/api/v1/predict", json=request_data)
        assert response.status_code in [400, 422]

    def test_submit_prediction_missing_model_type(self, client):
        """Test prediction request without model_type returns 400."""
        request_data = {
            "building_id": "building-001",
            "space_id": "space-001",
            "date_range": {"start": "2024-01-01", "end": "2024-01-31"}
        }

        response = client.post("/api/v1/predict", json=request_data)
        assert response.status_code in [400, 422]

    def test_submit_prediction_database_error(self, client):
        """Test prediction request when database fails returns 500."""
        request_data = {
            "building_id": "building-001",
            "space_id": "space-001",
            "date_range": {"start": "2024-01-01", "end": "2024-01-31"},
            "model_type": "lightgbm"
        }

        with patch("backend.api.predict.create_job", side_effect=Exception("DB connection failed")):
            response = client.post("/api/v1/predict", json=request_data)
            assert response.status_code == 500

    def test_submit_prediction_celery_error(self, client):
        """Test prediction request when Celery fails returns 500."""
        request_data = {
            "building_id": "building-001",
            "space_id": "space-001",
            "date_range": {"start": "2024-01-01", "end": "2024-01-31"},
            "model_type": "lightgbm"
        }

        with patch("backend.api.predict.create_job", return_value="test-job-001"), \
             patch("backend.api.predict.predict_task.apply_async", side_effect=Exception("Celery error")), \
             patch("backend.api.predict.update_job_status"):

            response = client.post("/api/v1/predict", json=request_data)
            assert response.status_code == 500


# =====================================================================
# TEST: Simulate Endpoint (Task 9 - POST /simulate)
# =====================================================================

class TestSimulateEndpoint:
    """Test cases for POST /simulate endpoint."""

    def test_submit_simulation_success(self, client):
        """Test submitting a valid simulation request."""
        request_data = {
            "building_id": "building-001",
            "ifc_file_id": "ifc-001",
            "weather_data_id": "weather-001",
            "parameters": {"simulation_days": 365}
        }

        with patch("backend.api.simulate.create_job", return_value="test-job-005"), \
             patch("backend.api.simulate.simulate_task.apply_async") as mock_apply:

            response = client.post("/api/v1/simulate", json=request_data)

            assert response.status_code == 202
            data = response.json()
            assert data["job_id"] == "test-job-005"
            assert data["status"] == "queued"
            mock_apply.assert_called_once()

    def test_submit_simulation_missing_building_id(self, client):
        """Test simulation request without building_id returns 400."""
        request_data = {
            "ifc_file_id": "ifc-001",
            "weather_data_id": "weather-001"
        }

        response = client.post("/api/v1/simulate", json=request_data)
        assert response.status_code in [400, 422]

    def test_submit_simulation_missing_ifc_file_id(self, client):
        """Test simulation request without ifc_file_id returns 400."""
        request_data = {
            "building_id": "building-001",
            "weather_data_id": "weather-001"
        }

        response = client.post("/api/v1/simulate", json=request_data)
        assert response.status_code in [400, 422]

    def test_submit_simulation_missing_weather_data_id(self, client):
        """Test simulation request without weather_data_id returns 400."""
        request_data = {
            "building_id": "building-001",
            "ifc_file_id": "ifc-001"
        }

        response = client.post("/api/v1/simulate", json=request_data)
        assert response.status_code in [400, 422]

    def test_submit_simulation_with_optional_parameters(self, client):
        """Test simulation request with optional parameters."""
        request_data = {
            "building_id": "building-001",
            "ifc_file_id": "ifc-001",
            "weather_data_id": "weather-001"
        }

        with patch("backend.api.simulate.create_job", return_value="test-job-006"), \
             patch("backend.api.simulate.simulate_task.apply_async") as mock_apply:

            response = client.post("/api/v1/simulate", json=request_data)

            assert response.status_code == 202
            data = response.json()
            assert data["job_id"] == "test-job-006"

    def test_submit_simulation_database_error(self, client):
        """Test simulation request when database fails returns 500."""
        request_data = {
            "building_id": "building-001",
            "ifc_file_id": "ifc-001",
            "weather_data_id": "weather-001"
        }

        with patch("backend.api.simulate.create_job", side_effect=Exception("DB connection failed")):
            response = client.post("/api/v1/simulate", json=request_data)
            assert response.status_code == 500


# =====================================================================
# TEST: Status Endpoint (Task 9 - GET /status/{job_id})
# =====================================================================

class TestStatusEndpoint:
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

    def test_get_status_failed_job_with_error_message(self, client, mock_job_failed):
        """Test getting status of a failed job includes error message."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_failed):
            response = client.get("/api/v1/status/test-job-004")

            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "test-job-004"
            assert data["status"] == "failed"
            assert data["error_message"] == "Connection timeout to database"

    def test_get_status_job_not_found(self, client):
        """Test getting status of non-existent job returns 404."""
        with patch("backend.api.jobs.get_job", return_value=None):
            response = client.get("/api/v1/status/non-existent-job")

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()

    def test_get_status_includes_all_timestamps(self, client, mock_job_completed):
        """Test that status response includes all timestamp fields."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_completed):
            response = client.get("/api/v1/status/test-job-003")

            data = response.json()
            assert "created_at" in data
            assert "started_at" in data
            assert "completed_at" in data


# =====================================================================
# TEST: Cancel Endpoint (Task 9 - DELETE /cancel/{job_id})
# =====================================================================

class TestCancelEndpoint:
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

    def test_cancel_failed_job_fails_with_400(self, client, mock_job_failed):
        """Test canceling a failed job returns 400."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_failed):
            response = client.delete("/api/v1/cancel/test-job-004")

            assert response.status_code == 400

    def test_cancel_job_not_found(self, client):
        """Test canceling non-existent job returns 404."""
        with patch("backend.api.jobs.get_job", return_value=None):
            response = client.delete("/api/v1/cancel/non-existent-job")

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()

    def test_cancel_job_revoke_failure_continues(self, client, mock_job_queued):
        """Test that cancellation continues even if revoke fails."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_queued), \
             patch("backend.api.jobs.celery_app.control.revoke", side_effect=Exception("Revoke failed")), \
             patch("backend.api.jobs.update_job_status", return_value=True):

            response = client.delete("/api/v1/cancel/test-job-001")

            # Should still succeed even if revoke fails
            assert response.status_code == 200


# =====================================================================
# TEST: Results Endpoint (Task 9 - GET /results/{job_id})
# =====================================================================

class TestResultsEndpoint:
    """Test cases for GET /results/{job_id} endpoint."""

    def test_get_results_completed_job_success(self, client, mock_job_completed):
        """Test retrieving results from a completed job."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_completed):
            response = client.get("/api/v1/results/test-job-003")

            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "test-job-003"
            assert data["status"] == "completed"
            assert data["data"] == {"predictions": [1.0, 2.0, 3.0], "model": "lightgbm"}
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

    def test_get_results_failed_job_fails_with_400(self, client, mock_job_failed):
        """Test retrieving results from a failed job returns 400."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_failed):
            response = client.get("/api/v1/results/test-job-004")

            assert response.status_code == 400

    def test_get_results_job_not_found(self, client):
        """Test retrieving results from non-existent job returns 404."""
        with patch("backend.api.jobs.get_job", return_value=None):
            response = client.get("/api/v1/results/non-existent-job")

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()

    def test_get_results_includes_all_required_fields(self, client, mock_job_completed):
        """Test that results response includes all required fields."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_completed):
            response = client.get("/api/v1/results/test-job-003")

            data = response.json()
            assert "job_id" in data
            assert "status" in data
            assert "data" in data
            assert "created_at" in data
            assert "completed_at" in data


# =====================================================================
# INTEGRATION: Endpoint Response Validation
# =====================================================================

class TestEndpointResponseValidation:
    """Test cases for response format validation."""

    def test_predict_response_format(self, client):
        """Test that predict endpoint returns correct response format."""
        request_data = {
            "building_id": "building-001",
            "space_id": "space-001",
            "date_range": {"start": "2024-01-01", "end": "2024-01-31"},
            "model_type": "lightgbm"
        }

        with patch("backend.api.predict.create_job", return_value="test-job-001"), \
             patch("backend.api.predict.predict_task.apply_async"):

            response = client.post("/api/v1/predict", json=request_data)

            # Response should be valid JSON
            data = response.json()

            # Check all expected fields are present
            assert "job_id" in data
            assert "status" in data
            assert "estimated_wait_time_seconds" in data

    def test_simulate_response_format(self, client):
        """Test that simulate endpoint returns correct response format."""
        request_data = {
            "building_id": "building-001",
            "ifc_file_id": "ifc-001",
            "weather_data_id": "weather-001"
        }

        with patch("backend.api.simulate.create_job", return_value="test-job-005"), \
             patch("backend.api.simulate.simulate_task.apply_async"):

            response = client.post("/api/v1/simulate", json=request_data)

            # Response should be valid JSON
            data = response.json()

            # Check all expected fields are present
            assert "job_id" in data
            assert "status" in data

    def test_status_response_format(self, client, mock_job_queued):
        """Test that status endpoint returns correct response format."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_queued):
            response = client.get("/api/v1/status/test-job-001")

            data = response.json()

            # Check required fields
            assert "job_id" in data
            assert "status" in data
            assert "progress" in data
            assert "created_at" in data

    def test_results_response_format(self, client, mock_job_completed):
        """Test that results endpoint returns correct response format."""
        with patch("backend.api.jobs.get_job", return_value=mock_job_completed):
            response = client.get("/api/v1/results/test-job-003")

            data = response.json()

            # Check required fields
            assert "job_id" in data
            assert "status" in data
            assert "data" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
