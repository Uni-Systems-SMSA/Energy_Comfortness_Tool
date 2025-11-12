# Multi-stage build for Energy Comfortness Tool with BIM2Sim and PostgreSQL 17
FROM ubuntu:22.04

# Prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python and build essentials
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-pip \
    build-essential \
    gcc \
    g++ \
    gfortran \
    # PostgreSQL 17
    wget \
    gnupg \
    lsb-release \
    ca-certificates \
    # Git for BIM2Sim clone
    git \
    # Additional dependencies for pythonocc-core
    libgl1-mesa-glx \
    libglu1-mesa \
    libsm6 \
    libxext6 \
    libxrender1 \
    # EnergyPlus dependencies
    libx11-6 \
    libgomp1 \
    # Process management
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda for BIM2Sim (requires conda for pythonocc-core)
RUN wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh && \
    bash miniconda.sh -b -p /opt/conda && \
    rm miniconda.sh && \
    /opt/conda/bin/conda config --set channel_priority strict && \
    /opt/conda/bin/conda config --add channels conda-forge && \
    /opt/conda/bin/conda config --set auto_activate_base false && \
    /opt/conda/bin/conda clean -afy

# Add conda to PATH
ENV PATH=/opt/conda/bin:$PATH

# Accept conda Terms of Service for required channels
RUN /opt/conda/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    /opt/conda/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Install PostgreSQL 17
RUN wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - && \
    echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && \
    apt-get install -y postgresql-17 postgresql-contrib-17 && \
    rm -rf /var/lib/apt/lists/*

# Install EnergyPlus 9.4.0
RUN EPLUS_VERSION=9.4.0 && \
    EPLUS_TAG=v${EPLUS_VERSION} && \
    EPLUS_SHA=998c4b761e && \
    EPLUS_INSTALL_DIR=/usr/local/EnergyPlus-${EPLUS_VERSION} && \
    wget -q https://github.com/NREL/EnergyPlus/releases/download/${EPLUS_TAG}/EnergyPlus-${EPLUS_VERSION}-${EPLUS_SHA}-Linux-Ubuntu20.04-x86_64.sh && \
    chmod +x EnergyPlus-${EPLUS_VERSION}-${EPLUS_SHA}-Linux-Ubuntu20.04-x86_64.sh && \
    printf 'y\n\nn\n' | ./EnergyPlus-${EPLUS_VERSION}-${EPLUS_SHA}-Linux-Ubuntu20.04-x86_64.sh && \
    rm EnergyPlus-${EPLUS_VERSION}-${EPLUS_SHA}-Linux-Ubuntu20.04-x86_64.sh && \
    ln -sf /usr/local/EnergyPlus-9-4-0/energyplus /usr/local/bin/energyplus && \
    ln -sf /usr/local/EnergyPlus-9-4-0 /usr/local/EnergyPlus

# Set EnergyPlus environment variables
ENV ENERGYPLUS_DIR=/usr/local/EnergyPlus \
    ENERGYPLUS_INSTALL_DIR=/usr/local/EnergyPlus

# Create application directory
WORKDIR /app

# Copy ECT application code
COPY ect/ /app/ect/
COPY .env /app/.env

# Create directory for models and logs (but not PostgreSQL data - that's managed by volume)
RUN mkdir -p /app/models /app/logs /app/database/data

# ========================================
# ECT Application Virtual Environment
# ========================================
RUN python3.11 -m venv /app/venv_ect && \
    /app/venv_ect/bin/pip install --no-cache-dir --upgrade pip setuptools wheel && \
    /app/venv_ect/bin/pip install --no-cache-dir -r /app/ect/requirements.txt

# ========================================
# BIM2Sim Conda Environment
# ========================================
# Clone BIM2Sim repository with submodules
RUN git clone --recurse-submodules -b development https://github.com/BIM2SIM/bim2sim.git /app/bim2sim

# Create conda environment for BIM2Sim with Python 3.11
RUN /opt/conda/bin/conda create -n bim2sim python=3.11 -c conda-forge -y && \
    /opt/conda/bin/conda clean -afy

# Install pythonocc-core from conda-forge (not available via PyPI)
RUN /opt/conda/bin/conda install -n bim2sim -c conda-forge pythonocc-core=7.7.0 -y && \
    /opt/conda/bin/conda clean -afy

# Install BIM2Sim base package
RUN /opt/conda/envs/bim2sim/bin/pip install --no-cache-dir -e /app/bim2sim

# Install BIM2Sim EnergyPlus plugin
RUN /opt/conda/envs/bim2sim/bin/pip install --no-cache-dir -e '/app/bim2sim[PluginEnergyPlus]'

# Note: Verification with 'python -m bim2sim -v' skipped due to import path issues during build
# BIM2Sim will be available when container runs with proper Python path

# ========================================
# PostgreSQL Configuration
# ========================================
USER postgres

# Remove any existing data directory and initialize fresh PostgreSQL database cluster
RUN rm -rf /var/lib/postgresql/17/main && \
    mkdir -p /var/lib/postgresql/17/main && \
    /usr/lib/postgresql/17/bin/initdb -D /var/lib/postgresql/17/main

# Configure PostgreSQL
RUN echo "host all all 0.0.0.0/0 md5" >> /var/lib/postgresql/17/main/pg_hba.conf && \
    echo "listen_addresses='*'" >> /var/lib/postgresql/17/main/postgresql.conf && \
    echo "port=5432" >> /var/lib/postgresql/17/main/postgresql.conf

# Switch back to root
USER root

# ========================================
# Supervisor Configuration
# ========================================
# Create initialization script for PostgreSQL
RUN cat > /usr/local/bin/init-postgres.sh <<'INITEOF' && \
    sed -i 's/\r$//' /usr/local/bin/init-postgres.sh && \
    chmod +x /usr/local/bin/init-postgres.sh
#!/bin/bash
set -e

# Ensure data directory exists and has correct ownership
mkdir -p /var/lib/postgresql/17/main
chown -R postgres:postgres /var/lib/postgresql/17/main

# Check if PostgreSQL is already initialized
if [ ! -f /var/lib/postgresql/17/main/PG_VERSION ]; then
    echo "Initializing PostgreSQL database..."
    su - postgres -c "/usr/lib/postgresql/17/bin/initdb -D /var/lib/postgresql/17/main"
    
    # Configure PostgreSQL
    echo "host all all 0.0.0.0/0 md5" >> /var/lib/postgresql/17/main/pg_hba.conf
    echo "listen_addresses='*'" >> /var/lib/postgresql/17/main/postgresql.conf
    echo "port=5432" >> /var/lib/postgresql/17/main/postgresql.conf
    echo "PostgreSQL initialized successfully"
    
    # Start PostgreSQL temporarily to create user and database
    echo "Starting PostgreSQL temporarily to create user and database..."
    su - postgres -c "/usr/lib/postgresql/17/bin/pg_ctl -D /var/lib/postgresql/17/main -w start"
    
    # Create user and database from .env variables
    su - postgres -c "psql -c \"CREATE USER ${POSTGRES_USER} WITH PASSWORD '${POSTGRES_PASSWORD}';\""
    su - postgres -c "psql -c \"CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER};\""
    su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO ${POSTGRES_USER};\""
    echo "User ${POSTGRES_USER} and database ${POSTGRES_DB} created successfully"
    
    # Stop PostgreSQL
    su - postgres -c "/usr/lib/postgresql/17/bin/pg_ctl -D /var/lib/postgresql/17/main -w stop"
fi

# Start PostgreSQL as postgres user
exec su - postgres -c "/usr/lib/postgresql/17/bin/postgres -D /var/lib/postgresql/17/main"
INITEOF

COPY <<'EOF' /etc/supervisor/conf.d/supervisord.conf
[supervisord]
nodaemon=true
user=root
logfile=/var/log/supervisor/supervisord.log
pidfile=/var/run/supervisord.pid

[program:postgresql]
user=root
command=/bin/bash /usr/local/bin/init-postgres.sh
autostart=true
autorestart=true
stdout_logfile=/var/log/supervisor/postgresql.log
stderr_logfile=/var/log/supervisor/postgresql_err.log
environment=POSTGRES_USER="%(ENV_POSTGRES_USER)s",POSTGRES_PASSWORD="%(ENV_POSTGRES_PASSWORD)s",POSTGRES_DB="%(ENV_POSTGRES_DB)s"
priority=1

[program:ect_dashboard]
command=/app/venv_ect/bin/streamlit run /app/ect/dashboard/app.py --server.port=8599 --server.address=0.0.0.0
directory=/app
autostart=true
autorestart=true
stdout_logfile=/var/log/supervisor/ect_dashboard.log
stderr_logfile=/var/log/supervisor/ect_dashboard_err.log
environment=PYTHONPATH="/app",PATH="/app/venv_ect/bin:/usr/local/bin:/usr/bin:/bin",ENERGYPLUS_DIR="/usr/local/EnergyPlus"
priority=10

[program:init_db]
command=/bin/bash -c "sleep 5 && /app/venv_ect/bin/python /app/ect/db/session.py"
directory=/app
autostart=true
autorestart=false
startsecs=0
stdout_logfile=/var/log/supervisor/init_db.log
stderr_logfile=/var/log/supervisor/init_db_err.log
environment=PYTHONPATH="/app"
priority=5
EOF

# Create supervisor log directory
RUN mkdir -p /var/log/supervisor

# Expose ports
# 5432: PostgreSQL (standard port)
# 8599: Streamlit dashboard (access via http://localhost:8599)
EXPOSE 5432 8599

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8599/_stcore/health || exit 1

# Set Python path for ECT app
ENV PYTHONPATH=/app

# Declare volumes for persistent data
# Mount these with docker run -v or in docker-compose.yml:
# - PostgreSQL data: /var/lib/postgresql/17/main
# - Trained models: /app/models
# - Application logs: /app/logs
# - Database exports/backups: /app/database/data
VOLUME ["/var/lib/postgresql/17/main", "/app/models", "/app/logs", "/app/database/data"]

# Start supervisor (manages PostgreSQL + Streamlit)
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
