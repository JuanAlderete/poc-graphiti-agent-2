# ─── Stage 1: Build dependencies ─────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /app

# System deps for asyncpg (needs libpq) and building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Stage 2: Runtime ────────────────────────────────────────────────────
FROM python:3.13-slim

WORKDIR /app

# Runtime deps only (libpq for asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Streamlit config: disable telemetry, set port
RUN mkdir -p /root/.streamlit && \
    echo '[server]\nheadless = true\nport = 8501\naddress = "0.0.0.0"\nenableCORS = false\n\n[browser]\ngatherUsageStats = false' > /root/.streamlit/config.toml

EXPOSE 8501

# Default: run the dashboard
# Override with: docker compose exec app python -m poc.run_poc --ingest ...
CMD ["python", "-m", "streamlit", "run", "dashboard/app.py"]
