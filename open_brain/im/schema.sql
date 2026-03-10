-- Open Brain IM schema — SQLite WAL mode
-- Pragma: journal_mode=WAL, busy_timeout=5000, foreign_keys=ON

CREATE TABLE IF NOT EXISTS channels (
    channel_id    TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    metadata      TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    msg_id          TEXT PRIMARY KEY,
    channel_id      TEXT NOT NULL REFERENCES channels(channel_id),
    sender          TEXT NOT NULL,
    content         TEXT NOT NULL,
    msg_type        TEXT NOT NULL DEFAULT 'post',
    correlation_id  TEXT,
    content_hash    TEXT NOT NULL,
    signature       TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expires_at      TEXT,
    metadata        TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS delivery_receipts (
    receipt_id    TEXT PRIMARY KEY,
    msg_id        TEXT NOT NULL REFERENCES messages(msg_id),
    recipient     TEXT NOT NULL,
    delivered_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    read_at       TEXT
);

CREATE TABLE IF NOT EXISTS retention_policy (
    channel_id    TEXT PRIMARY KEY REFERENCES channels(channel_id),
    max_age_days  INTEGER DEFAULT 90,
    max_count     INTEGER DEFAULT 10000
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_messages_channel
    ON messages(channel_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_sender
    ON messages(sender, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_correlation
    ON messages(correlation_id) WHERE correlation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_messages_expires
    ON messages(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_receipts_msg
    ON delivery_receipts(msg_id);
CREATE INDEX IF NOT EXISTS idx_receipts_recipient
    ON delivery_receipts(recipient, delivered_at DESC);
