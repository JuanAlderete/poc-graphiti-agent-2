# Exploration: SQL Syntax Error During Ingestion

## The Problem
When uploading files in the Dashboard for indexing, the user encounters a Postgres error:
`Error: syntax error at or near "SELECT"`

## Root Cause Analysis
During document ingestion, the code calls `ingest_files` which in turn calls `DatabasePool.init_db()` to ensure the database schema is initialized.

In `agent/db_utils.py`, the `init_db` method attempts to create an index:
```sql
CREATE INDEX IF NOT EXISTS idx_chunks_entity_types
    ON chunks USING GIN (
        (SELECT jsonb_agg(e->>'type')
         FROM jsonb_array_elements(metadata->'entities') AS e)
    );
```

PostgreSQL does not allow the use of subqueries (such as `SELECT ...`) directly within the expression of a `CREATE INDEX` statement unless wrapped in an `IMMUTABLE` function. This causes the `syntax error at or near "SELECT"` when the dashboard attempts to initialize the database upon file upload.

Wait, why did this work before? It likely didn't work and this index was newly added in a recent "v3.0" update that added entity extraction to the chunks.

## Potential Solutions
1. Wrap the logic in an `IMMUTABLE` PL/pgSQL function and index the result of that function.
2. Rely on the already existing `idx_chunks_entities` index (which is `ON chunks USING GIN ((metadata->'entities'))`). This index already allows efficient querying by entity type using the JSONB containment operator (`@> '[{"type": "Concept"}]'`).

Solution 2 is better because it avoids complexity and utilizes the existing GIN index on the `entities` array.
