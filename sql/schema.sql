CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- -----------------------------------------------------------------------------
-- DOCUMENTOS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title                TEXT NOT NULL,
    filename             TEXT,
    source_type          TEXT NOT NULL DEFAULT 'unknown',
    graphiti_episode_id  TEXT,
    group_id             TEXT,
    metadata             JSONB NOT NULL DEFAULT '{}',
    -- metadata incluye: source_type, filename, content_hash, edition, alumno_id
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- CHUNKS
-- metadata JSONB v3.0 incluye:
-- {
--   "source_type":    "llamada_venta",
--   "speaker_role":   "alumno",
--   "topics":         ["validacion", "objeciones"],
--   "content_level":  2,
--   "emotion":        "frustracion",
--   "domain":         "ventas",
--   "edition":        14,
--   "used_count":     0,
--   "last_used_at":   null,
--   "is_deleted":     false,
--
--   -- NUEVO v3.0: entidades y relaciones (estilo LightRAG)
--   "entities": [
--     {"name": "Cierre de ventas", "type": "Etapa de Proceso"},
--     {"name": "Sesgo de confirmación", "type": "Concepto Psicológico"}
--   ],
--   "relationships": [
--     {"subject": "Sesgo de confirmación", "relation": "dificulta", "object": "Cierre de ventas"}
--   ]
-- }
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content      TEXT NOT NULL,
    embedding    vector(1536),   -- Cambiar a 768 si LLM_PROVIDER=ollama o gemini
    metadata     JSONB NOT NULL DEFAULT '{}',
    chunk_index  INTEGER NOT NULL,
    token_count  INTEGER DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- CONTENIDO GENERADO
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS generated_content (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id          UUID NOT NULL,
    chunk_id        UUID REFERENCES chunks(id),
    document_id     UUID REFERENCES documents(id),
    content_type    TEXT NOT NULL,
    content         JSONB NOT NULL,
    qa_passed       BOOLEAN,
    qa_reason       TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(10, 6),
    model_used      TEXT,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    notion_page_id  TEXT,
    notion_url      TEXT,
    notion_status   TEXT DEFAULT 'Pendiente',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- WEEKLY RUNS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weekly_runs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_date            DATE NOT NULL,
    pieces_generated    INTEGER NOT NULL DEFAULT 0,
    pieces_failed       INTEGER NOT NULL DEFAULT 0,
    pieces_qa_passed    INTEGER NOT NULL DEFAULT 0,
    pieces_qa_failed    INTEGER NOT NULL DEFAULT 0,
    total_cost_usd      NUMERIC(10, 4),
    status              TEXT NOT NULL DEFAULT 'running',
    error_message       TEXT,
    notion_run_url      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

-- -----------------------------------------------------------------------------
-- TOKEN USAGE
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS token_usage (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id       UUID,
    operation    TEXT NOT NULL,
    model        TEXT NOT NULL,
    tokens_in    INTEGER NOT NULL DEFAULT 0,
    tokens_out   INTEGER NOT NULL DEFAULT 0,
    cost_usd     NUMERIC(10, 6) NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- ÍNDICES — BÚSQUEDA VECTORIAL
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- =============================================================================
-- ÍNDICES — FILTROS POR METADATA (existentes v2.0)
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_chunks_topics
    ON chunks USING GIN ((metadata->'topics'));

CREATE INDEX IF NOT EXISTS idx_chunks_domain
    ON chunks ((metadata->>'domain'));

CREATE INDEX IF NOT EXISTS idx_chunks_content_level
    ON chunks ((metadata->>'content_level'));

CREATE INDEX IF NOT EXISTS idx_chunks_emotion
    ON chunks ((metadata->>'emotion'));

CREATE INDEX IF NOT EXISTS idx_chunks_last_used
    ON chunks ((metadata->>'last_used_at'));

CREATE INDEX IF NOT EXISTS idx_chunks_used_count
    ON chunks (((metadata->>'used_count')::INTEGER));

CREATE INDEX IF NOT EXISTS idx_chunks_document_id
    ON chunks (document_id);

CREATE INDEX IF NOT EXISTS idx_documents_content_hash
    ON documents ((metadata->>'content_hash'));

CREATE INDEX IF NOT EXISTS idx_generated_run_id
    ON generated_content (run_id);

-- =============================================================================
-- ÍNDICES — ENTIDADES Y RELACIONES (NUEVO v3.0 — LightRAG integration)
-- =============================================================================

-- Índice GIN sobre el array de entidades para búsqueda por nombre/tipo
-- Permite: WHERE metadata->'entities' @> '[{"name": "Cierre de ventas"}]'
CREATE INDEX IF NOT EXISTS idx_chunks_entities
    ON chunks USING GIN ((metadata->'entities'));

-- Índice GIN sobre relaciones
-- Permite: WHERE metadata->'relationships' @> '[{"subject": "X"}]'
CREATE INDEX IF NOT EXISTS idx_chunks_relationships
    ON chunks USING GIN ((metadata->'relationships'));

-- Índice para búsqueda de texto parcial en nombres de entidades
-- Permite: WHERE metadata::text ILIKE '%Cierre de ventas%'
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_fulltext
    ON chunks USING gin (to_tsvector('spanish', metadata::text));

-- =============================================================================
-- FUNCIONES AUXILIARES
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Marca un chunk como usado (diversity tracking)
CREATE OR REPLACE FUNCTION mark_chunk_used(p_chunk_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE chunks
    SET metadata = metadata || jsonb_build_object(
        'used_count',   COALESCE((metadata->>'used_count')::INTEGER, 0) + 1,
        'last_used_at', NOW()::TEXT
    )
    WHERE id = p_chunk_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- VISTAS ANALÍTICAS (NUEVO v3.0)
-- =============================================================================

-- Vista: entidades más frecuentes en el corpus
-- Útil para el dashboard y para el Search Intent Generator
CREATE OR REPLACE VIEW v_entity_stats AS
SELECT
    e->>'name'  AS entity_name,
    e->>'type'  AS entity_type,
    COUNT(*)    AS chunk_count,
    COUNT(DISTINCT c.document_id) AS document_count
FROM chunks c,
     jsonb_array_elements(metadata->'entities') AS e
WHERE jsonb_array_length(metadata->'entities') > 0
  AND metadata->>'is_deleted' != 'true'
GROUP BY e->>'name', e->>'type'
ORDER BY chunk_count DESC;

-- Vista: resumen de documentos con conteo de entidades
CREATE OR REPLACE VIEW v_document_summary AS
SELECT
    d.id,
    d.title,
    d.filename AS source,
    d.created_at,
    COUNT(c.id) AS chunk_count,
    SUM(c.token_count) AS total_tokens,
    (d.metadata->>'graph_ingested')::boolean AS graph_ingested,
    (d.graphiti_episode_id IS NOT NULL) AS has_graphiti_node,
    -- Total de entidades únicas en este documento
    (
        SELECT COUNT(DISTINCT e->>'name')
        FROM chunks c2,
             jsonb_array_elements(c2.metadata->'entities') AS e
        WHERE c2.document_id = d.id
    ) AS unique_entity_count
FROM documents d
LEFT JOIN chunks c ON c.document_id = d.id
GROUP BY d.id, d.title, d.filename, d.created_at, d.metadata, d.graphiti_episode_id
ORDER BY d.created_at DESC;