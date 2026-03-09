-- Migration 002: Add Ed25519 signature column
-- Idempotent — safe to run on databases that already have the column.
--
-- The signature is an Ed25519 signature (RFC 8032) over the same
-- canonical JSON used for content_hash. It provides cryptographic
-- proof of origin: which node's private key signed this memory.
-- Pre-migration memories will have NULL signatures (unsigned).

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'signature'
    ) THEN
        ALTER TABLE memories ADD COLUMN signature TEXT;
    END IF;
END $$;
