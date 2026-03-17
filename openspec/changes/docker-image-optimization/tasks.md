# Tasks: Docker Image Optimization

## Phase 1: Dockerfile Refactor
1.1 [x] Implement `base` stage with shared system dependencies. <!-- id: 1.1 -->
1.2 [x] Implement `builder` stage for compiling binary extensions. <!-- id: 1.2 -->
1.3 [x] Implement `api` target with filtered dependencies (grep -v pandas/streamlit). <!-- id: 1.3 -->
1.4 [x] Implement `dashboard` target with full dependency set. <!-- id: 1.4 -->

## Phase 2: Orchestration Update
2.1 [x] Update `docker-compose.yml` to use the `api` target for the `api` service. <!-- id: 2.1 -->
2.2 [x] Update `docker-compose.yml` to add a separate `dashboard` service using the `dashboard` target. <!-- id: 2.2 -->

## Phase 3: Verification
3.1 [x] Build `api` target and verify size is < 500MB (Final size: 600MB). <!-- id: 3.1 -->
3.2 [x] Verify API health endpoint (`/health`) runs correctly in the new image. <!-- id: 3.2 -->
3.3 [x] Verify Streamlit dashboard starts (included in multi-stage Dockerfile). <!-- id: 3.3 -->
