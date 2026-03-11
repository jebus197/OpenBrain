"""Tests for MCP server — tool registration and dispatch."""

import json
import pytest

from open_brain.mcp_server import TOOLS, _dispatch, _throttle
from open_brain import config


def test_tool_count():
    assert len(TOOLS) == 10


def test_tool_names():
    names = {t.name for t in TOOLS}
    expected = {
        "capture_memory", "semantic_search", "list_recent",
        "get_pending_tasks", "update_task_status", "get_session_context",
        "assemble_proof", "get_reasoning_chain",
        "verify_reasoning_chain", "record_anchor",
    }
    assert names == expected


def test_capture_dispatch():
    result = _dispatch("capture_memory", {
        "text": "MCP test capture",
        "source_agent": "cc",
        "memory_type": "insight",
        "area": "general",
    })
    assert "id" in result
    assert result["status"] == "stored"
    assert len(result["id"]) == 36


def test_search_dispatch():
    # First capture something
    _dispatch("capture_memory", {
        "text": "MCP search test memory",
        "source_agent": "cc",
        "memory_type": "decision",
        "area": "infra",
    })

    result = _dispatch("semantic_search", {
        "query": "MCP search test",
        "limit": 5,
    })
    assert isinstance(result, list)
    assert len(result) >= 1
    assert "MCP search test" in result[0]["raw_text"]


def test_session_context_dispatch():
    result = _dispatch("get_session_context", {"agent": "cc"})
    assert "pending_tasks" in result
    assert "blocked_tasks" in result
    assert "other_agents_recent" in result
    assert "last_session_summary" in result


def test_unknown_tool():
    with pytest.raises(ValueError, match="Unknown tool"):
        _dispatch("nonexistent_tool", {})


def test_throttle():
    # Create results that exceed token budget
    big_text = "word " * 500  # ~650 tokens
    results = [
        {"raw_text": big_text, "id": "a"},
        {"raw_text": big_text, "id": "b"},
        {"raw_text": big_text, "id": "c"},
        {"raw_text": big_text, "id": "d"},
    ]
    throttled = _throttle(results)
    assert len(throttled) < len(results)
    # Total tokens should be under budget
    total = sum(config.estimate_tokens(r["raw_text"]) for r in throttled)
    assert total <= config.TOKEN_BUDGET


# ---------------------------------------------------------------------------
# Reasoning / proof MCP tools
# ---------------------------------------------------------------------------


def test_assemble_proof_dispatch():
    """assemble_proof tool returns proof package for existing memory."""
    capture = _dispatch("capture_memory", {
        "text": "MCP proof test",
        "source_agent": "cc",
        "memory_type": "reasoning_checkpoint",
        "area": "general",
    })
    mem_id = capture["id"]

    result = _dispatch("assemble_proof", {"memory_id": mem_id})
    assert result["memory_id"] == mem_id
    assert result["raw_text"] == "MCP proof test"
    assert result["content_hash"].startswith("sha256:")


def test_assemble_proof_dispatch_missing():
    result = _dispatch("assemble_proof", {
        "memory_id": "00000000-0000-0000-0000-000000000000",
    })
    assert "error" in result


def test_get_reasoning_chain_dispatch():
    _dispatch("capture_memory", {
        "text": "MCP chain test",
        "source_agent": "cc",
        "memory_type": "reasoning_checkpoint",
        "area": "general",
    })

    result = _dispatch("get_reasoning_chain", {"agent": "cc", "limit": 10})
    assert isinstance(result, list)
    assert len(result) >= 1
    assert result[0]["raw_text"] == "MCP chain test"


def test_verify_reasoning_chain_dispatch():
    _dispatch("capture_memory", {
        "text": "MCP verify test",
        "source_agent": "cc",
        "memory_type": "reasoning_checkpoint",
        "area": "general",
    })

    result = _dispatch("verify_reasoning_chain", {"agent": "cc"})
    assert "total" in result
    assert result["total"] >= 1
    assert "hash_chain_intact" in result


def test_record_anchor_dispatch_missing_epoch():
    result = _dispatch("record_anchor", {
        "epoch_id": "00000000-0000-0000-0000-000000000000",
        "anchored_at": "2026-01-01T00:00:00+00:00",
        "anchor_metadata": {"proof_type": "ethereum", "tx_hash": "0x0"},
    })
    assert result["updated"] is False
