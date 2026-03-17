# Docker Optimization Specification

## Purpose

Define the requirements for reducing the Docker image footprint by separating the core API from the UI-heavy Dashboard.

## Requirements

### Requirement: Multi-target Build Strategy
The system **MUST** use a multi-stage Dockerfile that provides separate targets for the API and the Dashboard.
- The `api` target **SHALL** only contain dependencies required for the FastAPI engine and database interaction.
- The `dashboard` target **SHALL** contain all dependencies including Streamlit and data visualization libs.

#### Scenario: Building and Running the API
- **GIVEN** a refactored Dockerfile with an `api` target.
- **WHEN** running `docker build --target api -t marketingmaker-api .`.
- **THEN** the build completes successfully and the image contains no Streamlit-related binaries.

#### Scenario: Building and Running the Dashboard
- **GIVEN** a refactored Dockerfile with a `dashboard` target.
- **WHEN** running `docker build --target dashboard -t marketingmaker-dashboard .`.
- **THEN** the build completes successfully and the dashboard starts on port 8501.

### Requirement: Image Size Optimization
The final production image for the `api` target **MUST** be smaller than 500MB.

#### Scenario: Verifying API Image Size
- **GIVEN** a successful build of the `api` target.
- **WHEN** checking the image size with `docker images`.
- **THEN** the size reported **MUST** be less than 500MB.

### Requirement: Docker Compose Integration
The `docker-compose.yml` **MUST** be updated to associate each service with its specific build target.

#### Scenario: Orchestration with Compose
- **GIVEN** an updated `docker-compose.yml` with `build: { context: ., target: api }`.
- **WHEN** running `docker compose up app`.
- **THEN** the system pulls/builds only the `api` target and the API stays healthy.
