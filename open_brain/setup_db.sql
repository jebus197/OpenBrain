-- Open Brain schema
-- Run as admin: psql open_brain -f open_brain/setup_db.sql

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -------------------------------------------------------------------
-- Main table
-- -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS memories (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_text        TEXT NOT NULL,
    embedding       vector(384) NOT NULL,
    embedding_model TEXT NOT NULL DEFAULT 'BAAI/bge-small-en-v1.5',
    content_hash    TEXT,              -- SHA-256 of canonical {raw_text, metadata}
    previous_hash   TEXT,              -- Hash chain link to predecessor
    signature       TEXT,              -- Ed25519 signature (hex) over canonical content
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -------------------------------------------------------------------
-- Indexes
-- -------------------------------------------------------------------

-- Semantic search (HNSW, cosine distance)
CREATE INDEX IF NOT EXISTS idx_memories_embedding
    ON memories USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Metadata filtering
CREATE INDEX IF NOT EXISTS idx_memories_source_agent
    ON memories USING gin ((metadata -> 'source_agent'));

CREATE INDEX IF NOT EXISTS idx_memories_memory_type
    ON memories USING gin ((metadata -> 'memory_type'));

CREATE INDEX IF NOT EXISTS idx_memories_action_status
    ON memories USING gin ((metadata -> 'action_status'));

CREATE INDEX IF NOT EXISTS idx_memories_area
    ON memories USING gin ((metadata -> 'area'));

-- Temporal ordering
CREATE INDEX IF NOT EXISTS idx_memories_created_at
    ON memories (created_at DESC);

-- Hash chain integrity
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_content_hash
    ON memories (content_hash) WHERE content_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_memories_previous_hash
    ON memories (previous_hash) WHERE previous_hash IS NOT NULL;

-- -------------------------------------------------------------------
-- Role grants (append-only: no DELETE)
-- -------------------------------------------------------------------

GRANT USAGE ON SCHEMA public TO ob_reader;
GRANT SELECT ON memories TO ob_reader;

GRANT USAGE ON SCHEMA public TO ob_writer;
GRANT SELECT, INSERT, UPDATE ON memories TO ob_writer;
