# Emerald Dockerfile — multi-stage build

FROM python:3.12-slim AS development

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ---- Production stage ----
FROM python:3.12-slim AS production

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=development /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY . .

CMD ["uvicorn", "emerald.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
