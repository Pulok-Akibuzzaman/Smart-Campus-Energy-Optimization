# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Set environment flags
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0

WORKDIR /app

# Install system dependencies if required for numerical wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code, static dashboard, and sample pack for self-testing
COPY app/ app/
COPY static/ static/
COPY run.py .
COPY BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json .
COPY test_solution.py .

# Expose service port
EXPOSE 8000

# Healthcheck for container orchestrators
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run API server bound to 0.0.0.0:8000
CMD ["python", "run.py"]
