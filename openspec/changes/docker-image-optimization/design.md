# Design: Docker Image Optimization via Multi-Target Builds

## Technical Approach

We will refactor the single `Dockerfile` into a multi-stage, multi-target build. The primary strategy is to prevent heavy "dashboard" dependencies (Streamlit, Plotly, Pandas) from leaking into the "api" production image.

## Architecture Decisions

### Decision: Multi-Target vs. Multiple Dockerfiles
**Choice**: Single `Dockerfile` with multiple targets.
**Alternatives considered**: `Dockerfile.api` and `Dockerfile.dashboard`.
**Rationale**: Keeping a single file reduces maintenance overhead and allows sharing the `base` and `builder` stages efficiently.

### Decision: Dependency Filtering
**Choice**: Filter `requirements.txt` using `grep` during the build process.
**Alternatives considered**: Manual splitting into `requirements.api.txt` and `requirements.dashboard.txt`.
**Rationale**: Avoids duplicating the shared core requirements (fastapi, pydantic, etc.) and keeps the root directory cleaner. We can use `grep -vE "streamlit|plotly|pandas|matplotlib" requirements.txt > reqs_api.txt`.

## Data Flow

    [Build Engine]
         │
    [base-python]  (Stage 1: Common environment)
         │
    ┌────┴────┐
    │         │
[api-build] [dash-build] (Stage 2: Selective pip install)
    │         │
[api-final] [dash-final] (Stage 3: Distroless-like runtime)

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `Dockerfile` | Modify | Total refactor to use `AS base`, `AS api`, and `AS dashboard`. |
| `docker-compose.yml` | Modify | Set `build: { target: api }` for the `app` service and `build: { target: dashboard }` for the new `dashboard` service. |
| `requirements.txt` | Read | Source of truth for all requirements, used with filters. |

## Interfaces / Contracts

The `api` target **MUST** run the FastAPI app:
```bash
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

The `dashboard` target **MUST** run Streamlit:
```bash
CMD ["streamlit", "run", "dashboard/app.py", "--server.port", "8501"]
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Image Size | API Image size | `docker build --target api -t MM-api . && docker images | grep MM-api` |
| Connectivity | API Endpoint | `curl http://localhost:8000/health` inside the container. |
| Connectivity | Dashboard | Verify port 8501 is reachable and Streamlit UI loads. |

## Migration / Rollout

No data migration required. Users will need to run `docker compose build --no-cache` to see the results.

## Open Questions

- [ ] Will `graphiti-core` pull in heavy ML libraries (torch/tensorflow) even in the API? (If so, we might need a more aggressive filter).
