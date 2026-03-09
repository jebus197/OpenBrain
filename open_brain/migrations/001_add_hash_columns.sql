-- Migration 001: Add content_hash and previous_hash columns
-- Run: psql open_brain -f open_brain/migrations/001_add_hash_columns.sql
--
-- Safe to run multiple times (IF NOT EXISTS guards).
-- Existing memories will have NULL content_hash and previous_hash.
-- New memories created after this migration will have computed hashes.

ALTER TABLE memories ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS previous_hash TEXT;

-- Content hash should be unique (each memory has distinct content)
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_content_hash
    ON memories (content_hash) WHERE content_hash IS NOT NULL;

-- Previous hash index for chain traversal
CREATE INDEX IF NOT EXISTS idx_memories_previous_hash
    ON memories (previous_hash) WHERE previous_hash IS NOT NULL;
