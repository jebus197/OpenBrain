"""Tests for open_brain.im.service — CLI entry point."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest import mock

import pytest

from open_brain.im.service import main
from open_brain.im.store import IMStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_cli.sqlite3"


@pytest.fixture
def store(db_path: Path) -> IMStore:
    """Pre-initialised store with default channels."""
    s = IMStore(db_path)
    s.create_channel("cc", "CC")
    s.create_channel("cx", "CX")
    s.create_channel("system", "System")
    return s


def _run(db_path: Path, *args: str) -> tuple[str, str, int]:
    """Run the CLI with given args, capturing stdout/stderr.

    Returns (stdout, stderr, exit_code).
    """
    argv = ["--db-path", str(db_path)] + list(args)
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    code = 0

    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout = out_buf
        sys.stderr = err_buf
        main(argv)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    finally:
        sys.stdout = old_out
        sys.stderr = old_err

    return out_buf.getvalue(), err_buf.getvalue(), code


# ---------------------------------------------------------------------------
# Tests: init
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_creates_channels(self, db_path: Path):
        out, _, code = _run(db_path, "init")
        assert code == 0
        assert "IM initialised" in out
        assert "#cc" in out
        assert "#cx" in out
        assert "#system" in out

    def test_init_with_project_flag(self, tmp_path: Path):
        out, _, code = _run(
            tmp_path / "proj.sqlite3", "init"
        )
        assert code == 0
        assert "IM initialised" in out


# ---------------------------------------------------------------------------
# Tests: post + read
# ---------------------------------------------------------------------------


class TestPostAndRead:
    def test_post_message(self, db_path: Path, store: IMStore):
        out, _, code = _run(db_path, "post", "cc", "Hello from CLI")
        assert code == 0
        assert "Posted to #cc" in out

    def test_post_and_read_round_trip(self, db_path: Path, store: IMStore):
        _run(db_path, "post", "cc", "Test message one", "--sender", "cx")
        out, _, code = _run(db_path, "read", "--channel", "cc")
        assert code == 0
        assert "Test message one" in out
        assert "cx" in out

    def test_read_all_channels(self, db_path: Path, store: IMStore):
        _run(db_path, "post", "cc", "msg-cc")
        _run(db_path, "post", "cx", "msg-cx")
        out, _, code = _run(db_path, "read")
        assert code == 0
        assert "msg-cc" in out
        assert "msg-cx" in out

    def test_read_with_limit(self, db_path: Path, store: IMStore):
        for i in range(5):
            _run(db_path, "post", "cc", f"msg-{i}")
        out, _, _ = _run(db_path, "read", "--channel", "cc", "--limit", "2")
        # Should only have 2 messages in output
        assert out.count("msg-") == 2

    def test_read_empty_channel(self, db_path: Path, store: IMStore):
        out, _, code = _run(db_path, "read", "--channel", "cc")
        assert code == 0
        assert "no messages" in out


# ---------------------------------------------------------------------------
# Tests: recent
# ---------------------------------------------------------------------------


class TestRecent:
    def test_recent_compact_output(self, db_path: Path, store: IMStore):
        _run(db_path, "post", "cc", "Recent test msg")
        out, _, code = _run(db_path, "recent", "--limit", "1")
        assert code == 0
        assert "Recent test msg" in out

    def test_recent_empty(self, db_path: Path, store: IMStore):
        out, _, code = _run(db_path, "recent")
        assert code == 0
        assert "no messages" in out


# ---------------------------------------------------------------------------
# Tests: action
# ---------------------------------------------------------------------------


class TestAction:
    def test_action_posts_to_system(self, db_path: Path, store: IMStore):
        out, _, code = _run(db_path, "action", "IN_PROGRESS", "Building IM")
        assert code == 0
        assert "Active action set: IN_PROGRESS" in out

        # Verify via store
        msgs = store.read_channel("system", limit=1)
        assert len(msgs) == 1
        assert "[ACTION] IN_PROGRESS: Building IM" in msgs[0].content


# ---------------------------------------------------------------------------
# Tests: search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_finds_message(self, db_path: Path, store: IMStore):
        _run(db_path, "post", "cc", "The quick brown fox jumps")
        _run(db_path, "post", "cc", "A slow red dog sleeps")
        out, _, code = _run(db_path, "search", "quick brown")
        assert code == 0
        assert "quick brown fox" in out

    def test_search_no_results(self, db_path: Path, store: IMStore):
        out, _, code = _run(db_path, "search", "nonexistent_term_xyz")
        assert code == 0
        assert "no messages" in out


# ---------------------------------------------------------------------------
# Tests: thread
# ---------------------------------------------------------------------------


class TestThread:
    def test_thread_reads_correlated_messages(self, db_path: Path, store: IMStore):
        # Post a root message and a reply via the store directly
        root = store.post(channel_id="cc", sender="cx", content="Root message")
        store.post(
            channel_id="cc",
            sender="cc",
            content="Reply to root",
            correlation_id=root.msg_id,
        )

        out, _, code = _run(db_path, "thread", root.msg_id)
        assert code == 0
        assert "Reply to root" in out


# ---------------------------------------------------------------------------
# Tests: clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_channel(self, db_path: Path, store: IMStore):
        _run(db_path, "post", "cc", "to be cleared")
        out, _, code = _run(db_path, "clear", "cc")
        assert code == 0
        assert "Cleared #cc" in out

        msgs = store.read_channel("cc", limit=10)
        assert len(msgs) == 0

    def test_clear_all(self, db_path: Path, store: IMStore):
        _run(db_path, "post", "cc", "msg1")
        _run(db_path, "post", "cx", "msg2")
        out, _, code = _run(db_path, "clear", "all")
        assert code == 0
        assert "Cleared all channels" in out


# ---------------------------------------------------------------------------
# Tests: unread
# ---------------------------------------------------------------------------


class TestUnread:
    def test_unread_shows_undelivered(self, db_path: Path, store: IMStore):
        store.post(channel_id="cc", sender="cx", content="Unread msg")
        out, _, code = _run(db_path, "unread", "cc_agent")
        assert code == 0
        assert "Unread msg" in out

    def test_unread_empty(self, db_path: Path, store: IMStore):
        # Mark all as delivered so nothing is unread
        out, _, code = _run(db_path, "unread", "nobody")
        assert code == 0


# ---------------------------------------------------------------------------
# Tests: channels
# ---------------------------------------------------------------------------


class TestChannels:
    def test_channels_lists_all(self, db_path: Path, store: IMStore):
        out, _, code = _run(db_path, "channels")
        assert code == 0
        assert "#cc" in out
        assert "#cx" in out
        assert "#system" in out

    def test_channels_empty_db(self, tmp_path: Path):
        out, _, code = _run(tmp_path / "empty.sqlite3", "channels")
        assert code == 0
        assert "No channels" in out


# ---------------------------------------------------------------------------
# Tests: purge
# ---------------------------------------------------------------------------


class TestPurge:
    def test_purge_nothing_to_purge(self, db_path: Path, store: IMStore):
        out, _, code = _run(db_path, "purge")
        assert code == 0
        assert "Nothing to purge" in out

    def test_purge_with_retention(self, db_path: Path, store: IMStore):
        # Insert an old message directly so retention can catch it.
        import uuid
        import json as _json

        from open_brain.im.store import _compute_content_hash

        old_ts = "2020-01-01T00:00:00.000Z"
        content = "ancient message"
        sender = "system"
        ch = _compute_content_hash(sender, content, old_ts)
        msg_id = str(uuid.uuid4())

        with store._conn() as conn:
            store._ensure_channel(conn, "cc")
            conn.execute(
                "INSERT INTO messages "
                "(msg_id, channel_id, sender, content, msg_type, "
                " correlation_id, content_hash, signature, created_at, "
                " expires_at, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (msg_id, "cc", sender, content, "post",
                 None, ch, None, old_ts, None, "{}"),
            )

        out, _, code = _run(db_path, "purge", "--channel", "cc", "--older-than", "1")
        assert code == 0
        assert "Retention applied" in out


# ---------------------------------------------------------------------------
# Tests: migrate-json
# ---------------------------------------------------------------------------


class TestMigrateJson:
    def test_migrate_json_basic(self, tmp_path: Path):
        import json

        state = {
            "version": "1.0",
            "protocol": {"agents": {"cc": "cc"}, "max_entries": 20},
            "active_action": {"status": "IDLE", "summary": "", "updated_utc": None},
            "cc": [
                {"ts": "2026-03-10T10:00:00Z", "msg": "cx: Hello from JSON"},
            ],
        }
        json_path = tmp_path / "im_state.json"
        json_path.write_text(json.dumps(state))

        db_path = tmp_path / "migrated.sqlite3"
        out, _, code = _run(db_path, "migrate-json", str(json_path))
        assert code == 0
        assert "Migration complete" in out
        assert "Messages migrated: 1" in out


# ---------------------------------------------------------------------------
# Tests: resync (r / rt)
# ---------------------------------------------------------------------------


class TestResync:
    def test_resync_r(self, db_path: Path, store: IMStore):
        _run(db_path, "post", "cc", "resync test msg")
        out, _, code = _run(db_path, "r")
        assert code == 0
        assert "Resync start" in out
        assert "IM recent" in out

    def test_resync_rt_includes_continue(self, db_path: Path, store: IMStore):
        out, _, code = _run(db_path, "rt")
        assert code == 0
        assert "Resync complete. Continue." in out


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------


class TestErrors:
    def test_no_command_shows_help(self, db_path: Path):
        out, _, code = _run(db_path)
        assert code == 0  # help exits 0

    def test_unknown_command(self, db_path: Path):
        _, err, code = _run(db_path, "nonexistent")
        assert code != 0


# ---------------------------------------------------------------------------
# Tests: signing integration
# ---------------------------------------------------------------------------


class TestSigning:
    def test_post_without_keypair_succeeds(self, db_path: Path, store: IMStore):
        """Post should work even when no keypair exists (unsigned)."""
        out, _, code = _run(db_path, "post", "cc", "Unsigned message")
        assert code == 0
        assert "Posted to #cc" in out

    def test_post_with_mock_signing(self, db_path: Path, store: IMStore):
        """Verify signing path is invoked when keypair exists."""
        with mock.patch(
            "open_brain.im.service._load_sign_fn",
            return_value=lambda h: "deadbeef" * 8,
        ):
            out, _, code = _run(db_path, "post", "cc", "Signed message")
            assert code == 0

        msgs = store.read_channel("cc", limit=1)
        assert len(msgs) == 1
        assert msgs[0].signature == "deadbeef" * 8
