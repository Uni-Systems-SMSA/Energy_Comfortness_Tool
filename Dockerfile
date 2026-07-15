# Start from official lightweight Python base image
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    libxml2 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Miniforge (free, open-source Conda alternative with conda-forge pre-configured)
ENV CONDA_DIR=/opt/conda
RUN curl -SLO https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh && \
    mkdir /root/.conda && \
    bash Miniforge3-Linux-x86_64.sh -b -p $CONDA_DIR && \
    rm -f Miniforge3-Linux-x86_64.sh

ENV PATH=$CONDA_DIR/bin:$PATH

# Create the conda environment and install pythonocc-core (OCC) from conda-forge (Python 3.11 is required by bim2sim)
RUN conda install -c conda-forge python=3.11 pythonocc-core -y && \
    conda clean -a -y

# Install EnergyPlus v9.4.0 (Linux build from NatLabRockies)
RUN curl -SLO https://github.com/NatLabRockies/EnergyPlus/releases/download/v9.4.0/EnergyPlus-9.4.0-998c4b761e-Linux-Ubuntu20.04-x86_64.tar.gz && \
    tar -xzf EnergyPlus-9.4.0-998c4b761e-Linux-Ubuntu20.04-x86_64.tar.gz && \
    mv EnergyPlus-9.4.0-998c4b761e-Linux-Ubuntu20.04-x86_64 /usr/local/EnergyPlus-9-4-0 && \
    ln -s /usr/local/EnergyPlus-9-4-0/energyplus /usr/local/bin/energyplus && \
    rm EnergyPlus-9.4.0-998c4b761e-Linux-Ubuntu20.04-x86_64.tar.gz

# Set working directory
WORKDIR /app

# Install base Python dependencies for Streamlit and ML
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Clone bim2sim, install dependencies, and manually copy all source files (including non-Python template/data files)
# to site-packages, as pip install does not copy non-Python resources.
RUN git clone --recursive -b development --depth 1 --shallow-submodules https://github.com/BIM2SIM/bim2sim.git /tmp/bim2sim && \
    pip install --no-cache-dir geomeppy numpy-stl /tmp/bim2sim && \
    cp -r /tmp/bim2sim/bim2sim/* /opt/conda/lib/python3.11/site-packages/bim2sim/ && \
    rm -rf /tmp/bim2sim

# Create a sitecustomize.py file inside the conda environment's site-packages to automatically 
# monkeypatch the collections module at startup for Python 3.10+ compatibility with older eppy/geomeppy code.
# This avoids making any modifications to the repository's Python files.
RUN echo "import collections, collections.abc; \
collections.MutableSequence = collections.abc.MutableSequence; \
collections.Iterable = collections.abc.Iterable; \
collections.Mapping = collections.abc.Mapping; \
collections.MutableMapping = collections.abc.MutableMapping; \
collections.Sequence = collections.abc.Sequence" > /opt/conda/lib/python3.11/site-packages/sitecustomize.py

# Copy project files
COPY . .

# Expose Streamlit port
EXPOSE 8501

# Start the Streamlit application
CMD ["streamlit", "run", "dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
