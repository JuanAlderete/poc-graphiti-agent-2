# Proposal: Fix Dashboard API Connection Issue

## Intent
The intent is to resolve the `Max retries exceeded` connection error the dashboard experiences when trying to communicate with the API.

## Problem Statement
The dashboard container defaults to using `http://localhost:8000` to contact the API. Because it runs in its own Docker container, `localhost` points to the dashboard container, not the API container, leading to a connection failure.

## Proposed Solution
Update `docker-compose.yml` to inject the `API_BASE_URL` environment variable into the `dashboard` service, pointing it to the correct internal Docker address for the API container: `http://marketingmaker_api:8000`.

We will also update `.env.example` to include `API_BASE_URL` for local development outside Docker.

## Scope
### In Scope
- Updating `docker-compose.yml` to set `API_BASE_URL`.
- Updating `.env` and `.env.example` if applicable.

### Out of Scope
- Modifying the Python code in `dashboard/app.py` since it already supports reading `API_BASE_URL`.

## Risks
None. This is standard Docker networking configuration.
