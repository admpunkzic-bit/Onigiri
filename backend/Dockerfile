FROM python:3.12-slim

# Install system dependencies (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Directory for SQLite persistent database
RUN mkdir -p /app/data

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    SQLITE_DB_PATH=/app/data/onigiri.db

EXPOSE 8000

# Production run with uvicorn (no reload)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
