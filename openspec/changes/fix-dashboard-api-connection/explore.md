# Exploration: Dashboard API Connection Error

## The Problem
The user reported that the dashboard is failing to check the Notion health status with the following error:
`HTTPConnectionPool(host='localhost', port=8000): Max retries exceeded with url: /config/check/notion`

This error occurs because the dashboard is attempting to connect to the API on `localhost:8000`.

## Code Analysis
In `dashboard/app.py`, the `_check_service` function defines the `api_base`:
```python
def _check_service(endpoint: str, payload: dict) -> dict:
    import requests
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")
    try:
        resp = requests.post(f"{api_base}{endpoint}", json=payload, timeout=15)
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}
```

In `docker-compose.yml`, the `dashboard` service does not define an `API_BASE_URL` environment variable. Therefore, it falls back to `http://localhost:8000`.

## The Root Cause
Inside a Docker container, `localhost` refers to the container itself. Since the API is running in a separate container named `marketingmaker_api` (or defined as the `api` service), `localhost:8000` is inaccessible from the dashboard container.

## Proposed Solution
We need to provide the correct `API_BASE_URL` to the dashboard container that points to the API service within the Docker network. The internal Docker network resolves service names, so the URL should be `http://marketingmaker_api:8000` or `http://api:8000`. According to `docker-compose.yml`, the service name is `api` and the container name is `marketingmaker_api`. Either will work, but `http://marketingmaker_api:8000` matches the explicit container name.

Additionally, we should check if any other places in `dashboard/app.py` or `.env` need `API_BASE_URL` defined.
