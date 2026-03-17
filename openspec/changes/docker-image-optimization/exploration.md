# Exploration: Docker Image Optimization

## Current State

The current Docker image is approximately **2GB** in size. A preliminary analysis of the `Dockerfile` and `requirements.txt` reveals the following:

- **Base Image:** `python:3.13-slim` is used. While "slim" is better than the full image, it still contains a full Debian-based Python environment.
- **Dependencies:** `requirements.txt` includes many heavy data science and UI libraries (pandas, numpy, streamlit, plotly).
- **Multi-stage Build:** Already implemented, which is a good baseline, but it installs everything into a single stage.
- **Build Context:** The `.dockerignore` seems adequate, but the inclusion of all libraries in one image is the main source of bloat.

## Affected Areas

- `Dockerfile` — Base image, build steps, and potentially splitting into multiple targets.
- `requirements.txt` — Dependency pruning or splitting by service.
- `docker-compose.yml` — Configuring separate images for API and Dashboard.

## Approaches

### 1. Split API and Dashboard Services
- **Description:** Create two separate `pip install` steps and two final images. One for the **API** (lightweight, no streamlit/plotly) and one for the **Dashboard**.
- **Pros:** The production API image will be much smaller (likely <500MB). Logical separation of concerns.
- **Cons:** Slightly more complex setup.
- **Effort:** Medium

### 2. Alpine-based Build (Selective)
- **Description:** Use `python:3.13-alpine` as a base.
- **Pros:** Radical size reduction.
- **Cons:** High risk of build failures due to missing shared libraries (libpq, musl vs glibc), especially for numpy/pandas.
- **Effort:** High (Risk-heavy)

### 3. Layer Consolidation and Cleaning
- **Description:** Consolidate layers and ensure all caches (`apt`, `pip`) are deleted within the same layer they are created.
- **Pros:** Incremental improvement (~50-100MB).
- **Cons:** Not enough to reach "lightweight" status.
- **Effort:** Low

## Recommendation

I recommend **Approach 1: Split API and Dashboard**. 
Most of the current "bloat" is likely only needed for the Streamlit Dashboard. The core API only needs `fastapi` and the DB drivers. By splitting these, the API can run on a very small image.

## Risks

- **Import Conflicts:** If some modules are shared, we must ensure they don't accidentally pull in heavy dependencies from the other "half" of the project.

## Ready for Proposal
Yes — I have enough information to propose a split Dockerfile strategy.
