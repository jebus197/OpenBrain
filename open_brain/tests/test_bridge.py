"""Tests for IM bridge dual-write."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

from open_brain import db
from open_brain.im_bridge import _db_capture_post, _db_capture_action


def test_db_capture_post():
    """Verify dual-write stores in database."""
    _db_capture_post("cc", "Bridge test message")

    results = db.list_recent(limit=1)
    assert len(results) == 1
    assert "Bridge test message" in results[0]["raw_text"]
    assert results[0]["metadata"]["memory_type"] == "handoff"
    assert results[0]["metadata"]["source_agent"] == "cc"


def test_db_capture_action():
    """Verify action dual-write stores as task."""
    _db_capture_action("IN_PROGRESS", "Building Open Brain")

    results = db.list_recent(limit=1, memory_type="task")
    assert len(results) == 1
    assert "Building Open Brain" in results[0]["raw_text"]


def test_db_failure_non_fatal(capsys):
    """DB failure should print to stderr but not raise."""
    with patch("open_brain.capture.capture_memory", side_effect=Exception("DB down")):
        # Should not raise
        _db_capture_post("cc", "test")

    captured = capsys.readouterr()
    assert "DB write failed" in captured.err


def test_action_idle_completed():
    """IDLE/DONE actions should be stored with completed status."""
    _db_capture_action("IDLE", "No pending action")

    results = db.list_recent(limit=1, memory_type="task")
    assert len(results) == 1
    assert results[0]["metadata"]["action_status"] == "completed"


def test_action_active_pending():
    """Active actions should be stored with pending status."""
    _db_capture_action("IN_PROGRESS", "Working on feature")

    results = db.list_recent(limit=1, memory_type="task")
    assert len(results) == 1
    assert results[0]["metadata"]["action_status"] == "pending"
