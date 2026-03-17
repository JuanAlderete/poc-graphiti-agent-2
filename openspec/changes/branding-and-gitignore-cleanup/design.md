# Design: Branding Update and Gitignore Cleanup

## Branding Migration Map

### Renaming Strategy
- **Text Replacements**:
    - `Novolabs` -> `MarketingMaker`
    - `novolabs` -> `marketingmaker`
    - `NOVOLABS` -> `MARKETINGMAKER`

### Affected Components
- **API (FastAPI)**:
    - `api/main.py`: Update app title and startup logs.
    - `api/models/`: Update default `organization_id`.
    - `api/routes/config_check.py`: Update success message branding.
- **Monitoring (Telegram)**:
    - `monitoring/telegram.py`: Update alert headers.
- **Orchestrator**:
    - `orchestrator/`: Update any organizational prefixes in logs or jobs.
- **Infrastructure (Docker)**:
    - `docker-compose.yml`: Update service and container names (`novolabs_postgres` -> `marketingmaker_postgres`).
- **Scripts**:
    - `scripts/reset_db.sh`: Update database and user defaults.
- **Documentation**:
    - `README.md`: Update headers, structure, and descriptions.
    - `ROADMAP.md`: Update all references.
    - `n8n/README.md`: Update workflow and variable names.

## Gitignore Refactor Design

### Section Structure
1. **Core / Global**: Python, OS (macOS/Windows/Linux), VS Code/IDE.
2. **Virtual Environments**: venv, .env.
3. **Caches**: __pycache__, .pytest_cache, .cache, .mypy_cache.
4. **Distribution / Build**: build/, dist/, *.egg-info.
5. **Project Specific Infrastructure (Local Only)**:
    - `logs/`
    - `temp/`, `tmp/`
    - `documents/` (local data)
    - `.agents/`, `.atl/`
6. **Databases**: *.db, *.sqlite, pgdata/.
7. **Secrets**: .env, *.key, *.pem, secrets/.
8. **Tool Artifacts**: repomix-output.*.

## Migration Rationale
Renaming container and database names improves brand consistency. Using a structured `.gitignore` prevents future leakage of sensitive or temporary files and keeps the repository clean.
