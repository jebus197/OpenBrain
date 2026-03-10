"""SQLite WAL-mode message store for Open Brain IM.

Design principles:
  - One SQLite file per project: ~/.openbrain/im/{project}.sqlite3
  - WAL mode: one writer + unlimited concurrent readers
  - FTS5 full-text search on message content
  - Ed25519 signing: every message gets a content_hash, optionally signed
  - Mandatory attribution: every message MUST have a sender (no anonymous)
  - Content hash: sha256(canonical(sender + content + created_at))

The store is the persistence layer. Higher-level concerns (CLI, facades,
bus integration) live in service.py and the api/ package.
"""

import hashlib
import json
import logging
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IMMessage:
    """Immutable message record.

    Frozen for hashability and thread safety — same convention as
    coordination.protocol.Envelope.
    """

    msg_id: str
    channel_id: str
    sender: str
    content: str
    msg_type: str
    correlation_id: Optional[str]
    content_hash: str
    signature: Optional[str]
    created_at: str
    expires_at: Optional[str]
    metadata: Dict[str, Any]


def _compute_content_hash(sender: str, content: str, created_at: str) -> str:
    """Compute SHA-256 content hash for an IM message.

    Canonical form: JSON with sorted keys, compact separators, UTF-8.
    Format matches OB convention: "sha256:<hex>".

    Hashed fields: sender, content, created_at. This triple uniquely
    identifies a message — same content from the same sender at a
    different time produces a different hash.
    """
    canonical = json.dumps(
        {"content": content, "created_at": created_at, "sender": sender},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _now_utc() -> str:
    """ISO 8601 UTC timestamp with millisecond precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# FTS5 setup — kept separate from main schema because virtual tables
# have different IF NOT EXISTS semantics in some SQLite versions.
_FTS_SETUP = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
        VALUES('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
        VALUES('delete', old.rowid, old.content);
    INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
END;
"""


class IMStore:
    """SQLite-backed message store with WAL mode.

    Thread safety: each method opens its own connection (SQLite WAL
    allows concurrent readers with a single writer). For high-throughput
    scenarios, callers should use a connection pool — but at Scale 0-1
    (single process), per-call connections are sufficient and simpler.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _conn(self, *, readonly: bool = False):
        """Context manager for a SQLite connection.

        WAL mode + busy_timeout ensures readers never block writers
        and writers retry for up to 5 seconds before failing.
        """
        uri = f"file:{self._db_path}"
        if readonly:
            uri += "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        else:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            if not readonly:
                conn.commit()
        except Exception:
            if not readonly:
                conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        """Create tables, indexes, and FTS if they don't exist."""
        schema_path = Path(__file__).parent / "schema.sql"
        schema_sql = schema_path.read_text()
        with self._conn() as conn:
            conn.executescript(schema_sql)
            conn.executescript(_FTS_SETUP)

    # ------------------------------------------------------------------
    # Channel management
    # ------------------------------------------------------------------

    _CHANNEL_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

    def create_channel(
        self,
        channel_id: str,
        display_name: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create a channel. Idempotent — ignores if already exists.

        Raises:
            ValueError: If channel_id is empty or contains invalid characters.
                        Valid: alphanumeric, hyphens, underscores, max 64 chars.
        """
        if not self._CHANNEL_ID_RE.match(channel_id):
            raise ValueError(
                f"Invalid channel_id {channel_id!r} — must be 1-64 chars, "
                "alphanumeric, hyphens, or underscores only."
            )
        meta_json = json.dumps(metadata or {}, sort_keys=True)
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO channels (channel_id, display_name, metadata) "
                "VALUES (?, ?, ?)",
                (channel_id, display_name, meta_json),
            )

    def list_channels(self) -> List[Dict[str, Any]]:
        """Return all channels with metadata."""
        with self._conn(readonly=True) as conn:
            rows = conn.execute(
                "SELECT channel_id, display_name, created_at, metadata "
                "FROM channels ORDER BY channel_id"
            ).fetchall()
        return [
            {
                "channel_id": r["channel_id"],
                "display_name": r["display_name"],
                "created_at": r["created_at"],
                "metadata": json.loads(r["metadata"]),
            }
            for r in rows
        ]

    def _ensure_channel(self, conn: sqlite3.Connection, channel_id: str) -> None:
        """Auto-create channel if it doesn't exist (convenience for post())."""
        conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id, display_name) "
            "VALUES (?, ?)",
            (channel_id, channel_id),
        )

    # ------------------------------------------------------------------
    # Post messages
    # ------------------------------------------------------------------

    def post(
        self,
        channel_id: str,
        sender: str,
        content: str,
        *,
        msg_type: str = "post",
        correlation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        sign_fn: Optional[Callable[[str], str]] = None,
        ttl_days: Optional[int] = None,
    ) -> IMMessage:
        """Post a message to a channel.

        Args:
            channel_id: Target channel (auto-created if absent).
            sender: Mandatory. Rejected if empty.
            content: Message body.
            msg_type: post | action | system | reply.
            correlation_id: Parent msg_id for threading.
            metadata: Arbitrary JSON-serialisable dict.
            sign_fn: Callable(content_hash_hex) -> hex_signature.
                     If None and a keypair exists, signing is skipped.
            ttl_days: If set, message expires after this many days.

        Returns: The posted IMMessage (with all computed fields).

        Raises:
            ValueError: If sender is empty.
        """
        if not sender or not sender.strip():
            raise ValueError("Sender is mandatory — anonymous messages are rejected.")

        msg_id = str(uuid.uuid4())
        created_at = _now_utc()
        content_hash = _compute_content_hash(sender, content, created_at)

        signature = None
        if sign_fn is not None:
            # Sign the content_hash hex string — sign_fn receives a
            # "sha256:<hex>" string and returns a hex-encoded signature.
            # Matches the convention in service.py _load_sign_fn().
            try:
                signature = sign_fn(content_hash)
            except Exception:
                logger.warning("sign_fn failed — message will be unsigned")
                signature = None

        expires_at = None
        if ttl_days is not None and ttl_days > 0:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(days=ttl_days)
            ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        meta_json = json.dumps(metadata or {}, sort_keys=True)

        with self._conn() as conn:
            self._ensure_channel(conn, channel_id)
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
                    msg_type,
                    correlation_id,
                    content_hash,
                    signature,
                    created_at,
                    expires_at,
                    meta_json,
                ),
            )

        return IMMessage(
            msg_id=msg_id,
            channel_id=channel_id,
            sender=sender,
            content=content,
            msg_type=msg_type,
            correlation_id=correlation_id,
            content_hash=content_hash,
            signature=signature,
            created_at=created_at,
            expires_at=expires_at,
            metadata=metadata or {},
        )

    # ------------------------------------------------------------------
    # Read messages
    # ------------------------------------------------------------------

    def _row_to_message(self, row: sqlite3.Row) -> IMMessage:
        """Convert a sqlite3.Row to an IMMessage."""
        return IMMessage(
            msg_id=row["msg_id"],
            channel_id=row["channel_id"],
            sender=row["sender"],
            content=row["content"],
            msg_type=row["msg_type"],
            correlation_id=row["correlation_id"],
            content_hash=row["content_hash"],
            signature=row["signature"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            metadata=json.loads(row["metadata"]),
        )

    def read_channel(
        self,
        channel_id: str,
        *,
        limit: int = 50,
        before: Optional[str] = None,
        after: Optional[str] = None,
        sender: Optional[str] = None,
    ) -> List[IMMessage]:
        """Read messages from a channel with cursor-based pagination.

        Args:
            channel_id: Channel to read.
            limit: Max messages to return.
            before: Return messages before this ISO timestamp (exclusive).
            after: Return messages after this ISO timestamp (exclusive).
            sender: Filter by sender.

        Returns: Messages ordered by created_at DESC (newest first).
        """
        clauses = ["channel_id = ?"]
        params: list = [channel_id]

        if before:
            clauses.append("created_at < ?")
            params.append(before)
        if after:
            clauses.append("created_at > ?")
            params.append(after)
        if sender:
            clauses.append("sender = ?")
            params.append(sender)

        where = " AND ".join(clauses)
        params.append(limit)

        with self._conn(readonly=True) as conn:
            rows = conn.execute(
                f"SELECT * FROM messages WHERE {where} "
                "ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()

        return [self._row_to_message(r) for r in rows]

    def read_thread(
        self,
        correlation_id: str,
        *,
        limit: int = 100,
    ) -> List[IMMessage]:
        """Read a message thread (all messages sharing a correlation_id).

        Also includes the root message (where msg_id == correlation_id).
        Returns: Messages ordered by created_at ASC (chronological).
        """
        with self._conn(readonly=True) as conn:
            rows = conn.execute(
                "SELECT * FROM messages "
                "WHERE correlation_id = ? OR msg_id = ? "
                "ORDER BY created_at ASC LIMIT ?",
                (correlation_id, correlation_id, limit),
            ).fetchall()

        return [self._row_to_message(r) for r in rows]

    def read_recent(
        self,
        *,
        limit: int = 20,
        channel_id: Optional[str] = None,
    ) -> List[IMMessage]:
        """Read the most recent messages across all channels (or one).

        Returns: Messages ordered by created_at DESC (newest first).
        """
        if channel_id:
            return self.read_channel(channel_id, limit=limit)

        with self._conn(readonly=True) as conn:
            rows = conn.execute(
                "SELECT * FROM messages ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        return [self._row_to_message(r) for r in rows]

    def get_message(self, msg_id: str) -> Optional[IMMessage]:
        """Get a single message by ID."""
        with self._conn(readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM messages WHERE msg_id = ?", (msg_id,)
            ).fetchone()
        return self._row_to_message(row) if row else None

    # ------------------------------------------------------------------
    # Full-text search
    # ------------------------------------------------------------------

    def search(self, query: str, *, limit: int = 20) -> List[IMMessage]:
        """Search message content via FTS5.

        Args:
            query: FTS5 query string (supports AND, OR, NOT, phrases).
            limit: Max results.

        Returns: Messages ordered by relevance (rank).
                 Empty list if query is malformed (FTS5 parse error).
        """
        if not query or not query.strip():
            return []

        try:
            with self._conn(readonly=True) as conn:
                rows = conn.execute(
                    "SELECT m.* FROM messages m "
                    "JOIN messages_fts f ON m.rowid = f.rowid "
                    "WHERE messages_fts MATCH ? "
                    "ORDER BY f.rank LIMIT ?",
                    (query, limit),
                ).fetchall()
        except sqlite3.OperationalError:
            logger.warning("FTS5 query parse error for: %r", query)
            return []

        return [self._row_to_message(r) for r in rows]

    # ------------------------------------------------------------------
    # Delivery receipts
    # ------------------------------------------------------------------

    def mark_delivered(self, msg_id: str, recipient: str) -> None:
        """Record that a message was delivered to a recipient."""
        receipt_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO delivery_receipts "
                "(receipt_id, msg_id, recipient) VALUES (?, ?, ?)",
                (receipt_id, msg_id, recipient),
            )

    def mark_read(self, msg_id: str, recipient: str) -> None:
        """Record that a recipient has read a message."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE delivery_receipts SET read_at = ? "
                "WHERE msg_id = ? AND recipient = ?",
                (_now_utc(), msg_id, recipient),
            )

    def get_unread(
        self,
        recipient: str,
        *,
        channel_id: Optional[str] = None,
    ) -> List[IMMessage]:
        """Get messages not yet delivered to a recipient.

        Returns messages that have no delivery receipt for this recipient.
        Optionally filtered to a single channel.
        """
        clauses = []
        params: list = [recipient]

        if channel_id:
            clauses.append("AND m.channel_id = ?")
            params.append(channel_id)

        extra_where = " ".join(clauses)

        with self._conn(readonly=True) as conn:
            rows = conn.execute(
                f"SELECT m.* FROM messages m "
                f"WHERE m.msg_id NOT IN ("
                f"  SELECT dr.msg_id FROM delivery_receipts dr "
                f"  WHERE dr.recipient = ?"
                f") {extra_where} "
                f"ORDER BY m.created_at ASC",
                params,
            ).fetchall()

        return [self._row_to_message(r) for r in rows]

    # ------------------------------------------------------------------
    # Retention and TTL
    # ------------------------------------------------------------------

    def set_retention_policy(
        self,
        channel_id: str,
        *,
        max_age_days: int = 90,
        max_count: int = 10000,
    ) -> None:
        """Set or update retention policy for a channel."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO retention_policy (channel_id, max_age_days, max_count) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(channel_id) DO UPDATE SET "
                "max_age_days = excluded.max_age_days, "
                "max_count = excluded.max_count",
                (channel_id, max_age_days, max_count),
            )

    def purge_expired(self) -> int:
        """Delete messages past their expires_at timestamp.

        Returns: Count of deleted messages.
        """
        now = _now_utc()
        with self._conn() as conn:
            # Delete receipts for expired messages first (FK constraint)
            conn.execute(
                "DELETE FROM delivery_receipts WHERE msg_id IN ("
                "  SELECT msg_id FROM messages "
                "  WHERE expires_at IS NOT NULL AND expires_at < ?"
                ")",
                (now,),
            )
            cursor = conn.execute(
                "DELETE FROM messages "
                "WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
        return cursor.rowcount

    def apply_retention(self, channel_id: Optional[str] = None) -> int:
        """Apply retention policies (max_age + max_count).

        If channel_id is given, applies only to that channel.
        Otherwise, applies to all channels with retention policies.

        Returns: Total count of deleted messages.
        """
        total_deleted = 0
        with self._conn() as conn:
            if channel_id:
                policies = conn.execute(
                    "SELECT * FROM retention_policy WHERE channel_id = ?",
                    (channel_id,),
                ).fetchall()
            else:
                policies = conn.execute(
                    "SELECT * FROM retention_policy"
                ).fetchall()

            for policy in policies:
                ch_id = policy["channel_id"]
                max_age = policy["max_age_days"]
                max_count = policy["max_count"]

                # Age-based purge
                if max_age and max_age > 0:
                    cutoff = (
                        datetime.now(timezone.utc) - timedelta(days=max_age)
                    ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

                    conn.execute(
                        "DELETE FROM delivery_receipts WHERE msg_id IN ("
                        "  SELECT msg_id FROM messages "
                        "  WHERE channel_id = ? AND created_at < ?"
                        ")",
                        (ch_id, cutoff),
                    )
                    cursor = conn.execute(
                        "DELETE FROM messages "
                        "WHERE channel_id = ? AND created_at < ?",
                        (ch_id, cutoff),
                    )
                    total_deleted += cursor.rowcount

                # Count-based purge (keep newest max_count)
                if max_count and max_count > 0:
                    conn.execute(
                        "DELETE FROM delivery_receipts WHERE msg_id IN ("
                        "  SELECT msg_id FROM messages "
                        "  WHERE channel_id = ? AND msg_id NOT IN ("
                        "    SELECT msg_id FROM messages "
                        "    WHERE channel_id = ? "
                        "    ORDER BY created_at DESC LIMIT ?"
                        "  )"
                        ")",
                        (ch_id, ch_id, max_count),
                    )
                    cursor = conn.execute(
                        "DELETE FROM messages "
                        "WHERE channel_id = ? AND msg_id NOT IN ("
                        "  SELECT msg_id FROM messages "
                        "  WHERE channel_id = ? "
                        "  ORDER BY created_at DESC LIMIT ?"
                        ")",
                        (ch_id, ch_id, max_count),
                    )
                    total_deleted += cursor.rowcount

        return total_deleted

    # ------------------------------------------------------------------
    # Bulk / admin
    # ------------------------------------------------------------------

    def clear_channel(self, channel_id: str) -> int:
        """Delete all messages in a channel. Returns count deleted."""
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM delivery_receipts WHERE msg_id IN ("
                "  SELECT msg_id FROM messages WHERE channel_id = ?"
                ")",
                (channel_id,),
            )
            cursor = conn.execute(
                "DELETE FROM messages WHERE channel_id = ?",
                (channel_id,),
            )
        return cursor.rowcount

    def clear_all(self) -> int:
        """Delete all messages across all channels. Returns count deleted."""
        with self._conn() as conn:
            conn.execute("DELETE FROM delivery_receipts")
            cursor = conn.execute("DELETE FROM messages")
        return cursor.rowcount

    def message_count(self, channel_id: Optional[str] = None) -> int:
        """Count messages, optionally filtered by channel."""
        with self._conn(readonly=True) as conn:
            if channel_id:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM messages WHERE channel_id = ?",
                    (channel_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM messages"
                ).fetchone()
        return row["cnt"]
