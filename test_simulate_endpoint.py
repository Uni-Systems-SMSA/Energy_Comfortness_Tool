"""
Test script for the POST /simulate endpoint.

This script tests the simulate endpoint locally using FastAPI's TestClient.
"""

import sys
import os
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient
from backend.main import app
from backend.models import SimulateRequest, JobStatus

# Create test client
client = TestClient(app)


def test_health_check():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    print("✓ Health check test passed")


def test_simulate_endpoint_valid():
    """Test simulate endpoint with valid request."""
    request_data = {
        "building_id": "building_001",
        "ifc_file_id": "ifc_001",
        "weather_data_id": "weather_001",
        "parameters": {
            "simulation_days": 365,
            "timestep": 60,
        }
    }

    response = client.post("/api/v1/simulate", json=request_data)
    print(f"Response status code: {response.status_code}")
    print(f"Response: {response.json()}")

    assert response.status_code == 202, f"Expected 202, got {response.status_code}"

    data = response.json()
    assert "job_id" in data
    assert data["status"] in ["pending", "queued"]
    assert "estimated_wait_time_seconds" in data

    print(f"✓ Simulate endpoint test passed with job_id: {data['job_id']}")
    return data["job_id"]


def test_simulate_endpoint_missing_building_id():
    """Test simulate endpoint with missing building_id."""
    request_data = {
        "ifc_file_id": "ifc_001",
        "weather_data_id": "weather_001",
    }

    response = client.post("/api/v1/simulate", json=request_data)
    print(f"Response status code: {response.status_code}")
    print(f"Response: {response.json()}")

    # This should fail validation before reaching the endpoint
    assert response.status_code in [400, 422]
    print("✓ Missing building_id test passed")


def test_simulate_endpoint_missing_ifc_file_id():
    """Test simulate endpoint with missing ifc_file_id."""
    request_data = {
        "building_id": "building_001",
        "weather_data_id": "weather_001",
    }

    response = client.post("/api/v1/simulate", json=request_data)
    print(f"Response status code: {response.status_code}")
    print(f"Response: {response.json()}")

    # This should fail validation before reaching the endpoint
    assert response.status_code in [400, 422]
    print("✓ Missing ifc_file_id test passed")


def test_simulate_endpoint_missing_weather_data_id():
    """Test simulate endpoint with missing weather_data_id."""
    request_data = {
        "building_id": "building_001",
        "ifc_file_id": "ifc_001",
    }

    response = client.post("/api/v1/simulate", json=request_data)
    print(f"Response status code: {response.status_code}")
    print(f"Response: {response.json()}")

    # This should fail validation before reaching the endpoint
    assert response.status_code in [400, 422]
    print("✓ Missing weather_data_id test passed")


def test_simulate_endpoint_no_parameters():
    """Test simulate endpoint without parameters."""
    request_data = {
        "building_id": "building_001",
        "ifc_file_id": "ifc_001",
        "weather_data_id": "weather_001",
    }

    response = client.post("/api/v1/simulate", json=request_data)
    print(f"Response status code: {response.status_code}")
    print(f"Response: {response.json()}")

    assert response.status_code == 202, f"Expected 202, got {response.status_code}"
    data = response.json()
    assert "job_id" in data
    print("✓ Simulate endpoint without parameters test passed")


if __name__ == "__main__":
    print("Running simulate endpoint tests...\n")

    try:
        print("1. Testing health check endpoint...")
        test_health_check()
        print()

        print("2. Testing simulate endpoint with valid request...")
        job_id = test_simulate_endpoint_valid()
        print()

        print("3. Testing simulate endpoint with missing building_id...")
        test_simulate_endpoint_missing_building_id()
        print()

        print("4. Testing simulate endpoint with missing ifc_file_id...")
        test_simulate_endpoint_missing_ifc_file_id()
        print()

        print("5. Testing simulate endpoint with missing weather_data_id...")
        test_simulate_endpoint_missing_weather_data_id()
        print()

        print("6. Testing simulate endpoint without parameters...")
        test_simulate_endpoint_no_parameters()
        print()

        print("=" * 50)
        print("All tests passed!")
        print("=" * 50)

    except Exception as e:
        print(f"✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
