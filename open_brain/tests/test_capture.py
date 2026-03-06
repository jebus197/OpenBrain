"""Tests for capture pipeline."""

import pytest

from open_brain import db
from open_brain.capture import capture_memory, embed_text, CaptureError


def test_embed_text_dimensions():
    vec = embed_text("Hello world")
    assert len(vec) == 384
    # Should be normalised (L2 norm ~1.0)
    import numpy as np
    norm = np.linalg.norm(vec)
    assert abs(norm - 1.0) < 0.01


def test_capture_roundtrip():
    mem_id = capture_memory(
        text="Test insight from capture pipeline",
        source_agent="cc",
        memory_type="insight",
        area="infra",
    )
    assert len(mem_id) == 36

    results = db.list_recent(limit=1)
    assert len(results) == 1
    assert results[0]["id"] == mem_id
    assert "capture pipeline" in results[0]["raw_text"]


def test_capture_task_requires_status():
    with pytest.raises(CaptureError, match="action_status"):
        capture_memory(
            text="A task without status",
            source_agent="cc",
            memory_type="task",
            area="general",
        )


def test_capture_invalid_agent():
    # Empty string is always rejected (even in open mode)
    with pytest.raises(CaptureError, match="source_agent"):
        capture_memory(
            text="Bad agent",
            source_agent="",
            memory_type="insight",
            area="general",
        )


def test_capture_invalid_type():
    with pytest.raises(CaptureError, match="memory_type"):
        capture_memory(
            text="Bad type",
            source_agent="cc",
            memory_type="nonexistent",
            area="general",
        )


def test_capture_invalid_area():
    with pytest.raises(CaptureError, match="area"):
        capture_memory(
            text="Bad area",
            source_agent="cc",
            memory_type="insight",
            area="nonexistent",
        )


def test_capture_task_full_lifecycle():
    mem_id = capture_memory(
        text="Implement feature X",
        source_agent="cx",
        memory_type="task",
        area="frontend",
        action_status="pending",
        assigned_to="cc",
        priority="high",
    )

    results = db.get_pending_tasks(assigned_to="cc")
    assert len(results) == 1
    assert results[0]["metadata"]["priority"] == "high"
    assert results[0]["metadata"]["assigned_to"] == "cc"
