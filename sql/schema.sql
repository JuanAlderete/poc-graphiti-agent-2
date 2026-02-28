-- =============================================================================
-- NOVOLABS AI ENGINE - Schema v2.0
-- Cambios vs v1.0:
--   - metadata JSONB enriquecida con campos de clasificación semántica
--   - Índices GIN para filtros avanzados por topics, domain, emotion
--   - used_count y last_used_at en metadata (reemplaza tabla used_sources separada)
--   - Neo4j es OPCIONAL: graphiti_episode_id se mantiene pero no es crítico
-- =============================================================================

-- -----------------------------------------------------------------------------
-- EXTENSIONES
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------------------------
-- DOCUMENTOS
-- Representa una fuente completa (transcripción, podcast, sesión, etc.)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title                TEXT NOT NULL,
    filename             TEXT,
    source_type          TEXT NOT NULL DEFAULT 'unknown',
    -- Valores posibles: llamada_venta | sesion_grupal | podcast | masterclass | email | otro
    
    graphiti_episode_id  TEXT,           -- Vinculación con Neo4j (OPCIONAL, puede ser NULL)
    group_id             TEXT,           -- Clasificación por dominio: marketing | ventas | producto | metodologia
    
    -- Metadata del documento completo
    metadata             JSONB NOT NULL DEFAULT '{}',
    -- Estructura esperada:
    -- {
    --   "edition":        14,
    --   "duration_min":   45,
    --   "alumno_id":      "uuid-o-nombre",
    --   "speaker_role":   "fundador|alumno|mentor|closer",
    --   "recording_date": "2026-02-15",
    --   "is_deleted":     false
    -- }
    
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- CHUNKS
-- Fragmentos de texto de un documento, con embedding vectorial y metadata rica
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content      TEXT NOT NULL,
    embedding    vector(1536),   -- OpenAI text-embedding-3-small

    -- Metadata semántica enriquecida (clasificada en ingesta por TaxonomyManager)
    metadata     JSONB NOT NULL DEFAULT '{}',
    -- Estructura completa esperada:
    -- {
    --   -- Clasificación de fuente
    --   "source_type":     "llamada_venta|sesion_grupal|podcast|masterclass",
    --   "speaker_role":    "fundador|alumno|mentor|closer",
    --   
    --   -- Clasificación semántica
    --   "topics":          ["validacion", "objeciones", "pricing"],
    --   "content_level":   2,          -- 1=básico, 2=intermedio, 3=avanzado, 4=experto
    --   "emotion":         "miedo|frustracion|win|neutral|motivacion",
    --   "domain":          "marketing|ventas|producto|metodologia",
    --   
    --   -- Contexto del documento
    --   "edition":         14,
    --   "alumno_id":       "...",
    --   "fecha":           "2026-02-15",
    --   
    --   -- Control de diversidad (actualizado en cada uso)
    --   "used_count":      0,
    --   "last_used_at":    null,
    --   
    --   -- Soft delete
    --   "is_deleted":      false
    -- }

    chunk_index  INTEGER NOT NULL,   -- Posición del chunk dentro del documento
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- CONTENIDO GENERADO
-- Piezas producidas por los agentes (reels, historias, emails, ads)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS generated_content (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id          UUID NOT NULL,                     -- Identifica la ejecución semanal
    chunk_id        UUID REFERENCES chunks(id),        -- Fuente usada para generar
    document_id     UUID REFERENCES documents(id),     -- Documento fuente (desnormalizado)
    
    content_type    TEXT NOT NULL,
    -- Valores posibles: reel_cta | reel_lead_magnet | historia | email | ads
    
    content         JSONB NOT NULL,
    -- Estructura varía por content_type, ejemplos:
    -- reel_cta:  { hook, script, cta, sugerencias_grabacion, copy }
    -- historia:  { tipo, slides:[{texto, sugerencia_visual}], cta_final }
    -- email:     { asunto, preheader, cuerpo, cta, ps }
    -- ads:       { headlines:[3], descripciones:[2], copy, cta, sugerencia_visual }

    -- Métricas de QA
    qa_passed       BOOLEAN,
    qa_reason       TEXT,           -- Motivo de falla si qa_passed = false
    retry_count     INTEGER NOT NULL DEFAULT 0,
    
    -- Costo de generación
    cost_usd        NUMERIC(10, 6),
    model_used      TEXT,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    
    -- Estado en Notion (se actualiza cuando se publica)
    notion_page_id  TEXT,
    notion_url      TEXT,
    notion_status   TEXT DEFAULT 'Pendiente',
    -- Valores: Pendiente | Propuesta | Aprobada | Publicada | Rechazada | QA_Failed
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- WEEKLY RUNS
-- Log de cada ejecución semanal del orquestador
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weekly_runs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_date            DATE NOT NULL,
    
    -- Resultados
    pieces_generated    INTEGER NOT NULL DEFAULT 0,
    pieces_failed       INTEGER NOT NULL DEFAULT 0,
    pieces_qa_passed    INTEGER NOT NULL DEFAULT 0,
    pieces_qa_failed    INTEGER NOT NULL DEFAULT 0,
    
    -- Costos
    total_cost_usd      NUMERIC(10, 4),
    
    -- Estado
    status              TEXT NOT NULL DEFAULT 'running',
    -- Valores: running | completed | failed | partial
    
    error_message       TEXT,
    notion_run_url      TEXT,   -- URL del registro en Notion Weekly Runs
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

-- -----------------------------------------------------------------------------
-- FEEDBACK
-- Calificaciones leídas desde Notion para el feedback loop (Fase 3)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feedback (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    generated_content_id UUID REFERENCES generated_content(id),
    notion_page_id      TEXT,
    
    rating              INTEGER CHECK (rating BETWEEN 1 AND 5),
    notes               TEXT,
    
    -- Para análisis por formato y fuente
    content_type        TEXT,
    source_document_id  UUID REFERENCES documents(id),
    
    rated_at            TIMESTAMPTZ,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- TOKEN TRACKING
-- Registro granular de costos por operación (existía, se mantiene y mejora)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS token_usage (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id       UUID,                   -- Puede ser NULL para operaciones fuera de un run
    operation    TEXT NOT NULL,          -- ingest | generate | qa | search_intent | embedding
    model        TEXT NOT NULL,
    tokens_in    INTEGER NOT NULL DEFAULT 0,
    tokens_out   INTEGER NOT NULL DEFAULT 0,
    cost_usd     NUMERIC(10, 6) NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- ÍNDICES
-- =============================================================================

-- Búsqueda vectorial (pgvector)
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Filtros semánticos por metadata (GIN para JSONB y arrays)
CREATE INDEX IF NOT EXISTS idx_chunks_topics
    ON chunks USING GIN ((metadata->'topics'));

CREATE INDEX IF NOT EXISTS idx_chunks_domain
    ON chunks ((metadata->>'domain'));

CREATE INDEX IF NOT EXISTS idx_chunks_content_level
    ON chunks ((metadata->>'content_level'));

CREATE INDEX IF NOT EXISTS idx_chunks_emotion
    ON chunks ((metadata->>'emotion'));

CREATE INDEX IF NOT EXISTS idx_chunks_source_type
    ON chunks ((metadata->>'source_type'));

-- Control de diversidad: filtrar chunks usados recientemente
CREATE INDEX IF NOT EXISTS idx_chunks_last_used
    ON chunks ((metadata->>'last_used_at'));

CREATE INDEX IF NOT EXISTS idx_chunks_used_count
    ON chunks (((metadata->>'used_count')::INTEGER));

-- FKs frecuentes
CREATE INDEX IF NOT EXISTS idx_chunks_document_id
    ON chunks (document_id);

CREATE INDEX IF NOT EXISTS idx_generated_run_id
    ON generated_content (run_id);

CREATE INDEX IF NOT EXISTS idx_generated_content_type
    ON generated_content (content_type);

CREATE INDEX IF NOT EXISTS idx_generated_qa_passed
    ON generated_content (qa_passed);

CREATE INDEX IF NOT EXISTS idx_documents_group_id
    ON documents (group_id);

CREATE INDEX IF NOT EXISTS idx_documents_source_type
    ON documents (source_type);

-- =============================================================================
-- FUNCIONES AUXILIARES
-- =============================================================================

-- Actualiza updated_at automáticamente en documentos
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

-- Marca un chunk como usado (actualiza used_count y last_used_at en metadata)
-- Uso: SELECT mark_chunk_used('uuid-del-chunk');
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