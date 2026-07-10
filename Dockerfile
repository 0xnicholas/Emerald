# Emerald Dockerfile — multi-stage build (v0.4.0)

FROM python:3.12-slim AS development

WORKDIR /app

# System dependencies (full set for dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .
RUN pip install --no-cache-dir -e .

# ---- Production stage (v0.4.0: independent pip install) ----
FROM python:3.12-slim AS production

WORKDIR /app

# Runtime system deps only (no build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Production-only Python deps
COPY requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

# Application code
COPY emerald/ ./emerald/
COPY alembic.ini ./
COPY migrations/ ./migrations/

# Non-root user for runtime
RUN useradd -m -u 1001 emerald && chown -R emerald:emerald /app
USER emerald

EXPOSE 8000

CMD ["uvicorn", "emerald.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
