# syntax=docker/dockerfile:1
# Z-Image-Turbo server — PyTorch with CUDA 12.6 + Diffusers
# Build: docker build -t ghcr.io/adorsys-gis/z-image-turbo-server:v1.0.0 .
# Run:   docker run --gpus all -p 8000:8000 \
#          -e API_KEY=test -e MODEL_DIR=/mnt/models \
#          ghcr.io/adorsys-gis/z-image-turbo-server:v1.0.0
FROM pytorch/pytorch:2.7.0-cuda12.6-cudnn9-runtime

LABEL org.opencontainers.image.source="https://github.com/ADORSYS-GIS/ai-helm"
LABEL org.opencontainers.image.description="Z-Image-Turbo FP8 inference server (OpenAI /v1/images/generations)"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# Prevent Python from writing .pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cu126 \
    -r requirements.txt

# Copy app
COPY app.py .

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["python", "app.py"]
