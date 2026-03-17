# ─── Stage 1: Base ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install runtime system dependencies (libpq for asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# ─── Stage 2: Builder ───────────────────────────────────────────────────────
FROM base AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Create partial requirements for API to minimize image size
# Excludes heavy UI/Data libraries
RUN grep -vE "streamlit|plotly|pandas|matplotlib|nest_asyncio" requirements.txt > requirements.api.txt

# Install API dependencies to a temporary directory
RUN pip install --no-cache-dir --prefix=/install/api -r requirements.api.txt

# Install all dependencies (including Dashboard) to a separate directory
RUN pip install --no-cache-dir --prefix=/install/full -r requirements.txt

# ─── Stage 3: API Runtime ──────────────────────────────────────────────────
FROM base AS api

# Copy only API dependencies
COPY --from=builder /install/api /usr/local

# Copy application code
COPY . .

# Expose API port
EXPOSE 8000

# Run FastAPI app
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ─── Stage 4: Dashboard Runtime ───────────────────────────────────────────
FROM base AS dashboard

# Copy full dependencies
COPY --from=builder /install/full /usr/local

# Copy application code
COPY . .

# Streamlit config
RUN mkdir -p /root/.streamlit && \
    echo '[server]\nheadless = true\nport = 8501\naddress = "0.0.0.0"\nenableCORS = false\n\n[browser]\ngatherUsageStats = false' > /root/.streamlit/config.toml

# Expose Dashboard port
EXPOSE 8501

# Run Streamlit dashboard
CMD ["python", "-m", "streamlit", "run", "dashboard/app.py"]
