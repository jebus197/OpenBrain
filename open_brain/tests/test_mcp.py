"""Tests for MCP server — tool registration and dispatch."""

import json
import pytest

from open_brain.mcp_server import TOOLS, _dispatch, _throttle
from open_brain import config


def test_tool_count():
    assert len(TOOLS) == 6


def test_tool_names():
    names = {t.name for t in TOOLS}
    expected = {
        "capture_memory", "semantic_search", "list_recent",
        "get_pending_tasks", "update_task_status", "get_session_context",
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
