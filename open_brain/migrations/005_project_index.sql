-- Migration 005: GIN index on metadata->'project'
-- Supports efficient project-scoped queries across all tool surfaces.

CREATE INDEX IF NOT EXISTS idx_memories_project
    ON memories USING gin ((metadata -> 'project'));
