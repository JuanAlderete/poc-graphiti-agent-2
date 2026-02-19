-- Enable extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Clean up existing (Cascade to remove dependencies/functions)
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS chunks CASCADE;
DROP TABLE IF EXISTS documents CASCADE;

-- 1. Documents Table
-- Represents the source file or logical unit.
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    content TEXT NOT NULL, -- Full original content (optional, or stored elsewhere)
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_documents_metadata ON documents USING GIN (metadata);
CREATE INDEX idx_documents_created_at ON documents (created_at DESC);

-- 2. Chunks Table
-- Stores the actual vectors and searchable text parts.
CREATE TABLE chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding vector(1536), -- Dimension depends on model (OpenAI=1536)
    chunk_index INTEGER NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    token_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Generated column for Full Text Search (Postgres 12+)
    -- Automatically updates when content changes.
    content_tsvector tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

-- HNSW Index for fast approximate nearest neighbor search
-- 'm' and 'ef_construction' can be tuned. m=16, ef_construction=64 are defaults.
CREATE INDEX idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);

-- GIN Index for Full Text Search
CREATE INDEX idx_chunks_tsvector ON chunks USING GIN (content_tsvector);

-- Foreign Key Index
CREATE INDEX idx_chunks_document_id ON chunks (document_id);
CREATE INDEX idx_chunks_chunk_index ON chunks (document_id, chunk_index);

-- 3. Sessions & Messages (Agent State)
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id TEXT, -- External User ID
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

CREATE INDEX idx_sessions_user_id ON sessions (user_id);

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_messages_session_id ON messages (session_id, created_at);

-- 4. Hybrid Search Function
-- Combines Vector Search (Cosine Similarity) and Full Text Search (Rank).
CREATE OR REPLACE FUNCTION hybrid_search(
    query_embedding vector(1536),
    query_text TEXT,
    match_count INT DEFAULT 10,
    full_text_weight FLOAT DEFAULT 0.3, -- Weight for text score (0.0 to 1.0)
    rrf_k INT DEFAULT 60 -- Constant for Reciprocal Rank Fusion
)
RETURNS TABLE (
    chunk_id UUID,
    document_id UUID,
    content TEXT,
    metadata JSONB,
    score FLOAT,
    vector_score FLOAT,
    text_score FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    WITH vector_results AS (
        SELECT 
            c.id, 
            ROW_NUMBER() OVER (ORDER BY c.embedding <=> query_embedding) AS rank,
            1 - (c.embedding <=> query_embedding) as similarity
        FROM chunks c
        ORDER BY c.embedding <=> query_embedding
        LIMIT match_count * 2
    ),
    text_results AS (
        SELECT 
            c.id, 
            ROW_NUMBER() OVER (ORDER BY ts_rank_cd(c.content_tsvector, plainto_tsquery('english', query_text)) DESC) AS rank,
            ts_rank_cd(c.content_tsvector, plainto_tsquery('english', query_text)) as similarity
        FROM chunks c
        WHERE c.content_tsvector @@ plainto_tsquery('english', query_text)
        LIMIT match_count * 2
    ),
    combined AS (
        SELECT
            COALESCE(v.id, t.id) AS id,
            COALESCE(1.0 / (rrf_k + v.rank), 0.0) + COALESCE(1.0 / (rrf_k + t.rank), 0.0) AS rrf_score,
            v.similarity AS v_sim,
            t.similarity AS t_sim
        FROM vector_results v
        FULL OUTER JOIN text_results t ON v.id = t.id
    )
    SELECT
        c.id AS chunk_id,
        c.document_id,
        c.content,
        c.metadata,
        comb.rrf_score AS score,
        comb.v_sim AS vector_score,
        comb.t_sim AS text_score
    FROM combined comb
    JOIN chunks c ON comb.id = c.id
    ORDER BY comb.rrf_score DESC
    LIMIT match_count;
END;
$$;

-- 5. Auto-update Trigger for updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_sessions_updated_at BEFORE UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
