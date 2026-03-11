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


# ---------------------------------------------------------------------------
# Reasoning CLI commands
# ---------------------------------------------------------------------------


def test_prove_returns_proof():
    """prove command outputs proof package for a stored memory."""
    r = _run(["capture", "CLI prove test", "--agent", "cc",
              "--type", "reasoning_checkpoint", "--area", "general"])
    assert r.returncode == 0
    mem_id = r.stdout.strip().split("Stored: ")[1]

    r = _run(["prove", mem_id])
    assert r.returncode == 0
    assert "Proof package" in r.stdout
    assert "Content hash: sha256:" in r.stdout


def test_prove_missing_memory():
    r = _run(["prove", "00000000-0000-0000-0000-000000000000"])
    assert r.returncode != 0
    assert "not found" in r.stderr.lower()


def test_reasoning_chain():
    _run(["capture", "CLI reasoning step 1", "--agent", "cc",
          "--type", "reasoning_checkpoint", "--area", "general"])
    _run(["capture", "CLI reasoning step 2", "--agent", "cc",
          "--type", "reasoning_checkpoint", "--area", "general"])

    r = _run(["reasoning", "cc"])
    assert r.returncode == 0
    assert "Reasoning chain" in r.stdout
    assert "checkpoints" in r.stdout


def test_reasoning_empty_agent():
    r = _run(["reasoning", "nonexistent_agent_xyz"])
    assert r.returncode == 0
    assert "No reasoning checkpoints" in r.stdout


def test_verify_reasoning():
    _run(["capture", "CLI verify step", "--agent", "cc",
          "--type", "reasoning_checkpoint", "--area", "general"])

    r = _run(["verify-reasoning", "cc"])
    assert r.returncode == 0
    assert "verification" in r.stdout.lower()
    assert "Chain integrity: OK" in r.stdout
