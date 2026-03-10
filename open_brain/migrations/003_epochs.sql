-- Migration 003: Epochs table for Merkle-tree batch verification
-- Run: psql open_brain -f open_brain/migrations/003_epochs.sql
--
-- Safe to run multiple times (IF NOT EXISTS guards).
-- Each epoch groups memories by time window and stores the Merkle root.

CREATE TABLE IF NOT EXISTS epochs (
    epoch_id        TEXT PRIMARY KEY,
    window_start    TEXT NOT NULL,
    window_end      TEXT NOT NULL,
    merkle_root     TEXT NOT NULL,
    memory_count    INTEGER NOT NULL,
    leaf_hashes     JSONB NOT NULL,       -- ordered list of content_hash values
    previous_epoch_root TEXT NOT NULL,    -- chain link to prior epoch
    sealed_at       TEXT NOT NULL,        -- ISO 8601 timestamp
    sealed_by       TEXT NOT NULL,        -- node_id that sealed
    UNIQUE (window_start, window_end)
);

-- Query epochs by time range.
CREATE INDEX IF NOT EXISTS idx_epochs_window
    ON epochs (window_start, window_end);

-- Look up epochs by Merkle root (verification queries).
CREATE INDEX IF NOT EXISTS idx_epochs_merkle_root
    ON epochs (merkle_root);

-- Grant read access to ob_reader, write access to ob_writer.
GRANT SELECT ON epochs TO ob_reader;
GRANT SELECT, INSERT ON epochs TO ob_writer;
