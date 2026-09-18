# Production-Ready Dockerfile for GridWise Campus Energy Optimizer
FROM python:3.11-slim

# Avoid buffering and bytecode generation
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install system dependencies (including CBC solver package)
RUN apt-get update && apt-get install -y --no-install-recommends \
    coinor-cbc \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app

# Expose HTTP port
EXPOSE 8000

# Run uvicorn bound to 0.0.0.0
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
