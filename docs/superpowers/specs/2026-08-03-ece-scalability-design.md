# ECE Scalability Redesign: Proper Architecture for Concurrent Users

**Date:** 2026-08-03  
**Status:** Design Phase  
**Goal:** Enable the Energy Comfortness Tool (ECT) to handle 6+ concurrent users without UI blocking, excessive reruns, or database lock contention.

---

## Problem Statement

The current ECT architecture tightly couples the Streamlit dashboard (`dashboard/app.py`) with the ECE (Energy Comfortness Engine) backend. This creates scalability bottlenecks:

- **UI Blocking:** Long-running predictions and EnergyPlus simulations freeze the dashboard
- **Excessive Reruns:** Streamlit reruns the entire script on every interaction, causing multiple concurrent users to interfere with each other
- **Database Contention:** Concurrent queries and writes cause locking issues
- **No Job Queue:** Predictions/simulations run inline; adding capacity requires more Streamlit instances (wasteful)

**Current behavior with 6 concurrent users:**
- Multiple reruns looping (users triggering script reruns simultaneously)
- Simulations block the UI for all users on the same Streamlit instance
- Database connections exhaust under concurrent load
- No way to monitor job progress or prioritize critical tasks

---

## Proposed Solution: FastAPI Backend + Stateless Streamlit + Job Queue

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                  Load Balancer (nginx/HAProxy)              │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   ┌────▼────┐          ┌────▼────┐          ┌────▼────┐
   │Streamlit│          │Streamlit│          │Streamlit│
   │Frontend │          │Frontend │          │Frontend │
   │Instance1│          │Instance2│          │Instance3│
   └────┬────┘          └────┬────┘          └────┬────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │ (HTTP/WebSocket API calls)
                              ▼
                  ┌──────────────────────────┐
                  │   FastAPI Backend        │
                  │  - /predict              │
                  │  - /simulate             │
                  │  - /status/<job_id>      │
                  │  - /cancel/<job_id>      │
                  │  - /health               │
                  └──────┬───────────┬───────┘
                         │           │
         ┌───────────────┼───────────┼───────────────┐
         │               │           │               │
    ┌────▼────┐      ┌───▼────┐ ┌──▼────┐      ┌───▼──────┐
    │  Redis  │      │ Job DB │ │Result │      │ PostgreSQL│
    │  Queue  │      │Records │ │ Cache │      │  Database │
    │(Celery) │      └────────┘ └──────┘      └───────────┘
    └────┬────┘
         │ (Pull jobs)
    ┌────▼──────────────────────────────────────┐
    │         Worker Processes (Horizontal Scaling)
    │  ┌──────────┐  ┌──────────┐  ┌──────────┐
    │  │ Worker 1 │  │ Worker 2 │  │ Worker 3 │
    │  │(ECE ML)  │  │(EnergyPl)│  │(Weather) │
    │  └──────────┘  └──────────┘  └──────────┘
    │  (Can add N workers as needed)
    └───────────────────────────────────────────┘
```

### Key Components

#### 1. **FastAPI Backend**
Replaces direct ECE calls from Streamlit. Exposes RESTful/WebSocket APIs:

- `POST /predict` — Queue a comfort prediction job
  - Input: `building_id`, `space_id`, `date_range`, `model_type`
  - Output: `job_id`, `estimated_wait_time`
  
- `POST /simulate` — Queue an EnergyPlus simulation
  - Input: `building_id`, `ifc_file_id`, `weather_data_id`, `parameters`
  - Output: `job_id`
  
- `GET /status/<job_id>` — Poll job progress
  - Output: `status` (queued|running|completed|failed), `progress` (%), `result_url`
  
- `GET /results/<job_id>` — Retrieve completed results
  - Output: Prediction/simulation data (same format as before)
  
- `DELETE /cancel/<job_id>` — Cancel a running job
  
- `GET /health` — Health check for load balancer
  
**Technology:** FastAPI (async, fast, built-in validation)  
**Authentication:** JWT tokens per user (or inherit from Streamlit session)

#### 2. **Job Queue (Redis + Celery or RQ)**
Decouples API request from computation:

- Redis stores job queue and job metadata
- Celery workers consume jobs asynchronously
- Supports priorities (high-priority predictions skip the queue)
- Automatic retry logic (3 attempts with exponential backoff)
- Job timeout (kill workers stuck > 1 hour)

**Why Redis:** Lightweight, fast, widely used for job queues

#### 3. **Worker Processes**
Execute actual ECE pipelines in parallel:

- Each worker processes one job at a time
- Workers pull from the same Redis queue
- Run ECE pipelines: `pipeline_ml.py`, `pipeline_eplus_wrapper.py`, `pipeline_weather.py`
- Write results to PostgreSQL
- Report progress every N seconds (for WebSocket updates)

**Scaling:** Add/remove workers independently from Streamlit; 6 concurrent users typically need 3-4 workers

#### 4. **Streamlit Frontend (Refactored)**
Becomes a stateless UI client:

- Remove all ECE computation (model training, simulations, etc.)
- Replace with API calls to FastAPI backend
- Add job submission forms: build prediction/simulation request, get `job_id`
- Add job monitor: poll `/status/{job_id}`, show progress bar
- Add results display: fetch from `/results/{job_id}` when ready
- Add job history: list recent jobs with status

**Key change:** Streamlit is now read-only for long computations (no blocking)

#### 5. **PostgreSQL Database**
Shared data store for all components:

- Existing tables: buildings, spaces, sensor_data, predictions, models, etc.
- New tables: `jobs` (job metadata, status, timestamps, user_id)
- Connection pooling (PgBouncer or SQLAlchemy pool) to handle concurrent workers

---

## Data Flow & Job Lifecycle

### Scenario: User Submits Prediction Request

```
1. Streamlit UI:
   - User selects building, date range, model type
   - Clicks "Predict Comfort"
   
2. Streamlit → FastAPI:
   - POST /predict {building_id, space_id, date_range, model_type}
   - Receives: {job_id: "job_abc123", status: "queued"}
   
3. FastAPI:
   - Validates input
   - Creates job record: {id, status="queued", user_id, created_at, etc.}
   - Serializes job as message: {job_id, params, pipeline_type="ml_predict"}
   - Pushes to Redis queue
   - Returns job_id to Streamlit
   
4. Streamlit:
   - Shows "Job submitted! ID: job_abc123"
   - Starts polling: GET /status/job_abc123 every 3 seconds
   - Displays progress bar (% complete from worker updates)
   
5. Worker (Celery):
   - Dequeues job from Redis
   - Updates DB: status="running"
   - Calls ECE pipeline: pipeline_ml.predict(...)
   - Every 10% progress, writes to Redis: {job_id, progress: 40}
   - Writes results to DB: predictions table
   - Updates DB: status="completed", result_table_id, completed_at
   
6. Streamlit:
   - Polls and sees status="completed"
   - Calls GET /results/job_abc123
   - Fetches predictions from DB
   - Displays charts (same as before)
   
7. Success!
   - User sees results without ever blocking
   - Other concurrent users unaffected
```

### Scaling Benefit

- Multiple workers process jobs in parallel (3 predictions running simultaneously)
- Multiple Streamlit instances submit jobs independently
- Database handles concurrent reads/writes via pooling
- No blocking; UI responsive for all users

---

## Scalability Strategy

### Horizontal Scaling (Adding Capacity)

**For 6 concurrent users:**
- **Streamlit:** 2-3 instances (each can handle multiple users browsing results)
- **Workers:** 3-4 instances (CPU-bound; assume 2-3 predictions/simulations per worker concurrently)
- **Redis:** 1 instance (sufficient for job queue; can upgrade to cluster later)
- **PostgreSQL:** 1 instance (or managed RDS; connection pool handles load)

**Load Balancer (nginx):**
```nginx
upstream streamlit_backend {
    server streamlit1:8501;
    server streamlit2:8501;
    server streamlit3:8501;
}

server {
    listen 80;
    location / {
        proxy_pass http://streamlit_backend;
    }
}
```

**Worker Auto-Scaling (Kubernetes example):**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ece-workers
spec:
  replicas: 3  # Can scale up/down based on queue length
  template:
    spec:
      containers:
      - name: worker
        image: ece-worker:latest
        env:
        - name: REDIS_URL
          value: redis://redis-service:6379
```

### Deployment Scenarios

**Local Development:**
- Docker Compose: 1 Streamlit + 1 FastAPI + 1 Redis + 1 PostgreSQL + 1 Worker
- Quick testing without infrastructure overhead

**Single-Machine Production:**
- Docker Compose on a beefy server (16+ CPU cores, 32GB+ RAM)
- Streamlit, FastAPI, Workers in separate containers

**Cloud (AWS/GCP/Azure):**
- Kubernetes cluster: auto-scale workers based on queue depth
- Managed Redis (ElastiCache, Cloud Memorystore)
- Managed PostgreSQL (RDS, Cloud SQL)
- Streamlit on App Runner / Cloud Run
- True unlimited scaling

---

## Error Handling & Monitoring

### Job Failure Recovery

**Worker Crash:**
- Job status remains "running" with a timeout watch
- If worker doesn't report within 60s, job is reassigned to another worker
- Max retries: 3 (configurable)
- On final failure: status="failed", error_message stored in DB

**Database Connection Lost:**
- Retry logic with exponential backoff (1s, 2s, 4s, 8s)
- If still unavailable after 30s, mark job as "failed"
- Streamlit shows error and offers manual retry

**Invalid Input:**
- FastAPI validation rejects before queueing
- Streamlit shows validation error immediately (no queue wait)

### Monitoring & Observability

**Key Metrics:**
- Job success rate (%)
- Average job duration (seconds)
- Queue depth (pending jobs)
- Worker utilization (jobs in progress / worker count)
- Database connection pool usage
- Error rate by type (validation, timeout, crash, etc.)

**Logging:**
- Each job logs: start, progress checkpoints, completion/failure, duration
- Workers log: job picked up, pipeline stages, errors
- FastAPI logs: request/response, validation errors
- PostgreSQL slow queries logged (> 1s)

**Alerting (Optional):**
- Alert if queue depth > 10 (workers overloaded)
- Alert if error rate > 5% (systemic issue)
- Alert if worker crashes > 2 in 5min

---

## Testing Strategy

### Unit Tests
- ECE pipeline functions in isolation (no DB/API)
- Example: `test_pipeline_ml_handles_missing_sensor_data()`
- Example: `test_feature_engineering_produces_valid_features()`

### API Tests
- FastAPI endpoints with mock job queue
- Example: `test_predict_endpoint_returns_job_id()`
- Example: `test_invalid_input_rejected_before_queueing()`
- Example: `test_status_endpoint_returns_correct_progress()`

### Integration Tests
- Full job lifecycle: Streamlit → FastAPI → Queue → Worker → DB → Results
- Spin up test Redis + PostgreSQL containers
- Example: `test_prediction_job_end_to_end()`
- Example: `test_multiple_concurrent_jobs_complete_independently()`

### Load Tests
- Simulate 6+ concurrent Streamlit users
- Each submits 2-3 jobs (predictions, simulations)
- Verify:
  - All jobs complete correctly
  - No data corruption
  - Worker CPU/memory reasonable
  - Database connections don't exhaust
- Tools: `locust` (Python, Streamlit-friendly), `k6`

### Manual/UI Tests
- Streamlit UI against local FastAPI
- Verify job submission works
- Verify progress bar updates in real-time
- Verify results display correctly
- Verify error messages are helpful

---

## Implementation Phases

### Phase 1: Backend Foundation (Week 1-2)
- Create FastAPI application with endpoints
- Set up Redis + Celery worker infrastructure
- Create `jobs` table in PostgreSQL
- Refactor ECE pipelines to be worker-friendly (no Streamlit dependencies)

### Phase 2: Streamlit Integration (Week 2-3)
- Refactor `dashboard/app.py` to call FastAPI instead of running ECE directly
- Add job submission UI
- Add job progress monitoring
- Add results display

### Phase 3: Testing & Deployment (Week 3-4)
- Write integration/load tests
- Docker Compose setup
- Deploy to staging
- Performance testing with 6+ concurrent users
- Deploy to production

---

## Success Criteria

✅ **6 concurrent users can submit predictions/simulations without UI blocking**  
✅ **Jobs complete in < 10% longer than before (acceptable overhead for scalability)**  
✅ **Job queue never exceeds 5 jobs (workers keep up)**  
✅ **Database connections don't exhaust under concurrent load**  
✅ **Easy to add workers by spinning up new containers**  
✅ **All existing functionality preserved (same predictions, same accuracy)**  
✅ **No data loss or corruption under load**  

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Redis single point of failure | Use Redis Sentinel or Cluster in production |
| Database connection limits | Use PgBouncer connection pooling; scale RDS if needed |
| Worker crashes lose jobs | Implement heartbeat + job reassignment logic |
| Streamlit session loss | Store progress in DB; user can refresh and poll existing job |
| Slow network to FastAPI | WebSocket for real-time progress instead of polling |

---

## Backwards Compatibility

- Existing ECE modules (`pipeline_ml.py`, `pipeline_eplus_wrapper.py`, etc.) remain unchanged
- Existing database schema extended (new `jobs` table only)
- Existing models/predictions unaffected
- Streamlit UI behavior identical from user perspective (just faster, no blocking)

---

## Open Questions / Future Enhancements

1. **Authentication:** How should we handle user isolation in the queue? (Each user queues their own jobs?)
2. **Result Caching:** Should identical requests share results to save computation?
3. **Priority Queuing:** Should certain users (e.g., admins) get higher priority?
4. **WebSocket Progress:** Use WebSocket instead of polling for real-time updates?
5. **Cost Optimization:** Auto-scale workers down during off-peak hours?
