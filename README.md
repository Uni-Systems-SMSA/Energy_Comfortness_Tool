# **Energy Comfortness Tool (ECT) - Standalone Version** 

<img src="./ect/dashboard/assets/images/ect_access.png" alt="ECT Access" height="100">

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

## Support

For issues or questions, please contact the project maintainers or refer to the project repository.

---

**Note:** All configuration is embedded in the Docker image. No additional setup files are required.

# Energy Comfortness Tool - Technical Architecture

A comprehensive building performance analysis system for indoor environmental quality (IEQ) prediction and energy simulation using machine learning and EnergyPlus integration.

## **System Architecture**

### **High-Level Architecture**
```
┌─────────────────────────────────────────────────────────────┐
│                    ECT Ecosystem                            │
├─────────────────────────────────────────────────────────────┤
│  CSV Data Upload   │  IFC Models      │  Weather API        │
│  (Sensor Data)     │  (Building BIM)  │  (Open-Meteo)       │
└─────────────┬───────────────┬─────────────────┬─────────────┘
              │               │                 │
              ▼               ▼                 ▼
┌─────────────────────────────────────────────────────────────┐
│              Energy Comfortness Tool (ECT)                 │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ Streamlit   │  │ ECE Pipeline │  │ Energy Simulation   │ │
│  │ Dashboard   │◄─┤ (ML Engine)  │◄─┤ (BIM2Sim+EnergyPlus)│ │
│  └─────────────┘  └──────────────┘  └─────────────────────┘ │
│                   ┌──────────────┐  ┌─────────────────────┐ │
│                   │ PostgreSQL   │  │ Weather Pipeline    │ │
│                   │ Database     │  │ (EPW Generation)    │ │
│                   └──────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│           Multi-Domain Comfort Analytics Dashboard          │
│     (Thermal, Visual, Acoustic, IAQ, Energy Analysis)      │
└─────────────────────────────────────────────────────────────┘
```

## **Directory Structure**

```
energy-comfortness-tool/
├── Dockerfile                  # Container definition
├── docker-compose-app.yml      # Service orchestration
├── README.md                   # Project documentation
├── .env                        # Environment configuration
├── database/
│   ├── data/                   # PostgreSQL data files
│   └── exports/               # Database backup files
├── ect/
│   ├── dashboard/
│   │   ├── app.py             # Streamlit web application (5557 lines)
│   │   └── assets/            # Static assets and configuration
│   ├── db/
│   │   ├── models.py          # SQLAlchemy ORM models
│   │   └── session.py         # Database connection management
│   ├── ece/                   # Energy Comfortness Engine
│   │   ├── pipeline_ml.py     # ML training and prediction pipeline
│   │   ├── pipeline_weather.py # Weather data processing and EPW generation
│   │   ├── pipeline_eplus*.py # EnergyPlus simulation orchestration
│   │   ├── feature_map.py     # ML feature engineering configuration
│   │   ├── model_zoo.py       # ML algorithm implementations
│   │   ├── helpers.py         # Comfort calculation utilities
│   │   └── weather_api.py     # Open-Meteo API integration
│   ├── requirements.txt       # Python dependencies
│   └── __version__.py         # Version information
├── migrations/                 # Database schema migrations
├── tests/                      # Comprehensive test suite
├── scripts/                    # Utility and maintenance scripts
└── models/                     # Trained ML model artifacts
```

## **Component Architecture**

### **1. Dashboard Layer** (`ect/dashboard/app.py`)
- **Framework**: Streamlit with multi-tab interface
- **Tabs**: Thermal, Visual, Acoustic, IAQ, Energy, Energy Comfortness
- **Responsibilities**:
  - Interactive data visualization with Altair charts
  - Real-time comfort classification and scoring
  - Energy simulation workflow orchestration
  - CSV data upload and processing
  - IFC building model upload and validation
  - Multi-domain correlation analysis

### **2. ECE (Energy Comfortness Engine)**

#### **ML Pipeline** (`ece/pipeline_ml.py`)
- **Purpose**: Multi-target environmental parameter prediction
- **Algorithms**: 
  - LightGBM Regressor (primary)
  - XGBoost Regressor
  - CatBoost Regressor
  - Random Forest Regressor
- **Target Variables**: 
  - Indoor temperature, humidity, luminance
  - CO2, TVOC, PM2.5, PM10 concentrations
  - Average and peak noise levels
- **Features**: Weather correlations, time harmonics, rolling windows, lag terms
- **Model Management**: Automated best-model selection based on R², versioning, artifact storage

#### **Weather Pipeline** (`ece/pipeline_weather.py`)
- **Purpose**: Real weather data to EnergyPlus EPW format conversion
- **Data Sources**: Open-Meteo API (historical + 14-day forecast)
- **Processing**: Unit conversion, quality validation, EPW header generation
- **Geocoding**: Reverse location lookup for metadata enrichment
- **Execution**: Integrated with energy simulation workflow

#### **Energy Simulation Pipeline** (`ece/pipeline_eplus_wrapper.py`, `ece/pipeline_eplus.py`)
- **Purpose**: Building energy performance simulation
- **Components**: 
  - BIM2Sim: IFC → EnergyPlus IDF conversion
  - EnergyPlus 9.4.0: Building energy simulation engine
  - Weather integration: Real data → EPW format
- **Output**: Zone-level energy consumption, time-series data
- **Storage**: PostgreSQL energy tables with full simulation metadata

### **3. Comfort Analysis Engine** (`ece/helpers.py`)
- **Thermal Comfort**: 
  - PMV/PPD calculations (ISO 7730)
  - Adaptive comfort models
  - Classification: A/B/C/NC categories
- **Visual Comfort**: 
  - Yong et al. 2024 visual comfort scoring
  - Illuminance-based analysis
- **Acoustic Comfort**: 
  - Age-dependent noise annoyance modeling (Yilmaz et al.)
  - Average and peak noise assessment
- **Air Quality**: 
  - Multi-pollutant analysis (CO2, TVOC, PM2.5, PM10)
  - WHO/ASHRAE threshold-based classifications
- **Overall Comfort**: Weighted multi-domain scoring (0-4 scale)

### **4. Data Layer** (`ect/db/models.py`)
- **Database**: PostgreSQL 17 with SQLAlchemy ORM
- **Core Tables**: 
  - `spaces`: Building spaces with coordinates
  - `measurements`: Sensor data time series
  - `weather`: External weather conditions
  - `trained_models`: ML model metadata and performance
  - `predictions`: ML predictions with comfort classifications
- **Energy Tables**: 
  - `energy_buildings`: Building-level simulation results
  - `energy_spaces`: Zone-level energy consumption
  - `energy_timeseries`: Hourly energy data points
- **Features**:
  - Foreign key relationships with cascading deletes
  - Unique constraints for data integrity
  - Automated timestamp management

### **5. Infrastructure Layer**
- **Containerization**: Docker all-in-one deployment
- **Process Management**: Supervisor for PostgreSQL, dashboard, initialization
- **Environment**: 
  - ECT app: Python 3.11 venv
  - BIM2Sim: Conda environment with pythonocc-core
- **Persistence**: Named volumes for database, models, logs, exports
- **Networking**: Internal container communication with external port exposure

## **Database Schema**

### **Core Data Model**
- **Spaces**: `space_id`, `building_id`, `latitude`, `longitude`, `created_at`, `updated_at`
- **Measurements**: `measurement_id`, `space_id`, `time_end`, `temperature_c`, `rh_percent`, `luminance_lux`, `co2_ppm`, `average_noise_db`, `peak_db`, `pm2_5_ugm3`, `tvoc_ppb`, `data_type`
- **Weather**: `weather_id`, `space_id`, `time_end`, `outdoor_temperature_2m`, `outdoor_relative_humidity_2m`, `wind_speed_10m`, `shortwave_radiation`, `precipitation`, `cloud_cover`, `src`
- **TrainedModels**: `model_id`, `target`, `space_id`, `algorithm`, `hyperparams`, `metrics`, `version`, `model_path`
- **Predictions**: `prediction_id`, `model_id`, `weather_id`, `predicted_temperature_c`, `predicted_rh_percent`, `pmv`, `ppd`, `thermal_comfort_class`, `visual_comfort_class`, `acoustic_comfort_class`, `overall_comfort`, `occupant_profile`

### **Energy Simulation Schema**
- **EnergyBuilding**: `energy_building_id`, `building_id`, `simulation_timestamp`, `weather_file_path`, `ifc_file_path`, `total_heating_kwh`, `total_cooling_kwh`, `zones_count`, `heating_timeseries`, `cooling_timeseries`
- **EnergySpace**: `energy_space_id`, `energy_building_id`, `space_id`, `zone_id`, `heating_kwh`, `cooling_kwh`, `floor_area_m2`, `heating_intensity_kwh_m2`
- **EnergyTimeSeries**: `timeseries_id`, `energy_space_id`, `timestamp`, `heating_power_w`, `cooling_power_w`, `heating_energy_kwh`, `cooling_energy_kwh`

## **Feature Engineering Strategy**
- **Time Features**: Hour/day-of-year sine/cosine harmonics for seasonality
- **Weather Correlations**: Temperature, humidity, solar radiation, wind patterns
- **Rolling Windows**: Mean, std, max, min over configurable periods (12h, 24h, 48h)
- **Lag Features**: Autoregressive terms for temporal dependencies
- **Domain-Specific**: Comfort-relevant feature combinations per target variable

## **Deployment Architecture**

### **Single Container Deployment**
```
Docker Container → Supervisor → PostgreSQL (port 5432) + Streamlit (port 8599) + Init Process
```

### **External Access Points**
```
Host:8599 → Streamlit Dashboard (Web Interface)
Host:5499 → PostgreSQL Database (External Access)
```

### **Volume Management**
- **ect_postgres_data**: PostgreSQL database files (`/var/lib/postgresql/17/main`)
- **ect_models**: Trained ML models (`/app/models`)
- **ect_logs**: Application logs (`/app/logs`)
- **ect_database_exports**: Database backup files (`/app/database/data`)

## **API Workflows**

### **Data Processing Pipeline**

#### **CSV Upload Workflow**
1. **Upload**: CSV sensor data via Streamlit file uploader
2. **Validation**: Schema validation, timestamp parsing, data quality checks
3. **Storage**: Insert into `measurements` table with space mapping
4. **Weather**: Automatic weather data fetching for space coordinates
5. **Processing**: Available for ML training and comfort analysis

#### **Energy Simulation Workflow**
1. **IFC Upload**: Building model file via Streamlit interface
2. **Weather Generation**: Real weather data → EPW format conversion
3. **BIM2Sim Processing**: IFC → EnergyPlus IDF conversion
4. **EnergyPlus Execution**: Building energy simulation
5. **Results Storage**: Energy data stored in PostgreSQL energy tables
6. **Visualization**: Interactive charts and energy analysis dashboard

### **ML Model Training**

#### **Automated Training Process**
1. **Data Preparation**: Feature engineering with time harmonics and weather correlations
2. **Algorithm Selection**: Multi-algorithm comparison (LightGBM, XGBoost, CatBoost, RandomForest)
3. **Model Evaluation**: R² score-based best model selection
4. **Artifact Management**: Model serialization and metadata storage
5. **Version Control**: Automatic model versioning and performance tracking

#### **Prediction Generation**
1. **Model Loading**: Best performing model per target variable
2. **Feature Engineering**: Real-time feature computation
3. **Batch Processing**: Efficient prediction generation
4. **Comfort Classification**: Multi-domain comfort scoring
5. **Storage**: Results stored in predictions table with comfort metadata

### **Comfort Analysis Pipeline**

#### **Multi-Domain Assessment**
```
Sensor Data → ML Predictions → Comfort Calculations → Classification (A/B/C/D/NC) → Overall Scoring
```

#### **Integration Points**
- **Thermal**: PMV/PPD ISO calculations with predicted temperature/humidity
- **Visual**: Illuminance-based comfort scoring with ML predictions
- **Acoustic**: Age-dependent noise annoyance with predicted noise levels
- **IAQ**: Multi-pollutant assessment with ML-predicted concentrations
- **Energy**: Building simulation integration with comfort correlation analysis

## **Configuration Management**
- **Environment Variables**: Database credentials, ports, and application settings via `.env`
- **Feature Maps**: ML target-feature relationships in `ece/feature_map.py`
- **Model Parameters**: Algorithm hyperparameters and training configuration
- **Comfort Thresholds**: Multi-domain comfort classification boundaries
- **Weather API**: Open-Meteo endpoint configuration and rate limiting
- **Simulation Settings**: EnergyPlus execution parameters and BIM2SIM configuration

## **Development Setup**

### **Prerequisites**
- Docker 24+ (or any recent Docker Engine)
- 4GB+ RAM for containerized deployment
- Port availability: 8599 (dashboard), 5499 (database)

### **Local Development**
```bash
# Clone repository
git clone <repository-url>
cd energy-comfortness-tool

# Configure environment (optional - embedded in image)
cp .env.example .env

# Deploy using Docker
docker run -d \
  --name ect-standalone \
  -p 8599:8599 \
  -p 5499:5432 \
  -v ect_postgres_data:/var/lib/postgresql/17/main \
  -v ect_models:/app/models \
  -v ect_logs:/app/logs \
  -v ect_database_exports:/app/database/data \
  IMAGE_NAME:latest

# Access dashboard
open http://localhost:8599
```

## **How to**

### **Add new comfort domains**
Comfort analysis can be extended by:
1. Adding new target variables to `ece/feature_map.py`
2. Implementing comfort calculation functions in `ece/helpers.py`
3. Creating new classification logic for comfort categories
4. Adding visualization components to the Streamlit dashboard

### **Integrate additional ML algorithms**
New ML algorithms can be added by:
1. Extending the algorithm list in `ece/pipeline_ml.py`
2. Adding algorithm-specific hyperparameters and configuration
3. Implementing wrapper classes in `ece/model_zoo.py`
4. Testing performance comparison in the model selection pipeline

### **Custom building simulation workflows**
Energy simulation can be customized by:
1. Modifying EnergyPlus execution parameters in `ece/pipeline_eplus.py`
2. Adjusting BIM2SIM processing configuration
3. Adding custom post-processing for simulation results
4. Extending energy analysis visualizations in the dashboard

