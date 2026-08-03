"""
Mock test script for the POST /predict endpoint.

This script tests the predict endpoint locally using mocked database and Celery.
"""

import sys
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Mock the database connection before importing backend modules
with patch("backend.db.jobs.SessionLocal"), \
     patch("backend.db.jobs.engine"), \
     patch("db.session.create_engine"), \
     patch("db.session.sessionmaker"):

    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.models import PredictRequest, JobStatus

    # Create test client
    client = TestClient(app)


def test_health_check():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    print("✓ Health check test passed")


def test_predict_endpoint_valid():
    """Test predict endpoint with valid request."""
    # Mock the Celery task
    with patch("backend.api.predict.predict_task.apply_async") as mock_celery, \
         patch("backend.api.predict.create_job") as mock_create_job, \
         patch("backend.api.predict.update_job_status") as mock_update_status:

        # Setup mock returns
        mock_create_job.return_value = "test_job_123"
        mock_celery.return_value = MagicMock(id="test_job_123")

        request_data = {
            "space_id": "space_001",
            "features": {
                "temperature": 22.5,
                "humidity": 45.0,
                "co2": 450.0,
            },
            "model_version": "1.0.0"
        }

        response = client.post("/api/v1/predict", json=request_data)
        print(f"Response status code: {response.status_code}")
        print(f"Response: {response.json()}")

        assert response.status_code == 202, f"Expected 202, got {response.status_code}"

        data = response.json()
        assert "job_id" in data
        assert data["status"] in ["pending", "queued"]
        assert "message" in data

        # Verify create_job was called
        mock_create_job.assert_called_once()
        assert mock_create_job.call_args[1]["job_type"] == "ml_predict"

        # Verify Celery task was queued
        mock_celery.assert_called_once()

        print(f"✓ Predict endpoint test passed with job_id: {data['job_id']}")
        return data["job_id"]


def test_predict_endpoint_missing_space_id():
    """Test predict endpoint with missing space_id."""
    request_data = {
        "features": {
            "temperature": 22.5,
            "humidity": 45.0,
        },
    }

    response = client.post("/api/v1/predict", json=request_data)
    print(f"Response status code: {response.status_code}")
    print(f"Response: {response.json()}")

    # This should fail validation before reaching the endpoint
    assert response.status_code in [400, 422]
    print("✓ Missing space_id test passed")


def test_predict_endpoint_empty_features():
    """Test predict endpoint with empty features."""
    with patch("backend.api.predict.predict_task.apply_async") as mock_celery, \
         patch("backend.api.predict.create_job") as mock_create_job, \
         patch("backend.api.predict.update_job_status") as mock_update_status:

        request_data = {
            "space_id": "space_001",
            "features": {},
        }

        response = client.post("/api/v1/predict", json=request_data)
        print(f"Response status code: {response.status_code}")
        print(f"Response: {response.json()}")

        assert response.status_code == 400
        assert "features must be a non-empty dictionary" in response.json()["detail"]
        print("✓ Empty features test passed")


def test_predict_endpoint_invalid_request():
    """Test predict endpoint with invalid request (missing features)."""
    request_data = {
        "space_id": "space_001",
    }

    response = client.post("/api/v1/predict", json=request_data)
    print(f"Response status code: {response.status_code}")
    print(f"Response: {response.json()}")

    # Should fail validation
    assert response.status_code == 422
    print("✓ Invalid request test passed")


def test_predict_task_function():
    """Test the predict_task Celery task function."""
    from backend.api.predict import predict_task

    # Create a mock self object for the task
    mock_self = MagicMock()
    mock_self.request.retries = 0
    mock_self.retry = MagicMock(side_effect=Exception("Retry triggered"))

    with patch("backend.api.predict.update_job_status") as mock_update, \
         patch("backend.api.predict.store_result") as mock_store:

        mock_update.return_value = True
        mock_store.return_value = True

        # Call the task
        result = predict_task(
            mock_self,
            job_id="test_job_123",
            space_id="space_001",
            features={"temperature": 22.5},
            model_version="1.0.0"
        )

        # Verify status updates
        assert mock_update.call_count >= 2  # At least running and completed
        assert mock_store.called

        # Verify result structure
        assert "job_id" in result
        assert result["job_id"] == "test_job_123"
        assert result["status"] == "completed"
        assert "results" in result

        print("✓ Predict task function test passed")


if __name__ == "__main__":
    print("Running predict endpoint tests (with mocks)...\n")

    try:
        print("1. Testing health check endpoint...")
        test_health_check()
        print()

        print("2. Testing predict endpoint with valid request...")
        job_id = test_predict_endpoint_valid()
        print()

        print("3. Testing predict endpoint with missing space_id...")
        test_predict_endpoint_missing_space_id()
        print()

        print("4. Testing predict endpoint with empty features...")
        test_predict_endpoint_empty_features()
        print()

        print("5. Testing predict endpoint with invalid request...")
        test_predict_endpoint_invalid_request()
        print()

        print("6. Testing predict_task Celery task...")
        test_predict_task_function()
        print()

        print("=" * 50)
        print("All tests passed!")
        print("=" * 50)

    except Exception as e:
        print(f"✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
