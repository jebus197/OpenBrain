"""Tests for CLI interface."""

import os
import subprocess
import sys
from pathlib import Path

PYTHON = sys.executable
CLI = [PYTHON, "-m", "open_brain.cli"]
# Repo root: two levels up from this test file
_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)


def _run(args, timeout=30):
    result = subprocess.run(
        CLI + args,
        capture_output=True, text=True, timeout=timeout,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "OPEN_BRAIN_DB_NAME": "open_brain_test",
        },
    )
    return result


def test_status():
    r = _run(["status"])
    assert r.returncode == 0
    assert "OK" in r.stdout


def test_capture_and_list_recent():
    r = _run(["capture", "CLI test memory", "--agent", "cc",
              "--type", "insight", "--area", "general"])
    assert r.returncode == 0
    assert "Stored:" in r.stdout

    r = _run(["list-recent", "--limit", "1"])
    assert r.returncode == 0
    assert "CLI test memory" in r.stdout


def test_capture_and_search():
    _run(["capture", "Semantic search test via CLI", "--agent", "cx",
          "--type", "decision", "--area", "frontend"])

    r = _run(["search", "semantic search test"])
    assert r.returncode == 0
    assert "Semantic search test" in r.stdout


def test_session_context():
    _run(["capture", "Context test", "--agent", "cc",
          "--type", "session_summary", "--area", "general"])

    r = _run(["session-context", "--agent", "cx"])
    assert r.returncode == 0
    assert "Session Context for CX" in r.stdout
    assert "Context test" in r.stdout  # Should appear in other agents' recent


def test_invalid_args():
    r = _run(["capture", "no agent"])
    assert r.returncode != 0


def test_pending_tasks_roundtrip():
    r = _run(["capture", "CLI task test", "--agent", "cc",
              "--type", "task", "--area", "infra",
              "--status", "pending", "--assigned-to", "cc"])
    assert r.returncode == 0
    mem_id = r.stdout.strip().split("Stored: ")[1]

    r = _run(["pending-tasks", "--agent", "cc"])
    assert r.returncode == 0
    assert "CLI task test" in r.stdout

    r = _run(["update-task", mem_id, "--status", "completed", "--agent", "cc"])
    assert r.returncode == 0

    r = _run(["pending-tasks", "--agent", "cc"])
    assert r.returncode == 0
    assert "No pending" in r.stdout
