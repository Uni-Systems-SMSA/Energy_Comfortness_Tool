# Task 5 Implementation Report: POST /simulate Endpoint with Celery Async EnergyPlus Simulations

**Date:** August 3, 2026  
**Task:** Implement Task 5 of ECE Scalability Plan  
**Status:** COMPLETED

## Overview

Task 5 implements the simulation API endpoint that users will call to submit EnergyPlus simulations. The endpoint accepts simulation requests, queues them to Celery, and returns a job_id for asynchronous processing. This follows the same pattern established by Task 4 (/predict endpoint) but with simulation-specific configuration.

## Files Created

### 1. `backend/api/simulate.py` (262 lines)
Simulation endpoint and Celery task implementation.

**Endpoint: POST /simulate**
- Path: `/api/v1/simulate`
- Status Code: 202 Accepted (async operation)
- Tags: ["simulate"]

**Request Model: SimulateRequest**
- building_id (str, required): Identifier for the building
- ifc_file_id (str, required): Identifier for the IFC file
- weather_data_id (str, required): Identifier for the weather data
- parameters (dict, optional): Simulation parameters

**Response Model: JobSubmissionResponse**
- job_id (str): Unique job identifier
- status (JobStatus): Initial status ("pending")
- estimated_wait_time_seconds (int): Estimated wait time

**Endpoint Logic:**
1. Validate input:
   - Ensures building_id is provided
   - Ensures ifc_file_id is provided
   - Ensures weather_data_id is provided
   - Parameters is optional (defaults to empty dict)
2. Create job record in DB:
   - Calls `create_job(job_type="eplus_simulate", input_params={...})`
   - Returns job_id
3. Queue to Celery:
   - Uses `apply_async` with task_id=job_id
   - Priority: 3 (lower than predictions at 5)
   - Timeout: 7200 seconds (2 hours)
4. Return JobSubmissionResponse immediately (no blocking)

**Error Handling:**
- HTTP 400: Missing required building_id, ifc_file_id, or weather_data_id
- HTTP 422: Request validation failure
- HTTP 500: Database or Celery queue failure
- Updates job status to "failed" on queue error

**Celery Task: simulate_task**
- Name: "simulate_task"
- Configuration:
  - bind=True (for retry capability)
  - max_retries=3
  - time_limit=7200 seconds (2 hours)
  - acks_late=True
  - Exponential backoff on retry

**Task Parameters:**
- self: Celery task context
- job_id: Unique job identifier
- building_id: Building identifier for simulation
- ifc_file_id: IFC file identifier
- weather_data_id: Weather data identifier
- parameters: Simulation parameters dictionary

**Task Logic:**
1. Update job status to "running" (progress 10%)
2. Call EnergyPlus simulation pipeline (currently mocked, TODO: integrate ece.pipeline_eplus.simulate)
3. Update progress to 50%
4. Store results in database via `store_result()`
5. Update job status to "completed" (progress 100%)
6. On error:
   - Log error with full context
   - Update job status to "failed" with error_message
   - Retry with exponential backoff (max 3 times)
   - On max retries exceeded: final failure state

**Return Value:**
```json
{
  "job_id": "uuid-string",
  "status": "completed",
  "results": {
    "building_id": "building_001",
    "ifc_file_id": "ifc_001",
    "weather_data_id": "weather_001",
    "parameters": {...},
    "simulation_output": {...},
    "timestamp": "2026-08-03T..."
  }
}
```

## Files Modified

### 1. `backend/models.py`
Updated SimulateRequest model to match task requirements:

**Before:**
```python
class SimulateRequest(BaseModel):
    space_id: str
    parameters: Dict[str, Any]
    duration: int
    model_version: Optional[str]
```

**After:**
```python
class SimulateRequest(BaseModel):
    building_id: str
    ifc_file_id: str
    weather_data_id: str
    parameters: Optional[Dict[str, Any]]
```

### 2. `backend/main.py`
Added import and router registration for simulate endpoint:

**Changes:**
- Added import: `from backend.api import simulate`
- Added router: `app.include_router(simulate.router, prefix="/api/v1", tags=["simulate"])`
- Enabled POST /simulate endpoint on FastAPI app

## Configuration

### Priority & Timeout
- **Priority:** 3 (lower than predictions at 5)
  - Simulations are more resource-intensive and longer-running
  - Lower priority allows predictions to be prioritized
- **Timeout:** 7200 seconds (2 hours)
  - Simulations can take significant time
  - Provides sufficient time for complete simulation runs
- **Max Retries:** 3
  - Balances reliability against cascading failures
  - Exponential backoff: min(2^retry_count, 300) seconds

### Estimated Wait Time
- Currently hardcoded to 300 seconds (5 minutes) in response
- TODO: Calculate based on queue depth and estimated simulation duration

## Integration Requirements

**Depends on (already completed in Tasks 1-4):**
- ✓ Task 1: FastAPI backend setup (`backend/main.py`, `backend/config.py`)
- ✓ Task 2: Celery configuration (`backend/queue.py`)
- ✓ Task 3: Database setup (`db/models.py`, `db/session.py`, jobs migration)
- ✓ Task 4: Prediction endpoint (`backend/api/predict.py`)
- ✓ Pydantic models (`backend/models.py`): SimulateRequest, JobSubmissionResponse, JobStatus

**Database Support:**
- Uses existing Job ORM model from Task 3
- job_type field supports "eplus_simulate" value
- input_params and result_data fields store simulation data

## Implementation Notes

### Design Decisions

1. **Async Processing Pattern:**
   - Endpoint returns immediately with job_id
   - Client polls GET /jobs/{job_id} to check status
   - No blocking on the endpoint
   - Matches Task 4 pattern for consistency

2. **Priority Hierarchy:**
   - Predictions: Priority 5 (shorter, user-facing)
   - Simulations: Priority 3 (longer, background work)
   - Allows predictions to take precedence when both are queued

3. **Long Timeout:**
   - 7200 seconds (2 hours) provides ample time
   - Typical EnergyPlus simulations for full-year runs
   - Prevents premature task timeout

4. **Optional Parameters:**
   - Simulations can proceed with default parameters
   - Allows flexible simulation configuration
   - Empty dict used when parameters not provided

5. **Consistent Error Handling:**
   - Follows same pattern as Task 4
   - Comprehensive validation at endpoint
   - Job status marked as "failed" on any error
   - Celery task retries with exponential backoff
   - Error messages stored for debugging

### Code Quality

- **Logging:** All major operations logged with job_id context
- **Type Hints:** Full type hints for maintainability
- **Documentation:** Comprehensive docstrings
- **Error Handling:** Try-catch blocks with proper cleanup
- **Comments:** Inline TODOs marking integration points

### Future Enhancements (TODOs)

1. **EnergyPlus Pipeline Integration:**
   - Currently using mock simulation output
   - TODO: Replace with `from ece.pipeline_eplus import simulate` when available
   - Will call: `simulate(building_id=building_id, ifc_file_id=ifc_file_id, weather_data_id=weather_data_id, parameters=parameters)`

2. **User Tracking:**
   - Currently user_id=None in create_job
   - TODO: Extract from authentication context when auth implemented

3. **Estimated Wait Time:**
   - Currently hardcoded to 300 seconds
   - TODO: Calculate based on:
     - Queue depth: `len(get_jobs_by_status("queued"))`
     - Average simulation duration
     - Celery worker availability

4. **Progress Updates:**
   - Currently progress at 10% (start) and 50% (before store)
   - TODO: Add intermediate progress updates during long simulations
   - Could update every 10% of expected runtime

5. **Simulation Validation:**
   - TODO: Validate IFC file and weather data exist before queuing
   - TODO: Add simulation parameter validation

6. **Monitoring & Metrics:**
   - TODO: Add Prometheus metrics for:
     - Simulation task duration
     - Success/failure rates
     - Queue depth
     - Task retry counts
     - IFC file handling performance

## Verification Checklist

- [x] Created backend/api/simulate.py with endpoint and Celery task
- [x] Updated SimulateRequest model in backend/models.py
- [x] Endpoint accepts SimulateRequest with validation
- [x] Endpoint returns JobSubmissionResponse with job_id
- [x] Endpoint returns 202 Accepted status
- [x] Job record created in database with job_type="eplus_simulate"
- [x] Task queued to Celery with task_id=job_id
- [x] Priority set to 3 (lower than predictions)
- [x] Timeout set to 7200 seconds
- [x] Max retries set to 3
- [x] Celery task updates job status through lifecycle
- [x] Error handling with status updates
- [x] Retry logic with exponential backoff
- [x] Router registered in backend/main.py
- [x] Code is syntactically valid Python
- [x] Follows same pattern as Task 4 for consistency

## Files Summary

### Created
- `backend/api/simulate.py` — 262 lines, endpoint + Celery task

### Modified
- `backend/models.py` — Updated SimulateRequest model (5 fields changed)
- `backend/main.py` — Added simulate router import and registration (2 lines)

### Test Files Created (not part of submission)
- `test_simulate_endpoint.py` — Integration tests for the endpoint

## Deployment Status

✓ Task 5 is complete and ready for integration
✓ Code follows established patterns from Task 4
✓ All required configurations applied
✓ Ready for integration with Tasks 6+ (status/results endpoints)

## Next Steps

1. Task 6: Implement GET /jobs/{job_id} and GET /jobs/{job_id}/results endpoints
2. Task 7: Implement job cancellation and cleanup
3. Task 8: Add monitoring and metrics collection
4. Integration: Connect to actual EnergyPlus pipeline when available
