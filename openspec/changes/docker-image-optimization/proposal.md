# Proposal: Docker Image Optimization via Service Splitting

## Intent

The current Docker image is ~2GB, which causes slow deployment cycles and wastes storage. The goal is to reduce the production API image size to <500MB by extracting heavy dashboard-only dependencies (Streamlit, Plotly, Pandas) into a separate stage/image.

## Scope

### In Scope
- **Dockerfile Refactor:** Implement a multi-target build (e.g., `base`, `api-runtime`, `dashboard-runtime`).
- **Dependency Management:** Split `requirements.txt` or use selective installation in the Dockerfile to ensure the API stage only contains necessary libraries.
- **Docker Compose Update:** Configure the `app` (API) and `dashboard` services to use their respective build targets.

### Out of Scope
- Migrating to Alpine Linux (High risk due to binary dependency compatibility).
- Optimizing internal application code.
- Changing the underlying database (PostgreSQL/Neo4j) versions.

## Approach

1.  **Multi-Stage Build:**
    - `builder` stage: Installs all build-time dependencies (gcc, etc.).
    - `api-runtime` stage: Installs only `fastapi`, `asyncpg`, `pydantic`, and LLM clients.
    - `dashboard-runtime` stage: Inherits from `api-runtime` and adds `streamlit`, `plotly`, and `pandas`.
2.  **Targeted Copying:** Only copy the required source code for each service where possible (though sharing the root is usually fine if `.dockerignore` is clean).
3.  **BuildKit Caching:** Utilize `--mount=type=cache` for `pip` to speed up subsequent builds.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `Dockerfile` | Modified | Total refactor to multi-target build. |
| `requirements.txt` | Modified | Likely split into `requirements.api.txt` and `requirements.dashboard.txt`. |
| `docker-compose.yml` | Modified | Update service definitions to point to specific build targets. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Missing dependencies in API | Med | Thoroughly test the API independently after splitting. |
| Increased complication in Compose | Low | Maintain clear service names and targets. |

## Rollback Plan

Revert `Dockerfile`, `requirements.txt`, and `docker-compose.yml` to their previous versions. Since the source code is unchanged, the single-image build will still work.

## Success Criteria

- [ ] Production API image size is < 500MB.
- [ ] Both API and Dashboard services start correctly via `docker compose up`.
- [ ] No regression in application functionality.
