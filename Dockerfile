# ──────────── GridWise LLM Service — Dockerfile ────────────
# python:3.11-slim for small footprint. CBC solver (PuLP) and scipy are
# pure-Python wheel installs — no system-level build deps required.
#
# Image does NOT bake in API keys. Use --env-file or -e at runtime.

FROM python:3.11-slim

# Don't buffer Python stdout/stderr (cleaner logs)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create non-root user
RUN groupadd --system gridwise \
    && useradd --system --gid gridwise --home /app --shell /usr/sbin/nologin gridwise

WORKDIR /app

# Install deps first (better layer caching)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy source
COPY src /app/src
COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md

# Ensure src is on PYTHONPATH
ENV PYTHONPATH=/app/src

# Switch to non-root
RUN chown -R gridwise:gridwise /app
USER gridwise

# Service port — must match host mapping
EXPOSE 8000

# Healthcheck — judges should see /health come up within 60s
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()" || exit 1

# Run
CMD ["uvicorn", "gridwise.app:app", "--host", "0.0.0.0", "--port", "8000"]
