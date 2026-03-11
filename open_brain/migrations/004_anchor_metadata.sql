-- Migration 004: Anchor metadata columns on epochs table
-- Run: python3 -m open_brain.cli migrate open_brain/migrations/004_anchor_metadata.sql
--
-- Adds blockchain anchor tracking to sealed epochs.
-- Chain-agnostic: anchor_metadata JSONB stores proof_type-specific data
-- (ethereum, ots, rfc3161).

ALTER TABLE epochs ADD COLUMN IF NOT EXISTS anchored_at TEXT;
ALTER TABLE epochs ADD COLUMN IF NOT EXISTS anchor_metadata JSONB;

-- Index for finding unanchored epochs efficiently.
CREATE INDEX IF NOT EXISTS idx_epochs_unanchored
    ON epochs (anchored_at) WHERE anchored_at IS NULL;

-- ob_writer needs UPDATE permission for record_anchor().
GRANT UPDATE ON epochs TO ob_writer;
