# Specification: Branding and Gitignore Cleanup

## Branding Update

### Scenarios

#### Scenario 1: Rename occurrences in code and docs
- **Given** The current brand name 'Novolabs' exists in titles, logs, and comments.
- **When** The renaming process is executed.
- **Then** All instances of 'Novolabs' MUST be replaced with 'MarketingMaker' (preserving case, e.g., `novolabs` -> `marketingmaker`, `NOVOLABS` -> `MARKETINGMAKER`).

#### Scenario 2: Update default configuration
- **Given** Default environment variables and database names use 'novolabs'.
- **When** The configuration is updated.
- **Then** 'novolabs' MUST be replaced with 'marketingmaker' in `docker-compose.yml`, `.env.example`, and `scripts/`.

#### Scenario 3: Update n8n workflows
- **Given** n8n workflows and documentation reference 'novolabs'.
- **When** Documentation and metadata are updated.
- **Then** Every reference MUST point to 'MarketingMaker'.

## Gitignore Cleanup

### Scenarios

#### Scenario 1: Remove redundant entries
- **Given** Multiple sections for `.env` and `venv` exist.
- **When** The `.gitignore` is refactored.
- **Then** Only one entry per type MUST remain, categorized under a clear header.

#### Scenario 2: Add missing specific ignores
- **Given** Tool-specific folders like `.agents` or `.atl` should be handled.
- **When** The `.gitignore` is updated.
- **Then** Project-specific infrastructure that MUST NOT be tracked MUST be included (e.g., local logs, temp files).

#### Scenario 3: Ignore sensitive patterns
- **Given** Credentials and keys might be present in various file extensions.
- **When** Security audits are applied to `.gitignore`.
- **Then** Patterns like `*.key`, `*.pem`, and `secrets/` MUST be consistently ignored.
