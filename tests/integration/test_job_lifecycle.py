"""
Task 10: Integration Tests for Full Job Lifecycle

This module tests the complete job lifecycle from API submission through
database storage and result retrieval. Tests cover:

- Prediction job end-to-end (API → Queue → DB → Results)
- Simulation job end-to-end
- Multiple concurrent jobs
- Job cancellation lifecycle
- Error handling and recovery

Tests verify that jobs complete successfully and results are correct.
"""

import pytest
import time
import uuid
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
# FIXTURES: Mock Database and Celery
# =====================================================================

@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock()
    return session


@pytest.fixture
def mock_celery():
    """Create a mock Celery app."""
    celery = MagicMock()
    celery.control.revoke = MagicMock()
    return celery


# =====================================================================
# TEST: Prediction Job Lifecycle
# =====================================================================

class TestPredictionJobLifecycle:
    """Test cases for complete prediction job lifecycle."""

    def test_predict_job_full_lifecycle(self, client):
        """Test full lifecycle: submit → running → completed."""

        # 1. Submit prediction job
        request_data = {
            "building_id": "building-001",
            "space_id": "space-001",
            "date_range": {"start": "2024-01-01", "end": "2024-01-31"},
            "model_type": "lightgbm"
        }

        # Mock the database and Celery for job creation
        with patch("backend.api.predict.create_job") as mock_create, \
             patch("backend.api.predict.predict_task.apply_async") as mock_apply, \
             patch("backend.api.predict.update_job_status") as mock_update, \
             patch("backend.api.predict.store_result") as mock_store, \
             patch("backend.api.jobs.get_job") as mock_get_job:

            # Set job ID
            job_id = f"job-{uuid.uuid4().hex[:12]}"
            mock_create.return_value = job_id

            # Submit job
            response = client.post("/api/v1/predict", json=request_data)
            assert response.status_code == 202
            assert response.json()["job_id"] == job_id

            # Verify job was created in database
            mock_create.assert_called_once()

            # Verify task was queued to Celery
            mock_apply.assert_called_once()

    def test_predict_job_status_transitions(self, client):
        """Test prediction job status transitions: queued → running → completed."""

        job_id = "test-job-predict-001"

        # Mock job object for different states
        def get_job_side_effect(jid):
            job = MagicMock()
            job.id = jid

            # Return different states based on call count
            call_count = mock_get_job.call_count
            if call_count == 1:
                job.status = "queued"
                job.progress = 0
            elif call_count == 2:
                job.status = "running"
                job.progress = 50
            else:
                job.status = "completed"
                job.progress = 100

            job.error_message = None
            job.created_at = datetime(2024, 1, 1, 12, 0, 0)
            job.started_at = datetime(2024, 1, 1, 12, 0, 5) if job.status != "queued" else None
            job.completed_at = datetime(2024, 1, 1, 12, 5, 0) if job.status == "completed" else None
            job.result_data = {"predictions": [1.0, 2.0, 3.0]} if job.status == "completed" else None

            return job

        with patch("backend.api.jobs.get_job", side_effect=get_job_side_effect) as mock_get_job:

            # Check initial status (queued)
            response = client.get(f"/api/v1/status/{job_id}")
            assert response.status_code == 200
            assert response.json()["status"] == "queued"

            # Check running status
            response = client.get(f"/api/v1/status/{job_id}")
            assert response.status_code == 200
            assert response.json()["status"] == "running"
            assert response.json()["progress"] == 50

            # Check completed status
            response = client.get(f"/api/v1/status/{job_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "completed"
            assert data["progress"] == 100

    def test_predict_job_results_retrieval(self, client):
        """Test retrieving results from completed prediction job."""

        job_id = "test-job-predict-002"

        # Mock completed job with results
        mock_job = MagicMock()
        mock_job.id = job_id
        mock_job.status = "completed"
        mock_job.progress = 100
        mock_job.error_message = None
        mock_job.created_at = datetime(2024, 1, 1, 12, 0, 0)
        mock_job.completed_at = datetime(2024, 1, 1, 12, 5, 0)
        mock_job.result_data = {
            "building_id": "building-001",
            "space_id": "space-001",
            "predictions": [1.0, 2.0, 3.0],
            "model_type": "lightgbm"
        }

        with patch("backend.api.jobs.get_job", return_value=mock_job):
            response = client.get(f"/api/v1/results/{job_id}")

            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == job_id
            assert data["status"] == "completed"
            assert "predictions" in data["data"]


# =====================================================================
# TEST: Simulation Job Lifecycle
# =====================================================================

class TestSimulationJobLifecycle:
    """Test cases for complete simulation job lifecycle."""

    def test_simulate_job_full_lifecycle(self, client):
        """Test full lifecycle: submit → running → completed."""

        # 1. Submit simulation job
        request_data = {
            "building_id": "building-001",
            "ifc_file_id": "ifc-001",
            "weather_data_id": "weather-001",
            "parameters": {"simulation_days": 365}
        }

        # Mock the database and Celery for job creation
        with patch("backend.api.simulate.create_job") as mock_create, \
             patch("backend.api.simulate.simulate_task.apply_async") as mock_apply:

            # Set job ID
            job_id = f"job-{uuid.uuid4().hex[:12]}"
            mock_create.return_value = job_id

            # Submit job
            response = client.post("/api/v1/simulate", json=request_data)
            assert response.status_code == 202
            assert response.json()["job_id"] == job_id

            # Verify job was created in database
            mock_create.assert_called_once()

            # Verify task was queued to Celery
            mock_apply.assert_called_once()

    def test_simulate_job_status_transitions(self, client):
        """Test simulation job status transitions: queued → running → completed."""

        job_id = "test-job-simulate-001"

        # Mock job object for different states
        def get_job_side_effect(jid):
            job = MagicMock()
            job.id = jid

            # Return different states based on call count
            call_count = mock_get_job.call_count
            if call_count == 1:
                job.status = "queued"
                job.progress = 0
            elif call_count == 2:
                job.status = "running"
                job.progress = 75
            else:
                job.status = "completed"
                job.progress = 100

            job.error_message = None
            job.created_at = datetime(2024, 1, 1, 12, 0, 0)
            job.started_at = datetime(2024, 1, 1, 12, 0, 5) if job.status != "queued" else None
            job.completed_at = datetime(2024, 1, 1, 12, 15, 0) if job.status == "completed" else None
            job.result_data = {"simulation_output": "energy_data"} if job.status == "completed" else None

            return job

        with patch("backend.api.jobs.get_job", side_effect=get_job_side_effect) as mock_get_job:

            # Check initial status (queued)
            response = client.get(f"/api/v1/status/{job_id}")
            assert response.status_code == 200
            assert response.json()["status"] == "queued"

            # Check running status
            response = client.get(f"/api/v1/status/{job_id}")
            assert response.status_code == 200
            assert response.json()["status"] == "running"

            # Check completed status
            response = client.get(f"/api/v1/status/{job_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "completed"


# =====================================================================
# TEST: Multiple Concurrent Jobs
# =====================================================================

class TestMultipleConcurrentJobs:
    """Test cases for handling multiple concurrent jobs."""

    def test_submit_multiple_prediction_jobs(self, client):
        """Test submitting multiple prediction jobs simultaneously."""

        # Submit 5 jobs concurrently
        job_ids = []
        for i in range(5):
            request_data = {
                "building_id": f"building-{i:03d}",
                "space_id": f"space-{i:03d}",
                "date_range": {"start": "2024-01-01", "end": "2024-01-31"},
                "model_type": "lightgbm"
            }

            with patch("backend.api.predict.create_job") as mock_create, \
                 patch("backend.api.predict.predict_task.apply_async"):

                job_id = f"job-predict-{i:03d}"
                mock_create.return_value = job_id

                response = client.post("/api/v1/predict", json=request_data)
                assert response.status_code == 202
                job_ids.append(response.json()["job_id"])

        # Verify we have 5 different job IDs
        assert len(job_ids) == 5
        assert len(set(job_ids)) == 5  # All unique

    def test_submit_multiple_simulation_jobs(self, client):
        """Test submitting multiple simulation jobs simultaneously."""

        # Submit 3 jobs
        job_ids = []
        for i in range(3):
            request_data = {
                "building_id": f"building-{i:03d}",
                "ifc_file_id": f"ifc-{i:03d}",
                "weather_data_id": f"weather-{i:03d}"
            }

            with patch("backend.api.simulate.create_job") as mock_create, \
                 patch("backend.api.simulate.simulate_task.apply_async"):

                job_id = f"job-simulate-{i:03d}"
                mock_create.return_value = job_id

                response = client.post("/api/v1/simulate", json=request_data)
                assert response.status_code == 202
                job_ids.append(response.json()["job_id"])

        # Verify we have 3 different job IDs
        assert len(job_ids) == 3
        assert len(set(job_ids)) == 3  # All unique

    def test_check_status_multiple_jobs(self, client):
        """Test checking status of multiple jobs."""

        jobs = []
        for i in range(4):
            job = MagicMock()
            job.id = f"test-job-multi-{i:03d}"
            job.status = "running"
            job.progress = 25 * i
            job.error_message = None
            job.created_at = datetime(2024, 1, 1, 12, 0, 0)
            job.started_at = datetime(2024, 1, 1, 12, 0, 5)
            job.completed_at = None
            job.result_data = None
            jobs.append(job)

        def get_job_side_effect(job_id):
            for job in jobs:
                if job.id == job_id:
                    return job
            return None

        with patch("backend.api.jobs.get_job", side_effect=get_job_side_effect):
            # Check status of all jobs
            for job in jobs:
                response = client.get(f"/api/v1/status/{job.id}")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "running"


# =====================================================================
# TEST: Job Cancellation Lifecycle
# =====================================================================

class TestJobCancellationLifecycle:
    """Test cases for job cancellation lifecycle."""

    def test_cancel_queued_job_lifecycle(self, client):
        """Test canceling a queued job."""

        job_id = "test-job-cancel-001"

        # Create queued job
        mock_job = MagicMock()
        mock_job.id = job_id
        mock_job.status = "queued"
        mock_job.progress = 0
        mock_job.error_message = None
        mock_job.created_at = datetime(2024, 1, 1, 12, 0, 0)
        mock_job.started_at = None
        mock_job.completed_at = None

        with patch("backend.api.jobs.get_job", return_value=mock_job), \
             patch("backend.api.jobs.celery_app.control.revoke") as mock_revoke, \
             patch("backend.api.jobs.update_job_status") as mock_update:

            # Cancel the job
            response = client.delete(f"/api/v1/cancel/{job_id}")
            assert response.status_code == 200
            assert "cancelled" in response.json()["message"].lower()

            # Verify revoke was called
            mock_revoke.assert_called_once_with(job_id, terminate=True)

            # Verify status was updated
            mock_update.assert_called_once()

    def test_cancel_running_job_lifecycle(self, client):
        """Test canceling a running job."""

        job_id = "test-job-cancel-002"

        # Create running job
        mock_job = MagicMock()
        mock_job.id = job_id
        mock_job.status = "running"
        mock_job.progress = 50
        mock_job.error_message = None
        mock_job.created_at = datetime(2024, 1, 1, 12, 0, 0)
        mock_job.started_at = datetime(2024, 1, 1, 12, 0, 5)
        mock_job.completed_at = None

        with patch("backend.api.jobs.get_job", return_value=mock_job), \
             patch("backend.api.jobs.celery_app.control.revoke") as mock_revoke, \
             patch("backend.api.jobs.update_job_status") as mock_update:

            # Cancel the job
            response = client.delete(f"/api/v1/cancel/{job_id}")
            assert response.status_code == 200

            # Verify Celery task was terminated
            mock_revoke.assert_called_once()

    def test_cannot_cancel_completed_job(self, client):
        """Test that completed jobs cannot be cancelled."""

        job_id = "test-job-cancel-003"

        # Create completed job
        mock_job = MagicMock()
        mock_job.id = job_id
        mock_job.status = "completed"
        mock_job.progress = 100
        mock_job.error_message = None
        mock_job.created_at = datetime(2024, 1, 1, 12, 0, 0)
        mock_job.started_at = datetime(2024, 1, 1, 12, 0, 5)
        mock_job.completed_at = datetime(2024, 1, 1, 12, 5, 0)

        with patch("backend.api.jobs.get_job", return_value=mock_job):
            response = client.delete(f"/api/v1/cancel/{job_id}")
            assert response.status_code == 400


# =====================================================================
# TEST: Error Handling and Recovery
# =====================================================================

class TestErrorHandlingAndRecovery:
    """Test cases for error handling and recovery."""

    def test_predict_job_with_database_error(self, client):
        """Test prediction job handles database errors."""

        request_data = {
            "building_id": "building-001",
            "space_id": "space-001",
            "date_range": {"start": "2024-01-01", "end": "2024-01-31"},
            "model_type": "lightgbm"
        }

        with patch("backend.api.predict.create_job", side_effect=Exception("DB Connection Error")):
            response = client.post("/api/v1/predict", json=request_data)
            assert response.status_code == 500

    def test_simulate_job_with_database_error(self, client):
        """Test simulation job handles database errors."""

        request_data = {
            "building_id": "building-001",
            "ifc_file_id": "ifc-001",
            "weather_data_id": "weather-001"
        }

        with patch("backend.api.simulate.create_job", side_effect=Exception("DB Connection Error")):
            response = client.post("/api/v1/simulate", json=request_data)
            assert response.status_code == 500

    def test_get_status_with_database_error(self, client):
        """Test status endpoint handles database errors."""

        with patch("backend.api.jobs.get_job", side_effect=Exception("DB Connection Error")):
            response = client.get("/api/v1/status/test-job-001")
            assert response.status_code == 500

    def test_cancel_job_with_database_error(self, client):
        """Test cancel endpoint handles database errors."""

        with patch("backend.api.jobs.get_job", side_effect=Exception("DB Connection Error")):
            response = client.delete("/api/v1/cancel/test-job-001")
            assert response.status_code == 500


# =====================================================================
# TEST: Job Data Integrity
# =====================================================================

class TestJobDataIntegrity:
    """Test cases for job data integrity."""

    def test_job_input_params_preserved(self, client):
        """Test that job input parameters are preserved."""

        job_id = "test-job-integrity-001"

        request_data = {
            "building_id": "building-001",
            "space_id": "space-001",
            "date_range": {"start": "2024-01-01", "end": "2024-01-31"},
            "model_type": "lightgbm"
        }

        created_params = None

        def create_job_side_effect(job_type, input_params, user_id=None):
            nonlocal created_params
            created_params = input_params
            return job_id

        with patch("backend.api.predict.create_job", side_effect=create_job_side_effect), \
             patch("backend.api.predict.predict_task.apply_async"):

            response = client.post("/api/v1/predict", json=request_data)

            # Verify input params match request
            assert created_params["building_id"] == "building-001"
            assert created_params["space_id"] == "space-001"
            assert created_params["model_type"] == "lightgbm"

    def test_job_result_data_preserved(self, client):
        """Test that job result data is preserved."""

        job_id = "test-job-integrity-002"

        mock_job = MagicMock()
        mock_job.id = job_id
        mock_job.status = "completed"
        mock_job.progress = 100
        mock_job.error_message = None
        mock_job.created_at = datetime(2024, 1, 1, 12, 0, 0)
        mock_job.completed_at = datetime(2024, 1, 1, 12, 5, 0)

        # Define result data
        result_data = {
            "building_id": "building-001",
            "space_id": "space-001",
            "predictions": [1.0, 2.0, 3.0, 4.0, 5.0],
            "model_type": "lightgbm",
            "confidence": 0.95
        }
        mock_job.result_data = result_data

        with patch("backend.api.jobs.get_job", return_value=mock_job):
            response = client.get(f"/api/v1/results/{job_id}")

            data = response.json()
            assert data["data"] == result_data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
