# ECE Deployment Guide

This guide covers deploying the Energy Comfortness Estimation (ECE) system in three deployment scenarios:
1. Local development with docker-compose
2. Single-machine production
3. Cloud deployment with Kubernetes

## Architecture Overview

The ECE system consists of:
- **FastAPI Backend**: REST API for job submission and management
- **Celery Workers**: Async task processing for predictions and simulations
- **PostgreSQL Database**: Job tracking and results storage
- **Redis**: Message broker for Celery task queue

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │
       ▼
┌─────────────────────────┐
│   FastAPI Backend       │ ─────────────┐
│   (1-N replicas)        │              │
└────────┬────────────────┘              │
         │                               │
         ▼                               ▼
    ┌────────────┐              ┌──────────────┐
    │   Redis    │◄────────────►│   PostgreSQL │
    │   Queue    │              │   Database   │
    └────────────┘              └──────────────┘
         ▲
         │
    ┌────┴──────────────────┐
    │ Celery Workers         │
    │ (1-N instances)        │
    │ - Predict tasks        │
    │ - Simulate tasks       │
    └───────────────────────┘
```

---

## 1. Local Development Setup

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Git
- ~8GB RAM
- ~20GB disk space

### Installation Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/ispingos/energy_comfortness_tool.git
   cd energy_comfortness_tool
   ```

2. **Setup environment variables**
   ```bash
   cp .env.template .env
   # Edit .env for local development
   ```

3. **Start services with docker-compose**
   ```bash
   docker-compose up -d
   ```

   This starts:
   - PostgreSQL database (port 5432)
   - Redis cache/queue (port 6379)
   - API backend (port 8000)

4. **Create virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

5. **Initialize database**
   ```bash
   # Apply migrations (if using Alembic)
   alembic upgrade head
   ```

6. **Start Celery worker locally**
   ```bash
   celery -A backend.queue worker -l info -c 2
   ```

7. **Run the dashboard**
   ```bash
   streamlit run dashboard/app.py
   ```

### Verify Installation

Test the API health endpoint:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "healthy"}
```

### Run Tests

```bash
# Unit tests
pytest tests/backend/test_api.py -v

# Integration tests
pytest tests/integration/test_job_lifecycle.py -v

# Load testing (requires running API)
locust -f tests/load/locustfile.py --host=http://localhost:8000 --users=6 --run-time=5m
```

---

## 2. Single-Machine Production Deployment

### Prerequisites
- Ubuntu 20.04 LTS or similar
- Python 3.11
- PostgreSQL 13+
- Redis 6.0+
- ~16GB RAM
- ~100GB disk space (for data/logs)
- Domain name (optional, for HTTPS)

### Installation Steps

1. **Update system**
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

2. **Install dependencies**
   ```bash
   sudo apt install -y python3.11 python3.11-venv postgresql postgresql-contrib redis-server nginx supervisor
   ```

3. **Clone and setup application**
   ```bash
   cd /opt
   sudo git clone https://github.com/ispingos/energy_comfortness_tool.git
   cd energy_comfortness_tool
   sudo python3.11 -m venv venv
   source venv/bin/activate
   sudo pip install -r requirements.txt
   ```

4. **Configure PostgreSQL**
   ```bash
   sudo -u postgres psql
   CREATE DATABASE ece_production;
   CREATE USER ece_user WITH PASSWORD 'secure_password_here';
   GRANT ALL PRIVILEGES ON DATABASE ece_production TO ece_user;
   \q
   ```

5. **Create environment file**
   ```bash
   sudo cp .env.template /etc/ece/.env
   sudo chown root:root /etc/ece/.env
   sudo chmod 600 /etc/ece/.env
   # Edit with production values
   ```

   Key variables:
   ```
   DATABASE_URL=postgresql://ece_user:secure_password@localhost:5432/ece_production
   REDIS_URL=redis://localhost:6379/0
   API_HOST=0.0.0.0
   API_PORT=8000
   CELERY_BROKER_URL=redis://localhost:6379/0
   CELERY_RESULT_BACKEND=redis://localhost:6379/0
   ```

6. **Configure Supervisor for auto-start**
   
   Create `/etc/supervisor/conf.d/ece-api.conf`:
   ```ini
   [program:ece-api]
   command=/opt/energy_comfortness_tool/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
   directory=/opt/energy_comfortness_tool
   user=www-data
   autostart=true
   autorestart=true
   stderr_logfile=/var/log/ece/api.err.log
   stdout_logfile=/var/log/ece/api.out.log
   environment=PATH="/opt/energy_comfortness_tool/venv/bin",HOME="/opt/energy_comfortness_tool"
   ```

   Create `/etc/supervisor/conf.d/ece-worker.conf`:
   ```ini
   [program:ece-worker]
   command=/opt/energy_comfortness_tool/venv/bin/celery -A backend.queue worker -l info -c 4
   directory=/opt/energy_comfortness_tool
   user=www-data
   autostart=true
   autorestart=true
   numprocs=2
   process_name=%(program_name)s_%(process_num)d
   stderr_logfile=/var/log/ece/worker%(process_num)d.err.log
   stdout_logfile=/var/log/ece/worker%(process_num)d.out.log
   environment=PATH="/opt/energy_comfortness_tool/venv/bin",HOME="/opt/energy_comfortness_tool"
   ```

7. **Configure Nginx reverse proxy**
   
   Create `/etc/nginx/sites-available/ece`:
   ```nginx
   upstream ece_api {
       server 127.0.0.1:8000;
   }

   server {
       listen 80;
       server_name your-domain.com;

       # Redirect HTTP to HTTPS (optional)
       return 301 https://$server_name$request_uri;
   }

   server {
       listen 443 ssl http2;
       server_name your-domain.com;

       ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

       client_max_body_size 100M;

       location / {
           proxy_pass http://ece_api;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

   Enable the site:
   ```bash
   sudo ln -s /etc/nginx/sites-available/ece /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

8. **Start services**
   ```bash
   sudo mkdir -p /var/log/ece
   sudo chown www-data:www-data /var/log/ece
   sudo supervisorctl reread
   sudo supervisorctl update
   sudo supervisorctl start ece-api ece-worker:*
   ```

### Monitoring

Monitor service status:
```bash
sudo supervisorctl status
```

View logs:
```bash
sudo tail -f /var/log/ece/api.out.log
sudo tail -f /var/log/ece/worker0.out.log
```

Health check:
```bash
curl https://your-domain.com/health
```

---

## 3. Cloud Deployment with Kubernetes

### Prerequisites
- Kubernetes cluster (1.21+)
- kubectl configured
- Docker registry (Docker Hub, ECR, GCR, etc.)
- Helm 3+ (optional but recommended)

### Build Docker Images

1. **Build API image**
   ```bash
   docker build -f Dockerfile.backend -t your-registry/ece-api:latest .
   docker push your-registry/ece-api:latest
   ```

2. **Build Worker image**
   ```bash
   docker build -f Dockerfile.worker -t your-registry/ece-worker:latest .
   docker push your-registry/ece-worker:latest
   ```

### Deploy with Kubernetes

1. **Create namespace**
   ```bash
   kubectl create namespace ece-production
   ```

2. **Create ConfigMap and Secrets**
   ```bash
   kubectl create configmap ece-config \
     --from-literal=API_HOST=0.0.0.0 \
     --from-literal=API_PORT=8000 \
     -n ece-production

   kubectl create secret generic ece-secrets \
     --from-literal=DATABASE_URL=postgresql://user:pass@postgres:5432/ece \
     --from-literal=REDIS_URL=redis://redis:6379/0 \
     -n ece-production
   ```

3. **Deploy PostgreSQL (using Helm)**
   ```bash
   helm repo add bitnami https://charts.bitnami.com/bitnami
   helm install postgres bitnami/postgresql \
     --set auth.username=ece_user \
     --set auth.password=secure_password \
     --set auth.database=ece \
     -n ece-production
   ```

4. **Deploy Redis (using Helm)**
   ```bash
   helm install redis bitnami/redis \
     --set auth.enabled=false \
     -n ece-production
   ```

5. **Create Kubernetes Deployment manifests**

   `k8s/api-deployment.yaml`:
   ```yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: ece-api
     namespace: ece-production
   spec:
     replicas: 3
     selector:
       matchLabels:
         app: ece-api
     template:
       metadata:
         labels:
           app: ece-api
       spec:
         containers:
         - name: api
           image: your-registry/ece-api:latest
           ports:
           - containerPort: 8000
           env:
           - name: DATABASE_URL
             valueFrom:
               secretKeyRef:
                 name: ece-secrets
                 key: DATABASE_URL
           - name: REDIS_URL
             valueFrom:
               secretKeyRef:
                 name: ece-secrets
                 key: REDIS_URL
           resources:
             requests:
               memory: "512Mi"
               cpu: "250m"
             limits:
               memory: "1Gi"
               cpu: "500m"
           livenessProbe:
             httpGet:
               path: /health
               port: 8000
             initialDelaySeconds: 10
             periodSeconds: 10
           readinessProbe:
             httpGet:
               path: /health
               port: 8000
             initialDelaySeconds: 5
             periodSeconds: 5
   ---
   apiVersion: v1
   kind: Service
   metadata:
     name: ece-api-service
     namespace: ece-production
   spec:
     selector:
       app: ece-api
     ports:
     - protocol: TCP
       port: 80
       targetPort: 8000
     type: LoadBalancer
   ```

   `k8s/worker-deployment.yaml`:
   ```yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: ece-worker
     namespace: ece-production
   spec:
     replicas: 3
     selector:
       matchLabels:
         app: ece-worker
     template:
       metadata:
         labels:
           app: ece-worker
       spec:
         containers:
         - name: worker
           image: your-registry/ece-worker:latest
           env:
           - name: DATABASE_URL
             valueFrom:
               secretKeyRef:
                 name: ece-secrets
                 key: DATABASE_URL
           - name: REDIS_URL
             valueFrom:
               secretKeyRef:
                 name: ece-secrets
                 key: REDIS_URL
           resources:
             requests:
               memory: "1Gi"
               cpu: "500m"
             limits:
               memory: "2Gi"
               cpu: "1000m"
   ```

6. **Deploy to Kubernetes**
   ```bash
   kubectl apply -f k8s/api-deployment.yaml
   kubectl apply -f k8s/worker-deployment.yaml
   ```

7. **Verify deployment**
   ```bash
   kubectl get pods -n ece-production
   kubectl logs -f deployment/ece-api -n ece-production
   kubectl get svc -n ece-production
   ```

### Scaling

Scale API replicas:
```bash
kubectl scale deployment/ece-api --replicas=5 -n ece-production
```

Scale Workers:
```bash
kubectl scale deployment/ece-worker --replicas=10 -n ece-production
```

### Monitoring (Kubernetes)

Setup Prometheus and Grafana:
```bash
helm install prometheus prometheus-community/kube-prometheus-stack \
  -n ece-production
```

Port forward to Grafana:
```bash
kubectl port-forward -n ece-production svc/prometheus-grafana 3000:80
```

---

## Performance Tuning

### API Configuration
- **Workers**: 4 per CPU core (from Gunicorn/Uvicorn)
- **Max Connections**: 100 per API instance
- **Request Timeout**: 30s for predictions, 120s for simulations

### Database Configuration
- **Connection Pool**: 20 connections per API instance
- **Query Timeout**: 60 seconds
- **Cache**: Redis for caching job results

### Celery Configuration
- **Worker Concurrency**: 4 per instance (adjustable)
- **Task Time Limit**: 3600s for predictions, 7200s for simulations
- **Prefetch Multiplier**: 4 tasks per worker

### Load Test Results (Expected)
- **Throughput**: 100+ requests/second with 10 API + 10 Worker instances
- **P95 Latency**: <500ms for predictions
- **Success Rate**: >99%
- **Max Concurrent Jobs**: 1000+

---

## Backup and Recovery

### Database Backup
```bash
# Create backup
pg_dump -U ece_user -h localhost ece_production > backup.sql

# Restore backup
psql -U ece_user -h localhost ece_production < backup.sql
```

### Redis Backup
```bash
# Create snapshot
redis-cli BGSAVE

# List snapshots
ls /var/lib/redis/dump.rdb
```

---

## Security Considerations

1. **Use HTTPS** with valid SSL certificates
2. **Enable CORS** only for trusted origins
3. **Use strong passwords** for database and Redis
4. **Implement rate limiting** at API gateway level
5. **Setup VPN** for access to production services
6. **Regular security audits** and dependency updates
7. **Log and monitor** all API requests
8. **Use secrets management** (AWS Secrets Manager, Vault, etc.)

---

## Troubleshooting

### API not responding
```bash
# Check if API is running
curl http://localhost:8000/health

# Check logs
tail -f /var/log/ece/api.out.log
```

### Jobs not processing
```bash
# Check Celery workers
celery -A backend.queue inspect active

# Check Redis connection
redis-cli PING
```

### Database connection issues
```bash
# Test PostgreSQL connection
psql -U ece_user -h localhost -d ece_production -c "SELECT 1"
```

### High memory usage
- Reduce Celery worker concurrency: `celery -A backend.queue worker -c 2`
- Reduce API worker count: `uvicorn backend.main:app --workers 2`

---

## Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Celery Documentation](https://docs.celeryproject.org/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Redis Documentation](https://redis.io/documentation)
- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [Docker Documentation](https://docs.docker.com/)

---

**Last Updated**: 2024-08-03
