"""
Task 11: Load Test for ECE Scalability

This module simulates 6+ concurrent users submitting predictions and simulations
over a 5-minute period, measuring response times and errors.

To run this load test locally:
    locust -f tests/load/locustfile.py --host=http://localhost:8000 --users=6 --spawn-rate=2 --run-time=5m

Or with more users for stress testing:
    locust -f tests/load/locustfile.py --host=http://localhost:8000 --users=20 --spawn-rate=5 --run-time=5m
"""

import random
import time
from locust import HttpUser, task, between, events
from datetime import datetime, timedelta


class ECELoadTestUser(HttpUser):
    """Simulates a user submitting prediction and simulation requests."""

    # Time between requests (1-3 seconds)
    wait_time = between(1, 3)

    # Track request metrics
    request_count = 0
    error_count = 0
    success_count = 0
    job_ids = []

    @task(3)
    def submit_prediction(self):
        """Task: Submit a prediction request (3x weight)."""
        try:
            # Generate random data
            building_id = f"building-{random.randint(1, 10):03d}"
            space_id = f"space-{random.randint(1, 50):03d}"
            start_date = (datetime.now() - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d")
            end_date = (datetime.now() - timedelta(days=random.randint(0, 5))).strftime("%Y-%m-%d")
            model_type = random.choice(["lightgbm", "xgboost", "catboost", "neural_network"])

            request_data = {
                "building_id": building_id,
                "space_id": space_id,
                "date_range": {
                    "start": start_date,
                    "end": end_date
                },
                "model_type": model_type
            }

            # Submit prediction request
            response = self.client.post(
                "/api/v1/predict",
                json=request_data,
                name="/api/v1/predict"
            )

            # Track metrics
            self.request_count += 1
            if response.status_code == 202:
                self.success_count += 1
                # Store job ID for status checking
                try:
                    job_id = response.json().get("job_id")
                    if job_id:
                        self.job_ids.append(job_id)
                except:
                    pass
            else:
                self.error_count += 1

        except Exception as e:
            self.error_count += 1

    @task(2)
    def submit_simulation(self):
        """Task: Submit a simulation request (2x weight)."""
        try:
            # Generate random data
            building_id = f"building-{random.randint(1, 10):03d}"
            ifc_file_id = f"ifc-{random.randint(1, 20):03d}"
            weather_data_id = f"weather-{random.randint(1, 15):03d}"
            simulation_days = random.randint(30, 365)

            request_data = {
                "building_id": building_id,
                "ifc_file_id": ifc_file_id,
                "weather_data_id": weather_data_id,
                "parameters": {
                    "simulation_days": simulation_days,
                    "timestep": 60
                }
            }

            # Submit simulation request
            response = self.client.post(
                "/api/v1/simulate",
                json=request_data,
                name="/api/v1/simulate"
            )

            # Track metrics
            self.request_count += 1
            if response.status_code == 202:
                self.success_count += 1
                # Store job ID for status checking
                try:
                    job_id = response.json().get("job_id")
                    if job_id:
                        self.job_ids.append(job_id)
                except:
                    pass
            else:
                self.error_count += 1

        except Exception as e:
            self.error_count += 1

    @task(4)
    def check_job_status(self):
        """Task: Check status of existing jobs (4x weight)."""
        try:
            # Check status of random job if we have any
            if self.job_ids:
                job_id = random.choice(self.job_ids)
                response = self.client.get(
                    f"/api/v1/status/{job_id}",
                    name="/api/v1/status/[job_id]"
                )

                # Track metrics
                self.request_count += 1
                if response.status_code == 200:
                    self.success_count += 1
                elif response.status_code == 404:
                    # Job not found (may have been cleaned up)
                    self.success_count += 1
                else:
                    self.error_count += 1

        except Exception as e:
            self.error_count += 1

    @task(1)
    def check_health(self):
        """Task: Check API health (1x weight)."""
        try:
            response = self.client.get(
                "/health",
                name="/health"
            )

            # Track metrics
            self.request_count += 1
            if response.status_code == 200:
                self.success_count += 1
            else:
                self.error_count += 1

        except Exception as e:
            self.error_count += 1

    @task(2)
    def retrieve_results(self):
        """Task: Try to retrieve results from completed jobs (2x weight)."""
        try:
            # Try to get results from random job
            if self.job_ids and len(self.job_ids) > 5:
                # Pick older job that might be completed
                job_id = random.choice(self.job_ids[:len(self.job_ids)//2])
                response = self.client.get(
                    f"/api/v1/results/{job_id}",
                    name="/api/v1/results/[job_id]",
                    catch_response=True
                )

                # Track metrics
                self.request_count += 1
                if response.status_code == 200:
                    self.success_count += 1
                elif response.status_code == 400:
                    # Job not completed yet (expected)
                    self.success_count += 1
                elif response.status_code == 404:
                    # Job not found (may have been cleaned up)
                    self.success_count += 1
                else:
                    self.error_count += 1

        except Exception as e:
            self.error_count += 1


# =====================================================================
# Load Test Event Handlers
# =====================================================================

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when test starts."""
    print("\n" + "="*70)
    print("ECE Load Test Starting")
    print("="*70)
    print(f"Target: {environment.host}")
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Called when test stops."""
    print("\n" + "="*70)
    print("ECE Load Test Summary")
    print("="*70)

    # Calculate statistics
    total_requests = environment.stats.total.num_requests
    total_failures = environment.stats.total.num_failures
    total_success = total_requests - total_failures
    success_rate = (total_success / total_requests * 100) if total_requests > 0 else 0

    print(f"Total Requests: {total_requests}")
    print(f"Successful: {total_success}")
    print(f"Failed: {total_failures}")
    print(f"Success Rate: {success_rate:.2f}%")
    print(f"\nResponse Times:")
    print(f"  Min: {environment.stats.total.min_response_time:.0f} ms")
    print(f"  Max: {environment.stats.total.max_response_time:.0f} ms")
    print(f"  Mean: {environment.stats.total.avg_response_time:.0f} ms")
    print(f"  P50: {environment.stats.total.get_response_time_percentile(0.5):.0f} ms")
    print(f"  P95: {environment.stats.total.get_response_time_percentile(0.95):.0f} ms")
    print(f"  P99: {environment.stats.total.get_response_time_percentile(0.99):.0f} ms")

    # Print endpoint statistics
    print(f"\nEndpoint Breakdown:")
    for name, stats in sorted(environment.stats.entries.items()):
        if stats.num_requests > 0:
            success_rate = ((stats.num_requests - stats.num_failures) / stats.num_requests * 100)
            print(f"\n  {name}")
            print(f"    Requests: {stats.num_requests}")
            print(f"    Failures: {stats.num_failures}")
            print(f"    Success Rate: {success_rate:.2f}%")
            print(f"    Mean Response: {stats.avg_response_time:.0f} ms")
            print(f"    Min Response: {stats.min_response_time:.0f} ms")
            print(f"    Max Response: {stats.max_response_time:.0f} ms")
            print(f"    P95 Response: {stats.get_response_time_percentile(0.95):.0f} ms")

    print("\n" + "="*70)
    print(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, response, context, exception, **kwargs):
    """Called for each request."""
    if exception:
        print(f"ERROR: {request_type} {name} - {exception}")


# =====================================================================
# Load Test Scenarios
# =====================================================================

"""
Load Test Scenarios:

1. Basic Load Test (6 users):
   locust -f tests/load/locustfile.py --host=http://localhost:8000 \\
     --users=6 --spawn-rate=1 --run-time=5m

2. Standard Load Test (15 users):
   locust -f tests/load/locustfile.py --host=http://localhost:8000 \\
     --users=15 --spawn-rate=2 --run-time=5m

3. Stress Test (30+ users):
   locust -f tests/load/locustfile.py --host=http://localhost:8000 \\
     --users=30 --spawn-rate=5 --run-time=10m

4. Web UI (interactive):
   locust -f tests/load/locustfile.py --host=http://localhost:8000

5. Headless with custom settings:
   locust -f tests/load/locustfile.py --host=http://localhost:8000 \\
     --users=6 --spawn-rate=2 --run-time=5m --headless

Expected Performance Metrics:
  - Response Time: < 500ms for predictions, < 2000ms for simulations
  - Success Rate: > 99% for all requests
  - P95 Response Time: < 1000ms for predictions
  - Error Rate: < 1%
"""
