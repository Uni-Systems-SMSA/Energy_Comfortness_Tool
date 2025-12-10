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
- **Python 3.11**
- **Docker & Docker Compose**
- **Git**
- **bim2sim conda environment**
- **EnergyPlus v9.4**

### Important Notice
For EnergyPlus on linux, the default installation path is
- `/usr/local/EnergyPlus-9-4-0`

For running in Windows, it should be adjusted in `ece/pipeline_eplus_wrapper.py`.

### Installation

#### Local Development Setup
```bash
# Clone and setup
git clone https://github.com/ispingos/energy_comfortness_tool.git
cd energy_comfortness_tool

# setup env variables
cp .env.template .env
# adjust .env file as necessary

# Start the database
docker-compose up -d

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: venv\Scripts\activate

# Or with Conda
# conda env create -n energy-comfortness-tool python=3.11
# conda activate energy-comfortness-tool

# Install dependencies
pip install -r requirements.txt

# Start application
streamlit run dashboard/app.py

# streamlit is going to expose the app
# at port 8501 (unless otherwise configured)

# For background streamlit run
# streamlit run dashboard/app.py &

# To kill the streamlit app, first get its pid
ps -ef | grep streamlit

# !!!  VERY CAREFUL TO GET THE ID OF THE CORRECT PROCESS !!!
sudo kill {pid}

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
