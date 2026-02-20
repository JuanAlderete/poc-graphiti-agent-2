-- Enable extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Clean up existing (Cascade to remove dependencies)
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS chunks CASCADE;
DROP TABLE IF EXISTS documents CASCADE;

-- ─── 1. Documents ─────────────────────────────────────────────────────────────
CREATE TABLE documents (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title               TEXT NOT NULL,
    source              TEXT NOT NULL,
    content             TEXT NOT NULL,
    metadata            JSONB DEFAULT '{}'::jsonb,
    -- Neo4j episode UUID devuelto por Graphiti (null hasta Fase 2)
    graphiti_episode_id TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Índice general sobre todo el JSONB (para queries ad-hoc)
CREATE INDEX idx_documents_metadata     ON documents USING GIN (metadata);
CREATE INDEX idx_documents_created_at   ON documents (created_at DESC);

-- Índice para deduplicación por hash de contenido (O(log n))
CREATE INDEX idx_documents_content_hash
    ON documents ((metadata->>'content_hash'));

-- Índice parcial para get_documents_missing_from_graph()
-- Solo indexa docs donde graph_ingested NO es true → mucho más pequeño
CREATE INDEX idx_documents_not_graph_ingested
    ON documents ((metadata->>'graph_ingested'))
    WHERE (metadata->>'graph_ingested') IS DISTINCT FROM 'true';

-- Índice por filename para lookups directos desde el dashboard
CREATE INDEX idx_documents_filename
    ON documents ((metadata->>'filename'));


-- ─── 2. Chunks ────────────────────────────────────────────────────────────────
CREATE TABLE chunks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    embedding       vector(1536),   -- OpenAI=1536 / Gemini=768 (ajustado en init_db)
    chunk_index     INTEGER NOT NULL,
    token_count     INTEGER,        -- pre-calculado en ingesta para estimar costos Fase 2
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    -- Full Text Search generado automáticamente
    content_tsvector tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

-- HNSW para ANN (Approximate Nearest Neighbor) — más rápido que IVFFlat para < 1M rows
CREATE INDEX idx_chunks_embedding     ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_chunks_tsvector      ON chunks USING GIN (content_tsvector);
CREATE INDEX idx_chunks_document_id   ON chunks (document_id);
CREATE INDEX idx_chunks_chunk_index   ON chunks (document_id, chunk_index);

-- Índice para filtrar por categoría/segmento en búsquedas filtradas
CREATE INDEX idx_chunks_category
    ON chunks ((metadata->>'category'))
    WHERE metadata->>'category' IS NOT NULL;

CREATE INDEX idx_chunks_doc_source
    ON chunks ((metadata->>'doc_source'));


-- ─── 3. Sessions & Messages ───────────────────────────────────────────────────
CREATE TABLE sessions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     TEXT,
    metadata    JSONB DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    expires_at  TIMESTAMPTZ
);

CREATE INDEX idx_sessions_user_id ON sessions (user_id);

CREATE TABLE messages (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,
    metadata    JSONB DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_messages_session_id ON messages (session_id, created_at);


-- ─── 4. Hybrid Search Function (RRF) ─────────────────────────────────────────
-- Combina Vector Search (cosine) + Full Text Search via Reciprocal Rank Fusion.
CREATE OR REPLACE FUNCTION hybrid_search(
    query_embedding  vector(1536),
    query_text       TEXT,
    match_count      INT     DEFAULT 10,
    full_text_weight FLOAT   DEFAULT 0.3,
    rrf_k            INT     DEFAULT 60
)
RETURNS TABLE (
    chunk_id    UUID,
    document_id UUID,
    content     TEXT,
    metadata    JSONB,
    score       FLOAT,
    vector_score FLOAT,
    text_score  FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    WITH vector_results AS (
        SELECT
            c.id,
            ROW_NUMBER() OVER (ORDER BY c.embedding <=> query_embedding) AS rank,
            1 - (c.embedding <=> query_embedding) AS similarity
        FROM chunks c
        ORDER BY c.embedding <=> query_embedding
        LIMIT match_count * 2
    ),
    text_results AS (
        SELECT
            c.id,
            ROW_NUMBER() OVER (
                ORDER BY ts_rank_cd(c.content_tsvector, plainto_tsquery('english', query_text)) DESC
            ) AS rank,
            ts_rank_cd(c.content_tsvector, plainto_tsquery('english', query_text)) AS similarity
        FROM chunks c
        WHERE c.content_tsvector @@ plainto_tsquery('english', query_text)
        LIMIT match_count * 2
    ),
    combined AS (
        SELECT
            COALESCE(v.id, t.id) AS id,
            COALESCE(1.0 / (rrf_k + v.rank), 0.0)
                + COALESCE(1.0 / (rrf_k + t.rank), 0.0) AS rrf_score,
            v.similarity AS v_sim,
            t.similarity AS t_sim
        FROM vector_results v
        FULL OUTER JOIN text_results t ON v.id = t.id
    )
    SELECT
        c.id         AS chunk_id,
        c.document_id,
        c.content,
        c.metadata,
        comb.rrf_score   AS score,
        comb.v_sim       AS vector_score,
        comb.t_sim       AS text_score
    FROM combined comb
    JOIN chunks c ON comb.id = c.id
    ORDER BY comb.rrf_score DESC
    LIMIT match_count;
END;
$$;


-- ─── 5. Triggers: updated_at ──────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_sessions_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();


-- ─── 6. Vista útil para el dashboard ─────────────────────────────────────────
-- Resumen por documento: cuántos chunks tiene y si fue hidratado al grafo.
CREATE OR REPLACE VIEW v_document_summary AS
SELECT
    d.id,
    d.title,
    d.source,
    d.metadata->>'category'           AS category,
    d.metadata->>'detected_people'    AS detected_people,
    (d.metadata->>'graph_ingested')::boolean AS graph_ingested,
    d.graphiti_episode_id IS NOT NULL  AS has_graphiti_node,
    COUNT(c.id)                        AS chunk_count,
    SUM(c.token_count)                 AS total_tokens,
    d.created_at,
    d.updated_at
FROM documents d
LEFT JOIN chunks c ON c.document_id = d.id
GROUP BY d.id, d.title, d.source, d.metadata, d.graphiti_episode_id, d.created_at, d.updated_at;