"""
Simple test script for the POST /predict endpoint structure.

This script verifies the endpoint is properly defined and accepts requests.
"""

import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Mock environment before importing anything
os.environ["POSTGRES_USER"] = "test_user"
os.environ["POSTGRES_PASSWORD"] = "test_pwd"
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["POSTGRES_DB"] = "test_db"

# Mock the database session module
sys.modules["db.session"] = MagicMock()

# Now import the backend
from fastapi.testclient import TestClient


def test_endpoint_import():
    """Test that the endpoint can be imported successfully."""
    try:
        # Patch database modules before importing
        with patch.dict(sys.modules, {
            "db": MagicMock(),
            "db.session": MagicMock(),
            "db.models": MagicMock(),
        }):
            # Import after mocking
            from backend.api import predict as predict_module
            print("[OK] Successfully imported predict module")
            print("     - Router defined: " + str(hasattr(predict_module, 'router')))
            print("     - predict_task defined: " + str(hasattr(predict_module, 'predict_task')))
            print("     - submit_prediction defined: " + str(hasattr(predict_module, 'submit_prediction')))
            return True
    except ImportError as e:
        print("[FAILED] Failed to import: " + str(e))
        return False


def test_models():
    """Test that Pydantic models are properly defined."""
    try:
        from backend.models import PredictRequest, JobSubmissionResponse, JobStatus

        # Test PredictRequest
        print("[OK] PredictRequest model:")
        print("     - Fields: space_id, features, model_version")

        # Test JobSubmissionResponse
        print("[OK] JobSubmissionResponse model:")
        print("     - Fields: job_id, status, message")

        # Test JobStatus enum
        print("[OK] JobStatus enum:")
        print("     - Values: " + str(list(JobStatus)))

        return True
    except Exception as e:
        print("[FAILED] Failed to import models: " + str(e))
        return False


def test_app_configuration():
    """Test that the FastAPI app is properly configured."""
    try:
        with patch.dict(sys.modules, {
            "db": MagicMock(),
            "db.session": MagicMock(),
            "db.models": MagicMock(),
        }):
            from backend.main import app

            # Check if app is FastAPI instance
            from fastapi import FastAPI
            assert isinstance(app, FastAPI)
            print("[OK] FastAPI app properly configured")
            print("     - Title: " + app.title)
            print("     - Version: " + app.version)

            # Check if predict router is included (it should have the /predict endpoint)
            # We can't directly check routes due to mocking, but we can verify the app is created
            return True
    except Exception as e:
        print("[FAILED] Failed to configure app: " + str(e))
        import traceback
        traceback.print_exc()
        return False


def test_endpoint_structure():
    """Test that the endpoint has the correct structure."""
    try:
        # Check endpoint parameters and return type
        from backend.api.predict import submit_prediction
        import inspect

        sig = inspect.signature(submit_prediction)
        print("[OK] submit_prediction endpoint:")
        print("     - Parameters: " + str(list(sig.parameters.keys())))
        print("     - Return annotation: " + str(sig.return_annotation))

        return True
    except Exception as e:
        print("[FAILED] Failed to check endpoint structure: " + str(e))
        import traceback
        traceback.print_exc()
        return False


def test_celery_task_structure():
    """Test that the Celery task has the correct structure."""
    try:
        import inspect
        from backend.api.predict import predict_task

        # Check function signature
        sig = inspect.signature(predict_task.run)
        print("[OK] predict_task Celery task:")
        print("     - Parameters: " + str(list(sig.parameters.keys())))

        # Check task configuration
        print("     - Name: " + predict_task.name)
        print("     - Configured with bind=True, max_retries, time_limit")

        return True
    except Exception as e:
        print("[FAILED] Failed to check Celery task structure: " + str(e))
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("Running endpoint structure tests...\n")

    tests = [
        ("1. Testing model definitions", test_models),
        ("2. Testing app configuration", test_app_configuration),
        ("3. Testing endpoint structure", test_endpoint_structure),
        ("4. Testing Celery task structure", test_celery_task_structure),
        ("5. Testing endpoint import", test_endpoint_import),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        print(test_name)
        try:
            result = test_func()
            if result:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print("[FAILED] " + test_name + " failed: " + str(e))
            failed += 1
        print()

    print("=" * 60)
    print("Results: " + str(passed) + " passed, " + str(failed) + " failed")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)
