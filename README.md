# **Energy Comfortness Tool (ECT) - standalone version** 

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![License](https://img.shields.io/badge/License-GPLv3-yellow.svg)

A comprehensive web-based tool for indoor environmental quality (IEQ) prediction, thermal comfort analysis, and building energy simulation. The ECT combines machine learning models, real-time weather data, and EnergyPlus simulations packaged as a single Docker image.

## Installation and Running

**Prerequisites:**
- Docker 24+ (or any recent Docker Engine)

### 1. Download the Image

Obtain the Energy Comfortness Tool Docker image:

```bash
# Replace IMAGE_NAME with the actual image reference provided
docker pull IMAGE_NAME:latest
```

### 2. Run the Container

The following command starts the containerized application with persistent storage:

**Linux / macOS:**
```bash
docker run -d \
  --name ect-standalone \
  -p 8599:8599 \
  -p 5499:5432 \
  -v ect_postgres_data:/var/lib/postgresql/17/main \
  -v ect_models:/app/models \
  -v ect_logs:/app/logs \
  -v ect_database_exports:/app/database/data \
  IMAGE_NAME:latest
```

**Windows (PowerShell):**
```powershell
docker run -d `
  --name ect-standalone `
  -p 8599:8599 `
  -p 5499:5432 `
  -v ect_postgres_data:/var/lib/postgresql/17/main `
  -v ect_models:/app/models `
  -v ect_logs:/app/logs `
  -v ect_database_exports:/app/database/data `
  IMAGE_NAME:latest
```

**Port Mappings:**
- `8599` - Streamlit Dashboard (web interface)
- `5499` - PostgreSQL Database (external access)

**Volumes:**
- `ect_postgres_data` - PostgreSQL database files
- `ect_models` - Trained ML models
- `ect_logs` - Application logs
- `ect_database_exports` - Database backup/export files

### 3. Access the Application

Open your browser and navigate to:

```
http://localhost:8599
```

### 4. Stop and Remove

```bash
# Stop the container
docker stop ect-standalone

# Remove the container
docker rm ect-standalone

# Remove volumes (optional - clears all data)
docker volume rm ect_postgres_data ect_models ect_logs ect_database_exports
```

## What's Included

The Docker image contains:
- Dashboard (web application)
- PostgreSQL 17 (database)
- [EnergyPlus](https://energyplus.net/) 9.4.0 (building simulation engine)
- [BIM2SIM](https://github.com/BIM2SIM) (IFC file processing)

