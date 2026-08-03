"""
Test script for the POST /predict endpoint.

This script tests the predict endpoint locally using FastAPI's TestClient.
"""

import sys
import os
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

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


if __name__ == "__main__":
    print("Running predict endpoint tests...\n")

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

        print("=" * 50)
        print("All tests passed!")
        print("=" * 50)

    except Exception as e:
        print(f"✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
