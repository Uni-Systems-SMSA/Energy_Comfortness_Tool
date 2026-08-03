"""
HTTP client for communicating with the FastAPI backend.

This module provides the APIClient class which handles all HTTP requests
to the FastAPI backend endpoints for job submission, status checking,
result retrieval, and job cancellation.
"""

import os
import logging
import requests
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class JobStatus:
    """Represents the status of a job."""
    job_id: str
    status: str  # queued, running, completed, failed, cancelled
    progress: int  # 0-100
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_url: Optional[str] = None


class APIClient:
    """HTTP client for FastAPI backend."""

    def __init__(self, base_url: Optional[str] = None, timeout: int = 30):
        """
        Initialize the API client.

        Args:
            base_url: Base URL for the FastAPI backend (default: http://localhost:8000)
            timeout: Request timeout in seconds (default: 30)
        """
        self.base_url = base_url or os.environ.get("FASTAPI_URL", "http://localhost:8000")
        self.timeout = timeout
        self.session = requests.Session()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the backend.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint (e.g., /api/v1/predict)
            data: Form data for the request
            json: JSON data for the request

        Returns:
            Response JSON as dictionary

        Raises:
            requests.RequestException: If request fails
            ValueError: If response is invalid
        """
        url = f"{self.base_url}{endpoint}"

        try:
            logger.debug(f"Making {method} request to {url}")

            response = self.session.request(
                method=method,
                url=url,
                json=json,
                data=data,
                timeout=self.timeout,
            )

            # Log response status
            logger.debug(f"Response status: {response.status_code}")

            # Handle errors
            if response.status_code >= 400:
                try:
                    error_detail = response.json().get("detail", "Unknown error")
                except:
                    error_detail = response.text

                logger.error(f"API error {response.status_code}: {error_detail}")
                raise ValueError(f"API error {response.status_code}: {error_detail}")

            # Parse response
            return response.json()

        except requests.ConnectionError as e:
            logger.error(f"Connection error: {e}")
            raise ValueError(f"Failed to connect to backend at {self.base_url}: {e}")
        except requests.Timeout as e:
            logger.error(f"Request timeout: {e}")
            raise ValueError(f"Request timeout: {e}")
        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise ValueError(f"Request failed: {e}")

    def submit_prediction(
        self,
        building_id: str,
        space_id: str,
        date_range: Dict[str, str],
        model_type: str,
    ) -> str:
        """
        Submit a prediction job to the backend.

        Args:
            building_id: Identifier for the building
            space_id: Identifier for the space
            date_range: Dictionary with 'start' and 'end' keys (ISO format dates)
            model_type: Type of model to use for prediction

        Returns:
            job_id: Unique identifier for the submitted job

        Raises:
            ValueError: If submission fails
        """
        payload = {
            "building_id": building_id,
            "space_id": space_id,
            "date_range": date_range,
            "model_type": model_type,
        }

        logger.info(f"Submitting prediction job for building={building_id}, space={space_id}")

        try:
            response = self._make_request(
                "POST",
                "/api/v1/predict",
                json=payload
            )

            job_id = response.get("job_id")
            if not job_id:
                raise ValueError("No job_id in response")

            logger.info(f"Prediction job submitted with job_id: {job_id}")
            return job_id

        except Exception as e:
            logger.error(f"Failed to submit prediction: {e}")
            raise

    def submit_simulation(
        self,
        building_id: str,
        ifc_file_id: str,
        weather_data_id: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Submit a simulation job to the backend.

        Args:
            building_id: Identifier for the building
            ifc_file_id: Identifier for the IFC file
            weather_data_id: Identifier for the weather data
            parameters: Optional simulation parameters

        Returns:
            job_id: Unique identifier for the submitted job

        Raises:
            ValueError: If submission fails
        """
        payload = {
            "building_id": building_id,
            "ifc_file_id": ifc_file_id,
            "weather_data_id": weather_data_id,
            "parameters": parameters or {},
        }

        logger.info(f"Submitting simulation job for building={building_id}, ifc={ifc_file_id}")

        try:
            response = self._make_request(
                "POST",
                "/api/v1/simulate",
                json=payload
            )

            job_id = response.get("job_id")
            if not job_id:
                raise ValueError("No job_id in response")

            logger.info(f"Simulation job submitted with job_id: {job_id}")
            return job_id

        except Exception as e:
            logger.error(f"Failed to submit simulation: {e}")
            raise

    def get_job_status(self, job_id: str) -> JobStatus:
        """
        Get the status of a job.

        Args:
            job_id: Unique job identifier

        Returns:
            JobStatus object with current status and progress

        Raises:
            ValueError: If job not found or request fails
        """
        logger.debug(f"Fetching status for job {job_id}")

        try:
            response = self._make_request("GET", f"/api/v1/status/{job_id}")

            # Parse response into JobStatus object
            status = JobStatus(
                job_id=response.get("job_id"),
                status=response.get("status"),
                progress=response.get("progress", 0),
                error_message=response.get("error_message"),
                created_at=self._parse_datetime(response.get("created_at")),
                started_at=self._parse_datetime(response.get("started_at")),
                completed_at=self._parse_datetime(response.get("completed_at")),
                result_url=response.get("result_url"),
            )

            logger.debug(f"Job {job_id} status: {status.status} ({status.progress}%)")
            return status

        except Exception as e:
            logger.error(f"Failed to get job status: {e}")
            raise

    def get_job_results(self, job_id: str) -> Dict[str, Any]:
        """
        Get the results of a completed job.

        Args:
            job_id: Unique job identifier

        Returns:
            Dictionary containing job results data

        Raises:
            ValueError: If job not found, not completed, or request fails
        """
        logger.info(f"Fetching results for job {job_id}")

        try:
            response = self._make_request("GET", f"/api/v1/results/{job_id}")

            data = response.get("data", {})
            logger.info(f"Successfully retrieved results for job {job_id}")

            return data

        except Exception as e:
            logger.error(f"Failed to get job results: {e}")
            raise

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a queued or running job.

        Args:
            job_id: Unique job identifier

        Returns:
            True if cancellation was successful

        Raises:
            ValueError: If job not found, not cancellable, or request fails
        """
        logger.info(f"Cancelling job {job_id}")

        try:
            response = self._make_request("DELETE", f"/api/v1/cancel/{job_id}")

            logger.info(f"Job {job_id} cancelled successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel job: {e}")
            raise

    @staticmethod
    def _parse_datetime(dt_string: Optional[str]) -> Optional[datetime]:
        """
        Parse ISO format datetime string to datetime object.

        Args:
            dt_string: ISO format datetime string

        Returns:
            datetime object or None if input is None
        """
        if not dt_string:
            return None

        try:
            # Handle ISO format with or without Z suffix
            if dt_string.endswith('Z'):
                dt_string = dt_string[:-1] + '+00:00'

            return datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            logger.warning(f"Failed to parse datetime: {dt_string}")
            return None
