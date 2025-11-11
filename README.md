# Energy Comfortness Tool (ECT)

[![Version](https://img.shields.io/badge/version-0.0.9-blue.svg)](https://github.com/ispingos/energy_comfortness_tool)
[![Python](https://img.shields.io/badge/python-3.8+-green.svg)](https://python.org)
[![Streamlit](https://img.shields.io/badge/streamlit-1.28+-red.svg)](https://streamlit.io)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

A comprehensive web-based tool for **indoor environmental quality (IEQ) prediction**, **thermal comfort analysis**, and **building energy simulation**. The ECT combines machine learning models, real-time weather data, and EnergyPlus simulations to provide actionable insights for building performance optimization.

## 🌟 Key Features

### 🎯 **Multi-Domain Comfort Prediction**
- **Thermal Comfort**: PMV/PPD calculations with adaptive comfort models
- **Visual Comfort**: Illuminance and glare analysis
- **Acoustic Comfort**: Noise level assessment and annoyance prediction  
- **Indoor Air Quality (IAQ)**: CO₂, CO, TVOC, PM2.5, PM10 monitoring and classification
- **Overall Comfort Score**: Unified metric combining all comfort domains with intelligent weighting

### 🏢 **Building Energy Simulation**
- **EnergyPlus Integration**: Full building energy modeling with IFC file support
- **Weather File Generation**: Automatic EPW file creation from real weather data
- **Multi-Zone Analysis**: Zone-level energy consumption and comfort correlation
- **Cross-Year Simulations**: Handle simulations spanning multiple calendar years
- **Temporal Resolution**: Hourly energy consumption tracking and analysis

### 🤖 **Advanced Machine Learning**
- **Multiple Algorithms**: LightGBM, XGBoost, CatBoost, Neural Networks
- **Feature Engineering**: Temporal features, weather correlations, autoregressive terms
- **Model Management**: Automated training, versioning, and performance tracking
- **Prediction Pipeline**: Real-time prediction with confidence intervals

### 📊 **Interactive Dashboard**
- **Real-Time Visualization**: Responsive charts with Altair and Streamlit
- **Multi-Tab Interface**: Organized by comfort domain (Thermal, Visual, Acoustic, IAQ, Energy)
- **Data Export**: CSV downloads for all predictions and analysis results
- **Configurable Profiles**: Multiple occupant profiles for personalized comfort assessment

### 🗄️ **Robust Data Management**
- **PostgreSQL Backend**: Scalable database with optimized queries
- **Time-Series Storage**: Efficient handling of sensor data and predictions
- **Data Validation**: Comprehensive input validation and error handling
- **Migration Support**: Database schema versioning and updates

## 🏗️ Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Web Dashboard │    │  ML Engine      │    │ Energy Simulator│
│   (Streamlit)   │◄──►│  (ECE)          │◄──►│  (EnergyPlus)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │              ┌─────────────────┐              │
         │              │   Weather API   │              │
         │              │  (Open-Meteo)   │              │
         │              └─────────────────┘              │
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
                    ┌─────────────────┐
                    │   PostgreSQL    │
                    │   Database      │
                    └─────────────────┘
```

## 🚀 Quick Start

### Prerequisites
- **Python 3.8+**
- **PostgreSQL 12+** 
- **Docker & Docker Compose** (recommended)
- **Git**

### Installation

#### Option 1: Docker Setup (Recommended)
```bash
# Clone the repository
git clone https://github.com/ispingos/energy_comfortness_tool.git
cd energy_comfortness_tool

# Create environment file
cp .env.example .env
# Edit .env with your database credentials

# Start the database
docker-compose up -d

# Install Python dependencies
pip install -r requirements.txt

# Run database migrations
python -m migrations.migrate_schema

# Start the application
streamlit run dashboard/app.py
```

#### Option 2: Local Development Setup
```bash
# Clone and setup
git clone https://github.com/ispingos/energy_comfortness_tool.git
cd energy_comfortness_tool

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup PostgreSQL database (configure .env file)
# Create database: createdb energy_comfortness_tool

# Run migrations
python -m migrations.migrate_schema

# Start application
streamlit run dashboard/app.py
```

### 📁 Project Structure

```
energy_comfortness_tool/
├── 📊 dashboard/           # Streamlit web application
│   ├── app.py             # Main dashboard (5000+ lines)
│   ├── assets/            # Static assets and logos
│   ├── models/            # Trained ML model files (.pkl)
│   └── model_reports/     # Model performance reports
├── 🗄️ db/                 # Database layer
│   ├── models.py          # SQLAlchemy ORM models
│   └── session.py         # Database connection management
├── 🤖 ece/                # Energy Comfortness Engine
│   ├── pipeline_ml.py     # ML training and prediction
│   ├── pipeline_weather.py # Weather data processing
│   ├── pipeline_eplus*.py # EnergyPlus simulation wrappers
│   ├── feature_map.py     # Feature definitions and mappings
│   ├── model_zoo.py       # ML algorithm implementations
│   └── weather_api.py     # External weather API integration
├── 🏢 eplus_sim/          # EnergyPlus simulation workspace
│   ├── weather/           # Generated EPW weather files
│   ├── models/            # Building models (IFC, gbXML)
│   ├── results/           # Simulation outputs and reports
│   └── templates/         # Building templates
├── 📂 migrations/         # Database schema migrations
├── 🧪 tests/              # Comprehensive test suite
├── 📚 docs/               # Documentation and guides
└── 🛠️ scripts/           # Utility and setup scripts
```

## 💡 Usage Guide

### 1. **Data Upload and Configuration**
```
📋 Sidebar → Configure Button
├── 📊 Upload CSV sensor data (with space_id, timestamps, measurements)
├── 🏗️ Upload IFC building model files
└── ⚙️ System validates and processes data automatically
```

### 2. **Weather Data and Time Configuration**
```
📅 Sidebar → Time Window
├── 🗓️ Set analysis period (start/end dates)
├── 📍 Select building/space from dropdown
└── 🌤️ Weather data auto-downloaded from Open-Meteo API
```

### 3. **Comfort Prediction Workflow**
```
🎯 Sidebar → Predict Button
├── 🤖 ML models predict environmental parameters
├── 😊 Comfort classes calculated (A/B/C/D scale)
├── 📊 Overall comfort score computed (0-4 scale)
└── 📈 Results displayed in organized tabs
```

### 4. **Energy Simulation Workflow**
```
⚡ Energy Tab → Run Energy Simulation
├── 🏗️ IFC model processed with bim2sim
├── 🌤️ EPW weather file generated from sensor data
├── 🏃‍♂️ EnergyPlus simulation executed
├── 💾 Results stored in database with timestamps
└── 📊 Energy consumption visualized by zone/time
```

## 📈 Feature Highlights

### **Thermal Comfort Analysis**
- **PMV (Predicted Mean Vote)** calculation using ISO 7730 standard
- **PPD (Predicted Percentage Dissatisfied)** with adaptive comfort models
- **Temperature and humidity** prediction with weather correlation
- **Seasonal adaptation** with time-based feature engineering

### **Indoor Air Quality (IAQ) Assessment**
- **Multi-pollutant monitoring**: CO₂, CO, TVOC, PM2.5, PM10
- **Health-based thresholds** with WHO and ASHRAE standards
- **Automated compliance reporting** with color-coded classifications
- **Trend analysis** and performance benchmarking

### **Building Energy Performance**
- **Zone-level energy breakdown** (heating/cooling/total)
- **Energy intensity metrics** (kWh/m²) with floor area normalization
- **Peak demand analysis** for capacity planning
- **Time-series correlation** between energy use and comfort

### **Advanced Analytics**
- **Cross-domain correlation** analysis (energy vs comfort)
- **Occupant profile customization** for personalized comfort
- **Export capabilities** for external analysis tools
- **Performance benchmarking** with historical data comparison

## 🔧 Configuration Options

### **Environment Variables (.env)**
```bash
# Database Configuration
POSTGRES_DB=energy_comfortness_tool
POSTGRES_USER=your_username
POSTGRES_PASSWORD=your_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5442

# Application Settings
LOG_LEVEL=INFO
ENABLE_DEBUG=false
MAX_UPLOAD_SIZE=200MB

# Weather API (Optional - has free tier)
OPENMETEO_API_KEY=your_api_key
```

### **ML Model Configuration**
```python
# Feature Engineering
TIME_DRIVERS = ["hour_sin", "hour_cos", "doy_sin", "doy_cos"]
WEATHER_FEATURES = ["outdoor_temperature_2m", "outdoor_relative_humidity_2m", "cloud_cover"]

# Model Algorithms  
ALGORITHMS = ["lightgbm", "xgboost", "catboost", "neural_network"]

# Prediction Targets
TARGETS = ["temperature_c", "rh_percent", "luminance_lux", "co2_ppm", 
          "average_noise_db", "peak_db", "pm2_5_ugm3", "tvoc_ppb"]
```

## 📚 API Reference

### **Core Functions**

#### **Comfort Prediction**
```python
from ece.pipeline_ml import main_train_all_targets, predict_all_targets

# Train models for all comfort parameters
main_train_all_targets(
    start_date="2024-01-01",
    end_date="2024-12-31", 
    space_id="office_01"
)

# Generate predictions
predictions = predict_all_targets(
    weather_data=df_weather,
    models_dir="dashboard/models/"
)
```

#### **Energy Simulation**
```python
from ece.pipeline_eplus_wrapper import run_user_request
from ece.pipeline_weather import generate_epw_for_location

# Generate weather file
epw_path = generate_epw_for_location(
    space_id="office_01",
    latitude=40.6401,
    longitude=22.9444,
    start=datetime(2024, 1, 1),
    end=datetime(2024, 12, 31)
)

# Run EnergyPlus simulation
results = run_user_request(
    ifc_file_path="building_model.ifc",
    weather_file_path=epw_path,
    space_id="office_01"
)
```

#### **Comfort Classification**
```python
from ece.helpers import calculate_comfort_classes

# Calculate all comfort metrics
comfort_results = calculate_comfort_classes(
    temperature=22.5,        # °C
    humidity=45.0,          # %
    luminance=500,          # lux  
    noise_avg=40,           # dB
    co2=450,               # ppm
    occupant_profile="Profile1"
)
```

## 🧪 Testing

The project includes comprehensive test coverage:

```bash
# Run all tests
python -m pytest tests/

# Test specific modules  
python -m pytest tests/test_comfort_calculation.py
python -m pytest tests/test_energy_simulation.py
python -m pytest tests/test_ml_pipeline.py

# Test coverage report
python -m pytest --cov=ece --cov=db --cov-report=html
```

### **Test Categories**
- **🔬 Unit Tests**: Individual function and class testing
- **🔗 Integration Tests**: Multi-component workflow testing  
- **📊 Data Tests**: Validation of ML model predictions
- **🏢 Simulation Tests**: EnergyPlus integration testing
- **🌐 API Tests**: Weather data and external service testing

## 📋 Requirements

### **Core Dependencies**
- **Web Framework**: `streamlit>=1.28`
- **Machine Learning**: `scikit-learn`, `lightgbm`, `xgboost`, `catboost`, `tensorflow`
- **Data Processing**: `pandas>=2.2`, `numpy>=1.26`, `scipy>=1.12`
- **Database**: `sqlalchemy>=2.0`, `psycopg2-binary`
- **Visualization**: `altair`, `matplotlib`
- **Building Simulation**: `bim2sim`, custom EnergyPlus wrappers

### **Optional Dependencies**
- **Comfort Analysis**: `pythermalcomfort` (PMV/PPD calculations)
- **Forecasting**: `prophet`, `pytorch-forecasting`
- **Optimization**: `optuna`, `mlflow`
- **Geospatial**: `geopy` (location services)

## 🚧 Known Limitations

- **EnergyPlus Version**: Requires EnergyPlus 9.0+ for IFC processing
- **File Size Limits**: IFC files limited to 200MB for upload
- **Simulation Time**: Large buildings may require 10-30 minutes per simulation
- **Weather Data**: Historical data limited to 2 years by free API tier
- **Concurrent Users**: Single-user application (Streamlit limitation)

## 🗺️ Roadmap

### **Upcoming Features**
- [ ] **Multi-building comparison** dashboard
- [ ] **Real-time sensor integration** via MQTT/InfluxDB
- [ ] **Advanced HVAC control optimization**
- [ ] **Mobile-responsive design**
- [ ] **API endpoints** for external integration
- [ ] **Automated report generation** (PDF/Word)
- [ ] **Machine learning model explanability** with SHAP

### **Performance Improvements**  
- [ ] **Caching layer** for repeated calculations
- [ ] **Async processing** for long-running simulations
- [ ] **Database optimization** with indexing and partitioning
- [ ] **Frontend optimization** for large datasets

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details.

### **Development Setup**
```bash
# Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/energy_comfortness_tool.git

# Create feature branch
git checkout -b feature/your-feature-name

# Make changes and test
python -m pytest tests/

# Submit pull request
git push origin feature/your-feature-name
```

### **Code Standards**
- **Python Style**: Follow PEP 8 with `black` formatting
- **Documentation**: Docstrings for all functions and classes
- **Testing**: Minimum 80% test coverage for new features
- **Commits**: Conventional commit messages (`feat:`, `fix:`, `docs:`)

## 📞 Support

- **📧 Email**: [Project Maintainer](mailto:maintainer@example.com)
- **🐛 Bug Reports**: [GitHub Issues](https://github.com/ispingos/energy_comfortness_tool/issues)
- **💡 Feature Requests**: [GitHub Discussions](https://github.com/ispingos/energy_comfortness_tool/discussions)
- **📚 Documentation**: [Wiki Pages](https://github.com/ispingos/energy_comfortness_tool/wiki)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **EnergyPlus**: US Department of Energy building simulation engine
- **Open-Meteo**: Free weather API service
- **Streamlit**: Rapid web app framework for Python
- **scikit-learn**: Machine learning library
- **PostgreSQL**: Advanced open-source database

---

**Made with ❤️ for sustainable building performance and occupant comfort**
