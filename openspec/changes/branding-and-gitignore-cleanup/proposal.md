# Proposal: Branding Update and Gitignore Cleanup

## Intent
Rename the project branding from 'Novolabs' to 'MarketingMaker' to align with the new brand identity. Simultaneously, optimize the `.gitignore` to remove redundant entries and ensure all temporary, environment, and project-specific files are correctly ignored.

## Scope
### Branding Update
- **API**: Update titles, logs, and default organizational IDs in `api/main.py`, `api/models/`, and `api/routes/`.
- **Dashboard**: Update branding in the Streamlit app.
- **n8n**: Update workflow names and documentation.
- **Documentation**: Update `README.md`, `ROADMAP.md`, and other project docs.
- **Scripts**: Update reset scripts and database default names.
- **Docker**: Update container names and environment examples.

### Gitignore Cleanup
- Remove redundant/duplicate entries (e.g., multiple `.env` and `venv` sections).
- Consolidate project-specific ignores.
- Ensure tool-specific ignores (VS Code, cursor, agents) are complete.

## Approach
1. **Search & Replace**: Perform a case-sensitive and case-insensitive search for 'Novolabs' and replace with 'MarketingMaker' (preserving case where appropriate, e.g., `novolabs` -> `marketingmaker`).
2. **Gitignore Refactor**: Rewrite `.gitignore` using a standard template (e.g., Python + VS Code) and append project-specific needs.
3. **Manual Review**: Verify that database names and container names in `docker-compose.yml` are updated.

## Risks
- **Breaking Changes**: Updating database or container names might require users to re-run setup scripts or migrate data.
- **Missed References**: Hardcoded strings in third-party integrations (like Notion IDs if named after the brand) might break if not handled.
- **Git State**: Changing `.gitignore` for files already tracked won't untrack them automatically.

## Rollback Plan
- Revert changes using Git: `git checkout .`.
- If database names were changed, manually rename them back or use backup.
