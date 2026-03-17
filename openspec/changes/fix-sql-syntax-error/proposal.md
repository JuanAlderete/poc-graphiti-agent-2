# Proposal: Fix SQL Syntax Error During Database Initialization

## Intent
The intent of this change is to fix the `syntax error at or near "SELECT"` error that blocks file ingestion by correcting an invalid `CREATE INDEX` statement in the database initialization script.

## Problem Statement
The method `DatabasePool.init_db()` located in `agent/db_utils.py` contains the following index creation statement:
```sql
CREATE INDEX IF NOT EXISTS idx_chunks_entity_types
    ON chunks USING GIN (
        (SELECT jsonb_agg(e->>'type')
         FROM jsonb_array_elements(metadata->'entities') AS e)
    );
```
PostgreSQL strictly prohibits using subqueries inside a `CREATE INDEX` expression. When the dashboard attempts to index uploaded files, it calls `init_db()` which executes this raw SQL, immediately throwing the syntax error.

Additionally, the dashboard's "Ingest existing directory" function hits a Python error: `name 'ingest_directory' is not defined`. This occurs because `poc/run_poc.py` attempts to call `ingest_directory()` but lacks the import statement: `from ingestion.ingest import ingest_directory`.

## Proposed Solution
1. Remove the invalid `idx_chunks_entity_types` index creation statement entirely from `agent/db_utils.py`. Filtering chunks by entity type can still be done efficiently using the accompanying index `idx_chunks_entities` (`CREATE INDEX IF NOT EXISTS idx_chunks_entities ON chunks USING GIN ((metadata->'entities'));`).
2. Add the missing import statement `from ingestion.ingest import ingest_directory` to `poc/run_poc.py`.

## Scope
### In Scope
- Modify `agent/db_utils.py` to remove the invalid index creation statement for `idx_chunks_entity_types`.

### Out of Scope
- No other changes to the database schema.
- No changes to existing ingestion workflows outside of removing the failing SQL snippet.
