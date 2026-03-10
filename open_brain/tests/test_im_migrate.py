"""Tests for open_brain.im.migrate — flat-file JSON to SQLite migration."""

import json
from pathlib import Path

import pytest

from open_brain.im.migrate import (
    _extract_sender,
    migrate_json_to_sqlite,
)
from open_brain.im.store import IMStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_json_state(
    agents: list[str],
    entries_per_agent: int = 3,
    *,
    active_action: dict | None = None,
) -> dict:
    """Build a synthetic flat-file JSON state."""
    state = {
        "version": "1.0",
        "protocol": {
            "agents": {a: a for a in agents},
            "max_entries": 20,
        },
        "active_action": active_action or {
            "status": "IDLE",
            "summary": "No pending action.",
            "updated_utc": None,
        },
    }
    for i, agent in enumerate(agents):
        entries = []
        for j in range(entries_per_agent):
            # Newest first (same as im_service.py insert order)
            idx = entries_per_agent - j - 1
            entries.append({
                "ts": f"2026-03-10T{10 + i:02d}:{idx:02d}:00Z",
                "msg": f"{agents[(i + 1) % len(agents)]}: Message {idx} to {agent}",
            })
        state[agent] = entries
    return state


@pytest.fixture
def json_state_path(tmp_path: Path) -> Path:
    """Write a standard 2-agent JSON state file and return its path."""
    state = _make_json_state(["cc", "cx"])
    path = tmp_path / "im_state.json"
    path.write_text(json.dumps(state, indent=2))
    return path


@pytest.fixture
def sqlite_path(tmp_path: Path) -> Path:
    return tmp_path / "test_migrate.sqlite3"


# ---------------------------------------------------------------------------
# Tests: _extract_sender
# ---------------------------------------------------------------------------


class TestExtractSender:
    """Tests for sender extraction from message content."""

    def test_known_agent_prefix(self):
        assert _extract_sender("cx: API refactor done", ["cc", "cx"]) == "cx"

    def test_known_agent_prefix_case_insensitive(self):
        assert _extract_sender("CC: session starting", ["cc", "cx"]) == "cc"

    def test_no_known_prefix_returns_system(self):
        assert _extract_sender("Just a regular message", ["cc", "cx"]) == "system"

    def test_empty_agents_returns_system(self):
        assert _extract_sender("cx: hello", []) == "system"

    def test_partial_match_not_extracted(self):
        # "ccc:" should not match "cc"
        assert _extract_sender("ccc: some msg", ["cc", "cx"]) == "system"


# ---------------------------------------------------------------------------
# Tests: migrate_json_to_sqlite
# ---------------------------------------------------------------------------


class TestMigrateBasic:
    """Basic migration scenarios."""

    def test_migrate_creates_channels(
        self, json_state_path: Path, sqlite_path: Path
    ):
        result = migrate_json_to_sqlite(json_state_path, sqlite_path)
        assert result["channels"] == 2

        store = IMStore(sqlite_path)
        channels = store.list_channels()
        channel_ids = {c["channel_id"] for c in channels}
        assert "cc" in channel_ids
        assert "cx" in channel_ids

    def test_migrate_imports_messages(
        self, json_state_path: Path, sqlite_path: Path
    ):
        result = migrate_json_to_sqlite(json_state_path, sqlite_path)
        assert result["migrated"] == 6  # 3 per agent × 2 agents

        store = IMStore(sqlite_path)
        assert store.message_count() == 6

    def test_migrate_preserves_timestamps(
        self, json_state_path: Path, sqlite_path: Path
    ):
        migrate_json_to_sqlite(json_state_path, sqlite_path)
        store = IMStore(sqlite_path)

        # CC stream messages should have timestamps from the fixture
        msgs = store.read_channel("cc", limit=10)
        timestamps = [m.created_at for m in msgs]
        # Verify they contain the expected hour (10 for cc, index 0)
        assert any("T10:" in ts for ts in timestamps)

    def test_migrate_preserves_content(
        self, json_state_path: Path, sqlite_path: Path
    ):
        migrate_json_to_sqlite(json_state_path, sqlite_path)
        store = IMStore(sqlite_path)

        msgs = store.read_channel("cc", limit=10)
        contents = [m.content for m in msgs]
        assert any("Message 0 to cc" in c for c in contents)

    def test_migrate_extracts_senders(
        self, json_state_path: Path, sqlite_path: Path
    ):
        migrate_json_to_sqlite(json_state_path, sqlite_path)
        store = IMStore(sqlite_path)

        # Messages in cc stream are from cx (format: "cx: Message N to cc")
        msgs = store.read_channel("cc", limit=10)
        senders = {m.sender for m in msgs}
        assert "cx" in senders

    def test_migrate_returns_zero_skipped_on_first_run(
        self, json_state_path: Path, sqlite_path: Path
    ):
        result = migrate_json_to_sqlite(json_state_path, sqlite_path)
        assert result["skipped"] == 0


class TestMigrateIdempotency:
    """Migration must be idempotent — safe to run multiple times."""

    def test_second_run_skips_all(
        self, json_state_path: Path, sqlite_path: Path
    ):
        r1 = migrate_json_to_sqlite(json_state_path, sqlite_path)
        r2 = migrate_json_to_sqlite(json_state_path, sqlite_path)

        assert r1["migrated"] == 6
        assert r2["migrated"] == 0
        assert r2["skipped"] == 6

        store = IMStore(sqlite_path)
        assert store.message_count() == 6  # No duplicates

    def test_third_run_still_idempotent(
        self, json_state_path: Path, sqlite_path: Path
    ):
        migrate_json_to_sqlite(json_state_path, sqlite_path)
        migrate_json_to_sqlite(json_state_path, sqlite_path)
        r3 = migrate_json_to_sqlite(json_state_path, sqlite_path)

        assert r3["migrated"] == 0
        assert r3["skipped"] == 6


class TestMigrateEdgeCases:
    """Edge cases and error handling."""

    def test_missing_file_raises(self, sqlite_path: Path):
        with pytest.raises(FileNotFoundError):
            migrate_json_to_sqlite(
                Path("/nonexistent/im_state.json"), sqlite_path
            )

    def test_empty_state_no_agents(self, tmp_path: Path, sqlite_path: Path):
        state = {
            "version": "1.0",
            "protocol": {"agents": {}, "max_entries": 20},
            "active_action": {"status": "IDLE", "summary": "", "updated_utc": None},
        }
        path = tmp_path / "empty.json"
        path.write_text(json.dumps(state))

        result = migrate_json_to_sqlite(path, sqlite_path)
        assert result["migrated"] == 0
        assert result["channels"] == 0

    def test_empty_stream(self, tmp_path: Path, sqlite_path: Path):
        state = _make_json_state(["cc"], entries_per_agent=0)
        path = tmp_path / "empty_stream.json"
        path.write_text(json.dumps(state))

        result = migrate_json_to_sqlite(path, sqlite_path)
        assert result["channels"] == 1
        assert result["migrated"] == 0

    def test_empty_message_skipped(self, tmp_path: Path, sqlite_path: Path):
        state = {
            "version": "1.0",
            "protocol": {"agents": {"cc": "cc"}, "max_entries": 20},
            "active_action": {"status": "IDLE", "summary": "", "updated_utc": None},
            "cc": [
                {"ts": "2026-03-10T10:00:00Z", "msg": ""},
                {"ts": "2026-03-10T10:01:00Z", "msg": "Real message"},
            ],
        }
        path = tmp_path / "with_empty.json"
        path.write_text(json.dumps(state))

        result = migrate_json_to_sqlite(path, sqlite_path)
        assert result["migrated"] == 1  # Empty message skipped

    def test_active_action_migrated(self, tmp_path: Path, sqlite_path: Path):
        state = _make_json_state(
            ["cc"],
            entries_per_agent=1,
            active_action={
                "status": "IN_PROGRESS",
                "summary": "Refactoring auth module",
                "updated_utc": "2026-03-10T12:00:00Z",
            },
        )
        path = tmp_path / "with_action.json"
        path.write_text(json.dumps(state))

        result = migrate_json_to_sqlite(path, sqlite_path)
        # 1 message + 1 action
        assert result["migrated"] == 2

        store = IMStore(sqlite_path)
        sys_msgs = store.read_channel("system", limit=10)
        assert len(sys_msgs) == 1
        assert "[ACTION] IN_PROGRESS" in sys_msgs[0].content

    def test_idle_action_not_migrated(
        self, json_state_path: Path, sqlite_path: Path
    ):
        result = migrate_json_to_sqlite(json_state_path, sqlite_path)
        store = IMStore(sqlite_path)

        # Should only have cc and cx channels, no system channel messages
        sys_msgs = store.read_channel("system", limit=10)
        assert len(sys_msgs) == 0

    def test_migrated_metadata_flag(
        self, json_state_path: Path, sqlite_path: Path
    ):
        migrate_json_to_sqlite(json_state_path, sqlite_path)
        store = IMStore(sqlite_path)

        msgs = store.read_channel("cc", limit=1)
        assert msgs[0].metadata.get("migrated") is True

    def test_project_name_in_channel_metadata(
        self, json_state_path: Path, sqlite_path: Path
    ):
        migrate_json_to_sqlite(
            json_state_path, sqlite_path, project_name="genesis"
        )
        store = IMStore(sqlite_path)
        channels = store.list_channels()

        for ch in channels:
            if ch["channel_id"] in ("cc", "cx"):
                assert ch["metadata"]["project"] == "genesis"
