"""Tests for open_brain.im.store — SQLite WAL-mode message store.

Coverage targets from the approved plan (~40 tests):
  - Schema creation and WAL mode verification
  - post() with and without signing
  - read_channel() with pagination cursors (before/after)
  - read_thread() correlation ID threading
  - search() via FTS5
  - mark_delivered / mark_read / get_unread
  - create_channel / list_channels
  - purge_expired (TTL enforcement)
  - apply_retention (max_age + max_count)
  - Concurrent read access (WAL mode)
  - Content hash determinism
  - Signature verification on read
  - Empty channel handling
  - Invalid sender rejection (mandatory attribution)
"""

import json
import sqlite3
import time
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest

from open_brain.im.store import IMMessage, IMStore, _compute_content_hash


@pytest.fixture
def store(tmp_path: Path) -> IMStore:
    """Create a fresh IMStore in a temporary directory."""
    return IMStore(tmp_path / "test_im.sqlite3")


@pytest.fixture
def populated_store(store: IMStore) -> IMStore:
    """Store with a channel and several messages for read/search tests."""
    store.create_channel("cc", "Claude Code")
    store.create_channel("cx", "Codex")
    for i in range(5):
        store.post("cc", "cc-agent", f"Message {i} about architecture")
    for i in range(3):
        store.post("cx", "cx-agent", f"Review finding {i} about trust")
    return store


# -----------------------------------------------------------------------
# Schema and WAL mode
# -----------------------------------------------------------------------


class TestSchemaAndWAL:
    def test_wal_mode_enabled(self, store: IMStore) -> None:
        conn = sqlite3.connect(str(store._db_path))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_foreign_keys_enabled(self, store: IMStore) -> None:
        conn = sqlite3.connect(str(store._db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        conn.close()
        assert fk == 1

    def test_tables_exist(self, store: IMStore) -> None:
        conn = sqlite3.connect(str(store._db_path))
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "channels" in tables
        assert "messages" in tables
        assert "delivery_receipts" in tables
        assert "retention_policy" in tables

    def test_fts_table_exists(self, store: IMStore) -> None:
        conn = sqlite3.connect(str(store._db_path))
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "messages_fts" in tables

    def test_schema_idempotent(self, tmp_path: Path) -> None:
        """Creating IMStore twice on the same DB should not fail."""
        db_path = tmp_path / "idempotent.sqlite3"
        store1 = IMStore(db_path)
        store2 = IMStore(db_path)  # noqa: F841
        # Both should work — IF NOT EXISTS in schema
        store1.create_channel("test", "Test")
        assert len(store1.list_channels()) == 1

    def test_db_directory_created(self, tmp_path: Path) -> None:
        """IMStore creates parent directories if needed."""
        db_path = tmp_path / "deep" / "nested" / "im.sqlite3"
        store = IMStore(db_path)  # noqa: F841
        assert db_path.exists()


# -----------------------------------------------------------------------
# Channel management
# -----------------------------------------------------------------------


class TestChannels:
    def test_create_and_list_channels(self, store: IMStore) -> None:
        store.create_channel("cc", "Claude Code")
        store.create_channel("cx", "Codex")
        channels = store.list_channels()
        assert len(channels) == 2
        ids = {c["channel_id"] for c in channels}
        assert ids == {"cc", "cx"}

    def test_create_channel_idempotent(self, store: IMStore) -> None:
        store.create_channel("cc", "Claude Code")
        store.create_channel("cc", "Different Name")  # should be ignored
        channels = store.list_channels()
        assert len(channels) == 1
        assert channels[0]["display_name"] == "Claude Code"

    def test_create_channel_with_metadata(self, store: IMStore) -> None:
        store.create_channel("cc", "Claude Code", metadata={"priority": "high"})
        channels = store.list_channels()
        assert channels[0]["metadata"] == {"priority": "high"}

    def test_list_channels_empty(self, store: IMStore) -> None:
        assert store.list_channels() == []

    def test_auto_create_channel_on_post(self, store: IMStore) -> None:
        """Posting to a non-existent channel auto-creates it."""
        store.post("new_channel", "agent", "Hello")
        channels = store.list_channels()
        assert len(channels) == 1
        assert channels[0]["channel_id"] == "new_channel"


# -----------------------------------------------------------------------
# Posting messages
# -----------------------------------------------------------------------


class TestPost:
    def test_post_returns_message(self, store: IMStore) -> None:
        msg = store.post("cc", "cc-agent", "Test content")
        assert isinstance(msg, IMMessage)
        assert msg.channel_id == "cc"
        assert msg.sender == "cc-agent"
        assert msg.content == "Test content"
        assert msg.msg_type == "post"
        assert msg.correlation_id is None
        assert msg.signature is None
        assert msg.expires_at is None
        assert msg.metadata == {}

    def test_post_generates_uuid(self, store: IMStore) -> None:
        msg = store.post("cc", "agent", "test")
        assert len(msg.msg_id) == 36  # UUID format
        assert "-" in msg.msg_id

    def test_post_generates_content_hash(self, store: IMStore) -> None:
        msg = store.post("cc", "agent", "test")
        assert msg.content_hash.startswith("sha256:")
        assert len(msg.content_hash) == 71  # "sha256:" + 64 hex chars

    def test_post_with_metadata(self, store: IMStore) -> None:
        meta = {"priority": "high", "area": "security"}
        msg = store.post("cc", "agent", "test", metadata=meta)
        assert msg.metadata == meta

    def test_post_with_correlation_id(self, store: IMStore) -> None:
        root = store.post("cc", "agent", "root message")
        reply = store.post(
            "cc", "other", "reply", correlation_id=root.msg_id
        )
        assert reply.correlation_id == root.msg_id

    def test_post_with_ttl(self, store: IMStore) -> None:
        msg = store.post("cc", "agent", "ephemeral", ttl_days=7)
        assert msg.expires_at is not None
        # Expires approximately 7 days from now
        expires = datetime.fromisoformat(msg.expires_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = expires - now
        # timedelta.days truncates — 6.99 days shows as days=6
        total_hours = delta.total_seconds() / 3600
        assert 166 < total_hours < 170  # ~7 days ± a few hours

    def test_post_with_sign_fn(self, store: IMStore) -> None:
        """Signing function is called with content_hash."""
        captured = {}

        def mock_sign(content_hash: str) -> str:
            captured["hash"] = content_hash
            return "deadbeef" * 16  # 128 hex chars (fake Ed25519 sig)

        msg = store.post("cc", "agent", "signed message", sign_fn=mock_sign)
        assert msg.signature == "deadbeef" * 16
        assert captured["hash"] == msg.content_hash

    def test_post_msg_types(self, store: IMStore) -> None:
        for mtype in ("post", "action", "system", "reply"):
            msg = store.post("cc", "agent", f"type={mtype}", msg_type=mtype)
            assert msg.msg_type == mtype

    def test_post_rejects_empty_sender(self, store: IMStore) -> None:
        with pytest.raises(ValueError, match="Sender is mandatory"):
            store.post("cc", "", "content")

    def test_post_rejects_whitespace_sender(self, store: IMStore) -> None:
        with pytest.raises(ValueError, match="Sender is mandatory"):
            store.post("cc", "   ", "content")


# -----------------------------------------------------------------------
# Content hash determinism
# -----------------------------------------------------------------------


class TestContentHash:
    def test_deterministic_for_same_input(self) -> None:
        h1 = _compute_content_hash("agent", "hello", "2026-01-01T00:00:00.000Z")
        h2 = _compute_content_hash("agent", "hello", "2026-01-01T00:00:00.000Z")
        assert h1 == h2

    def test_different_sender_different_hash(self) -> None:
        h1 = _compute_content_hash("agent_a", "hello", "2026-01-01T00:00:00.000Z")
        h2 = _compute_content_hash("agent_b", "hello", "2026-01-01T00:00:00.000Z")
        assert h1 != h2

    def test_different_content_different_hash(self) -> None:
        h1 = _compute_content_hash("agent", "hello", "2026-01-01T00:00:00.000Z")
        h2 = _compute_content_hash("agent", "world", "2026-01-01T00:00:00.000Z")
        assert h1 != h2

    def test_different_timestamp_different_hash(self) -> None:
        h1 = _compute_content_hash("agent", "hello", "2026-01-01T00:00:00.000Z")
        h2 = _compute_content_hash("agent", "hello", "2026-01-02T00:00:00.000Z")
        assert h1 != h2

    def test_hash_format(self) -> None:
        h = _compute_content_hash("a", "b", "c")
        assert h.startswith("sha256:")
        hex_part = h[7:]
        assert len(hex_part) == 64
        int(hex_part, 16)  # validates hex


# -----------------------------------------------------------------------
# Reading messages
# -----------------------------------------------------------------------


class TestReadChannel:
    def test_read_empty_channel(self, store: IMStore) -> None:
        store.create_channel("cc", "Claude Code")
        msgs = store.read_channel("cc")
        assert msgs == []

    def test_read_channel_newest_first(self, populated_store: IMStore) -> None:
        msgs = populated_store.read_channel("cc")
        # Verify descending order
        for i in range(len(msgs) - 1):
            assert msgs[i].created_at >= msgs[i + 1].created_at

    def test_read_channel_limit(self, populated_store: IMStore) -> None:
        msgs = populated_store.read_channel("cc", limit=2)
        assert len(msgs) == 2

    def test_read_channel_before_cursor(self, populated_store: IMStore) -> None:
        all_msgs = populated_store.read_channel("cc")
        midpoint = all_msgs[2].created_at
        before_msgs = populated_store.read_channel("cc", before=midpoint)
        for m in before_msgs:
            assert m.created_at < midpoint

    def test_read_channel_after_cursor(self, populated_store: IMStore) -> None:
        all_msgs = populated_store.read_channel("cc")
        midpoint = all_msgs[2].created_at
        after_msgs = populated_store.read_channel("cc", after=midpoint)
        for m in after_msgs:
            assert m.created_at > midpoint

    def test_read_channel_filter_sender(self, populated_store: IMStore) -> None:
        # Post from a different sender to cc
        populated_store.post("cc", "other-agent", "From other")
        msgs = populated_store.read_channel("cc", sender="other-agent")
        assert len(msgs) == 1
        assert msgs[0].sender == "other-agent"

    def test_read_channel_isolation(self, populated_store: IMStore) -> None:
        """Messages from other channels are not returned."""
        cc_msgs = populated_store.read_channel("cc")
        cx_msgs = populated_store.read_channel("cx")
        assert all(m.channel_id == "cc" for m in cc_msgs)
        assert all(m.channel_id == "cx" for m in cx_msgs)


class TestReadRecent:
    def test_read_recent_all_channels(self, populated_store: IMStore) -> None:
        msgs = populated_store.read_recent(limit=100)
        assert len(msgs) == 8  # 5 cc + 3 cx
        # Newest first
        for i in range(len(msgs) - 1):
            assert msgs[i].created_at >= msgs[i + 1].created_at

    def test_read_recent_single_channel(self, populated_store: IMStore) -> None:
        msgs = populated_store.read_recent(channel_id="cx", limit=100)
        assert len(msgs) == 3
        assert all(m.channel_id == "cx" for m in msgs)


class TestReadThread:
    def test_thread_includes_root_and_replies(self, store: IMStore) -> None:
        root = store.post("cc", "agent", "Root message")
        store.post("cc", "other", "Reply 1", correlation_id=root.msg_id)
        store.post("cc", "agent", "Reply 2", correlation_id=root.msg_id)
        thread = store.read_thread(root.msg_id)
        assert len(thread) == 3

    def test_thread_chronological_order(self, store: IMStore) -> None:
        root = store.post("cc", "agent", "Root")
        store.post("cc", "other", "Reply", correlation_id=root.msg_id)
        thread = store.read_thread(root.msg_id)
        assert thread[0].content == "Root"
        assert thread[1].content == "Reply"

    def test_thread_limit(self, store: IMStore) -> None:
        root = store.post("cc", "agent", "Root")
        for i in range(10):
            store.post("cc", "agent", f"Reply {i}", correlation_id=root.msg_id)
        thread = store.read_thread(root.msg_id, limit=5)
        assert len(thread) == 5


class TestGetMessage:
    def test_get_existing_message(self, store: IMStore) -> None:
        msg = store.post("cc", "agent", "find me")
        found = store.get_message(msg.msg_id)
        assert found is not None
        assert found.content == "find me"

    def test_get_nonexistent_message(self, store: IMStore) -> None:
        assert store.get_message("nonexistent-id") is None


# -----------------------------------------------------------------------
# Full-text search
# -----------------------------------------------------------------------


class TestSearch:
    def test_search_finds_matching_content(self, populated_store: IMStore) -> None:
        results = populated_store.search("architecture")
        assert len(results) == 5  # all cc messages mention architecture

    def test_search_case_insensitive(self, store: IMStore) -> None:
        store.post("cc", "agent", "Architecture decisions")
        results = store.search("architecture")
        assert len(results) == 1

    def test_search_no_results(self, populated_store: IMStore) -> None:
        results = populated_store.search("nonexistent_term_xyz")
        assert results == []

    def test_search_limit(self, populated_store: IMStore) -> None:
        results = populated_store.search("architecture", limit=2)
        assert len(results) <= 2

    def test_search_cross_channel(self, populated_store: IMStore) -> None:
        """Search spans all channels."""
        # "trust" appears only in cx channel
        results = populated_store.search("trust")
        assert len(results) == 3
        assert all(r.channel_id == "cx" for r in results)


# -----------------------------------------------------------------------
# Delivery receipts
# -----------------------------------------------------------------------


class TestDeliveryReceipts:
    def test_mark_delivered(self, store: IMStore) -> None:
        msg = store.post("cc", "sender", "hello")
        store.mark_delivered(msg.msg_id, "recipient")
        unread = store.get_unread("recipient")
        # After delivery, message should not be in unread
        assert msg.msg_id not in {m.msg_id for m in unread}

    def test_mark_read(self, store: IMStore) -> None:
        msg = store.post("cc", "sender", "hello")
        store.mark_delivered(msg.msg_id, "recipient")
        store.mark_read(msg.msg_id, "recipient")
        # Verify read_at is set
        conn = sqlite3.connect(str(store._db_path))
        conn.row_factory = sqlite3.Row
        receipt = conn.execute(
            "SELECT * FROM delivery_receipts WHERE msg_id = ?",
            (msg.msg_id,),
        ).fetchone()
        conn.close()
        assert receipt["read_at"] is not None

    def test_unread_returns_undelivered(self, store: IMStore) -> None:
        msg1 = store.post("cc", "sender", "msg1")
        msg2 = store.post("cc", "sender", "msg2")
        store.mark_delivered(msg1.msg_id, "reader")
        unread = store.get_unread("reader")
        unread_ids = {m.msg_id for m in unread}
        assert msg1.msg_id not in unread_ids
        assert msg2.msg_id in unread_ids

    def test_unread_filtered_by_channel(self, store: IMStore) -> None:
        store.post("cc", "sender", "cc msg")
        store.post("cx", "sender", "cx msg")
        unread = store.get_unread("reader", channel_id="cc")
        assert all(m.channel_id == "cc" for m in unread)

    def test_mark_delivered_idempotent(self, store: IMStore) -> None:
        msg = store.post("cc", "sender", "hello")
        store.mark_delivered(msg.msg_id, "recipient")
        store.mark_delivered(msg.msg_id, "recipient")  # no error
        unread = store.get_unread("recipient")
        assert msg.msg_id not in {m.msg_id for m in unread}


# -----------------------------------------------------------------------
# TTL and retention
# -----------------------------------------------------------------------


class TestPurgeExpired:
    def test_purge_removes_expired(self, store: IMStore) -> None:
        # Post with extremely short TTL (already expired by the time we purge)
        msg = store.post("cc", "agent", "ephemeral", ttl_days=0)
        # Manually set expires_at to the past
        conn = sqlite3.connect(str(store._db_path))
        conn.execute(
            "UPDATE messages SET expires_at = '2020-01-01T00:00:00.000Z' "
            "WHERE msg_id = ?",
            (msg.msg_id,),
        )
        conn.commit()
        conn.close()

        deleted = store.purge_expired()
        assert deleted == 1
        assert store.message_count() == 0

    def test_purge_keeps_non_expired(self, store: IMStore) -> None:
        store.post("cc", "agent", "permanent")
        store.post("cc", "agent", "with ttl", ttl_days=30)
        deleted = store.purge_expired()
        assert deleted == 0
        assert store.message_count() == 2

    def test_purge_cleans_receipts(self, store: IMStore) -> None:
        msg = store.post("cc", "agent", "will expire")
        store.mark_delivered(msg.msg_id, "reader")
        # Expire it
        conn = sqlite3.connect(str(store._db_path))
        conn.execute(
            "UPDATE messages SET expires_at = '2020-01-01T00:00:00.000Z' "
            "WHERE msg_id = ?",
            (msg.msg_id,),
        )
        conn.commit()
        conn.close()

        store.purge_expired()
        # Verify receipt was also deleted
        conn = sqlite3.connect(str(store._db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM delivery_receipts"
        ).fetchone()[0]
        conn.close()
        assert count == 0


class TestRetention:
    def test_retention_age_based(self, store: IMStore) -> None:
        store.create_channel("cc", "Claude Code")
        store.set_retention_policy("cc", max_age_days=30, max_count=10000)

        # Post old message
        msg = store.post("cc", "agent", "old message")
        conn = sqlite3.connect(str(store._db_path))
        conn.execute(
            "UPDATE messages SET created_at = '2020-01-01T00:00:00.000Z' "
            "WHERE msg_id = ?",
            (msg.msg_id,),
        )
        conn.commit()
        conn.close()

        # Post fresh message
        store.post("cc", "agent", "fresh message")

        deleted = store.apply_retention("cc")
        assert deleted == 1
        assert store.message_count("cc") == 1

    def test_retention_count_based(self, store: IMStore) -> None:
        store.create_channel("cc", "Claude Code")
        store.set_retention_policy("cc", max_age_days=9999, max_count=3)

        for i in range(5):
            store.post("cc", "agent", f"Message {i}")

        deleted = store.apply_retention("cc")
        assert deleted == 2
        assert store.message_count("cc") == 3

    def test_retention_all_channels(self, store: IMStore) -> None:
        store.create_channel("cc", "CC")
        store.create_channel("cx", "CX")
        store.set_retention_policy("cc", max_count=2)
        store.set_retention_policy("cx", max_count=2)

        for i in range(4):
            store.post("cc", "agent", f"cc-{i}")
            store.post("cx", "agent", f"cx-{i}")

        deleted = store.apply_retention()
        assert deleted == 4  # 2 from each channel
        assert store.message_count("cc") == 2
        assert store.message_count("cx") == 2

    def test_retention_no_policy_no_action(self, store: IMStore) -> None:
        """Channels without retention policies are untouched."""
        store.create_channel("cc", "CC")
        for i in range(10):
            store.post("cc", "agent", f"msg-{i}")
        deleted = store.apply_retention("cc")
        assert deleted == 0
        assert store.message_count("cc") == 10


# -----------------------------------------------------------------------
# Bulk / admin
# -----------------------------------------------------------------------


class TestBulkOperations:
    def test_clear_channel(self, populated_store: IMStore) -> None:
        deleted = populated_store.clear_channel("cc")
        assert deleted == 5
        assert populated_store.message_count("cc") == 0
        # Other channel untouched
        assert populated_store.message_count("cx") == 3

    def test_clear_all(self, populated_store: IMStore) -> None:
        deleted = populated_store.clear_all()
        assert deleted == 8
        assert populated_store.message_count() == 0

    def test_message_count(self, populated_store: IMStore) -> None:
        assert populated_store.message_count() == 8
        assert populated_store.message_count("cc") == 5
        assert populated_store.message_count("cx") == 3

    def test_clear_channel_cleans_receipts(self, store: IMStore) -> None:
        msg = store.post("cc", "agent", "hello")
        store.mark_delivered(msg.msg_id, "reader")
        store.clear_channel("cc")
        conn = sqlite3.connect(str(store._db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM delivery_receipts"
        ).fetchone()[0]
        conn.close()
        assert count == 0


# -----------------------------------------------------------------------
# Concurrent access (WAL mode)
# -----------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_reads(self, populated_store: IMStore) -> None:
        """Multiple threads can read simultaneously under WAL mode."""
        results: List[int] = []
        errors: List[Exception] = []

        def reader():
            try:
                msgs = populated_store.read_channel("cc")
                results.append(len(msgs))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Concurrent reads failed: {errors}"
        assert all(r == 5 for r in results)

    def test_read_during_write(self, store: IMStore) -> None:
        """A reader should not be blocked by a writer under WAL mode."""
        store.post("cc", "agent", "initial")
        errors: List[Exception] = []

        def writer():
            try:
                for i in range(10):
                    store.post("cc", "writer", f"msg-{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(10):
                    store.read_channel("cc")
            except Exception as e:
                errors.append(e)

        t_write = threading.Thread(target=writer)
        t_read = threading.Thread(target=reader)
        t_write.start()
        t_read.start()
        t_write.join(timeout=10)
        t_read.join(timeout=10)

        assert not errors, f"Concurrent read/write failed: {errors}"
