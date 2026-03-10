"""Migrate flat-file JSON IM state to SQLite.

One-shot, idempotent migration from the rolling-buffer JSON format
(tools/im_service.py) to the SQLite WAL-mode store (open_brain.im.store).

JSON state format (source):
    {
        "version": "1.0",
        "protocol": {"agents": {"cc": "cc", ...}, "max_entries": 20},
        "active_action": {"status": "...", "summary": "...", "updated_utc": "..."},
        "cc": [{"ts": "2026-03-10T16:05:17Z", "msg": "..."}, ...],
        "cx": [{"ts": "2026-03-10T15:00:00Z", "msg": "..."}, ...],
    }

Each agent key maps to a list of {ts, msg} entries (newest first).
The migration creates one IM channel per agent stream and imports
all messages with their original timestamps preserved.

Idempotency: messages are skipped if a message with the same
content_hash already exists in the target store.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from open_brain.im.store import IMStore, _compute_content_hash

logger = logging.getLogger(__name__)

# Keys in the JSON state that are NOT agent streams.
_RESERVED_KEYS = frozenset({
    "version",
    "protocol",
    "active_action",
})


def migrate_json_to_sqlite(
    json_path: Path,
    sqlite_path: Path,
    *,
    project_name: str = "default",
) -> Dict[str, int]:
    """One-shot migration from flat-file JSON state to SQLite.

    Reads the JSON state file, creates channels for each agent stream,
    imports all messages preserving timestamps and ordering.

    Args:
        json_path: Path to the JSON IM state file.
        sqlite_path: Path for the SQLite database (created if absent).
        project_name: Project identifier (used in channel metadata).

    Returns:
        {"migrated": N, "skipped": S, "channels": M}
        where N is messages imported, S is duplicates skipped, M is
        channels created.

    Raises:
        FileNotFoundError: If json_path does not exist.
        json.JSONDecodeError: If json_path is not valid JSON.

    Idempotent: skips messages whose content_hash already exists
    in the target database. Safe to run multiple times.
    """
    if not json_path.exists():
        raise FileNotFoundError(f"JSON state file not found: {json_path}")

    state = json.loads(json_path.read_text())
    store = IMStore(sqlite_path)

    # Discover agent streams: any top-level key not in _RESERVED_KEYS
    # whose value is a list.
    streams = {
        key: entries
        for key, entries in state.items()
        if key not in _RESERVED_KEYS and isinstance(entries, list)
    }

    channels_created = 0
    migrated = 0
    skipped = 0

    # Collect existing content hashes for fast dedup lookups.
    existing_hashes = _load_existing_hashes(store)

    for agent_name, entries in streams.items():
        # Create channel for this agent stream.
        store.create_channel(
            channel_id=agent_name,
            display_name=agent_name.upper(),
            metadata={"source": "json_migration", "project": project_name},
        )
        channels_created += 1

        # Entries are newest-first in the JSON. Reverse to insert in
        # chronological order so created_at ordering is natural.
        for entry in reversed(entries):
            ts = entry.get("ts", "")
            msg = entry.get("msg", "")

            if not msg:
                continue

            # The JSON format has no sender field — the stream name
            # is the recipient/channel, not the sender. We use "system"
            # as sender since the original format doesn't distinguish.
            # However, many messages start with "agent_name:" prefix
            # (e.g., "cc: session starting"). Try to extract the sender
            # from the message content.
            sender = _extract_sender(msg, list(streams.keys()))

            # Compute content hash with original timestamp.
            content_hash = _compute_content_hash(sender, msg, ts)

            if content_hash in existing_hashes:
                skipped += 1
                continue

            # Insert directly via SQL to preserve original timestamps.
            _insert_migrated_message(
                store,
                channel_id=agent_name,
                sender=sender,
                content=msg,
                content_hash=content_hash,
                created_at=ts,
            )
            existing_hashes.add(content_hash)
            migrated += 1

    # Migrate active_action as a system message if present and non-idle.
    action = state.get("active_action", {})
    if action and action.get("status") and action["status"] != "IDLE":
        _migrate_active_action(store, action, existing_hashes)
        migrated += 1

    result = {
        "migrated": migrated,
        "skipped": skipped,
        "channels": channels_created,
    }
    logger.info(
        "Migration complete: %d migrated, %d skipped, %d channels",
        migrated, skipped, channels_created,
    )
    return result


def _extract_sender(msg: str, known_agents: list[str]) -> str:
    """Try to extract the sender from message content.

    The flat-file format stores messages like "cx: API refactor complete."
    in the cc stream (cx posted to cc's stream). If the message starts
    with a known agent name followed by a colon, use that as the sender.

    Falls back to "system" if no sender prefix is detected.
    """
    for agent in known_agents:
        prefix = f"{agent}:"
        if msg.lower().startswith(prefix):
            return agent
    return "system"


def _load_existing_hashes(store: IMStore) -> set[str]:
    """Load all existing content hashes from the store for dedup."""
    import sqlite3

    hashes: set[str] = set()
    with store._conn(readonly=True) as conn:
        rows = conn.execute("SELECT content_hash FROM messages").fetchall()
        for row in rows:
            hashes.add(row["content_hash"])
    return hashes


def _insert_migrated_message(
    store: IMStore,
    *,
    channel_id: str,
    sender: str,
    content: str,
    content_hash: str,
    created_at: str,
) -> None:
    """Insert a migrated message with its original timestamp.

    Uses direct SQL rather than store.post() to preserve the original
    created_at timestamp (post() generates a new one).
    """
    import uuid

    msg_id = str(uuid.uuid4())
    meta_json = json.dumps({"migrated": True}, sort_keys=True)

    with store._conn() as conn:
        store._ensure_channel(conn, channel_id)
        conn.execute(
            "INSERT INTO messages "
            "(msg_id, channel_id, sender, content, msg_type, "
            " correlation_id, content_hash, signature, created_at, "
            " expires_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg_id,
                channel_id,
                sender,
                content,
                "post",
                None,
                content_hash,
                None,
                created_at,
                None,
                meta_json,
            ),
        )


def _migrate_active_action(
    store: IMStore,
    action: Dict[str, Any],
    existing_hashes: set[str],
) -> None:
    """Migrate the active_action as a system message in the 'system' channel."""
    status = action.get("status", "UNKNOWN")
    summary = action.get("summary", "")
    ts = action.get("updated_utc", "")

    content = f"[ACTION] {status}: {summary}"
    sender = "system"
    created_at = ts or "1970-01-01T00:00:00Z"

    content_hash = _compute_content_hash(sender, content, created_at)
    if content_hash in existing_hashes:
        return

    _insert_migrated_message(
        store,
        channel_id="system",
        sender=sender,
        content=content,
        content_hash=content_hash,
        created_at=created_at,
    )
    existing_hashes.add(content_hash)
