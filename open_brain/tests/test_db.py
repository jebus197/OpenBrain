"""Tests for database layer."""

import numpy as np
import pytest

from open_brain import db, config


def _dummy_embedding(seed=42):
    """Generate a deterministic 384-dim normalised vector."""
    rng = np.random.RandomState(seed)
    vec = rng.randn(config.EMBEDDING_DIMENSION).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec.tolist()


def test_verify_connection():
    assert db.verify_connection() is True


def test_insert_and_retrieve():
    meta = {"source_agent": "cc", "memory_type": "decision", "area": "infra"}
    mem_id = db.insert_memory("Test decision", _dummy_embedding(), meta)
    assert mem_id is not None
    assert len(mem_id) == 36  # UUID format

    results = db.list_recent(limit=1)
    assert len(results) == 1
    assert results[0]["id"] == mem_id
    assert results[0]["raw_text"] == "Test decision"
    assert results[0]["metadata"]["source_agent"] == "cc"


def test_semantic_search_relevance():
    """Insert two memories and verify the more relevant one ranks higher."""
    vec_a = _dummy_embedding(seed=1)
    vec_b = _dummy_embedding(seed=2)

    db.insert_memory("PostgreSQL migration plan", vec_a,
                     {"source_agent": "cc", "memory_type": "decision", "area": "infra"})
    db.insert_memory("UX colour palette review", vec_b,
                     {"source_agent": "cw", "memory_type": "review", "area": "ux"})

    # Search with vec_a should return PostgreSQL memory first
    results = db.semantic_search(vec_a, limit=2)
    assert len(results) == 2
    assert "PostgreSQL" in results[0]["raw_text"]
    assert results[0]["distance"] < results[1]["distance"]


def test_semantic_search_with_filter():
    vec = _dummy_embedding(seed=10)
    db.insert_memory("CC memory", vec,
                     {"source_agent": "cc", "memory_type": "insight", "area": "general"})
    db.insert_memory("CX memory", _dummy_embedding(seed=11),
                     {"source_agent": "cx", "memory_type": "insight", "area": "general"})

    results = db.semantic_search(vec, source_agent="cc")
    assert len(results) == 1
    assert results[0]["metadata"]["source_agent"] == "cc"


def test_list_recent_filters():
    db.insert_memory("A", _dummy_embedding(1),
                     {"source_agent": "cc", "memory_type": "task", "area": "web"})
    db.insert_memory("B", _dummy_embedding(2),
                     {"source_agent": "cx", "memory_type": "insight", "area": "infra"})

    results = db.list_recent(source_agent="cx")
    assert len(results) == 1
    assert results[0]["raw_text"] == "B"

    results = db.list_recent(memory_type="task")
    assert len(results) == 1
    assert results[0]["raw_text"] == "A"


def test_pending_tasks():
    db.insert_memory("Task one", _dummy_embedding(1), {
        "source_agent": "cc", "memory_type": "task",
        "action_status": "pending", "assigned_to": "cc", "area": "infra",
    })
    db.insert_memory("Task two", _dummy_embedding(2), {
        "source_agent": "cc", "memory_type": "task",
        "action_status": "completed", "assigned_to": "cc", "area": "infra",
    })
    db.insert_memory("Task three", _dummy_embedding(3), {
        "source_agent": "cc", "memory_type": "task",
        "action_status": "blocked", "assigned_to": "all", "area": "web",
    })

    results = db.get_pending_tasks(assigned_to="cc")
    assert len(results) == 2  # pending + blocked (assigned to cc or all)
    statuses = {r["metadata"]["action_status"] for r in results}
    assert statuses == {"pending", "blocked"}


def test_update_task_status():
    mem_id = db.insert_memory("Do the thing", _dummy_embedding(1), {
        "source_agent": "cc", "memory_type": "task",
        "action_status": "pending", "assigned_to": "cc", "area": "general",
    })

    updated = db.update_task_status(mem_id, "completed", "cc", note="Done")
    assert updated is True

    # Verify it's no longer pending
    results = db.get_pending_tasks(assigned_to="cc")
    assert len(results) == 0

    # Verify metadata was updated
    recent = db.list_recent(limit=1)
    meta = recent[0]["metadata"]
    assert meta["action_status"] == "completed"
    assert meta["completed_by"] == "cc"
    assert "completed_at" in meta
    assert meta["status_note"] == "Done"


def test_update_task_not_found():
    updated = db.update_task_status("00000000-0000-0000-0000-000000000000",
                                    "completed", "cc")
    assert updated is False


def test_session_context():
    # Insert data for multiple agents
    db.insert_memory("CC session summary", _dummy_embedding(1), {
        "source_agent": "cc", "memory_type": "session_summary", "area": "general",
    })
    db.insert_memory("CX insight", _dummy_embedding(2), {
        "source_agent": "cx", "memory_type": "insight", "area": "web",
    })
    db.insert_memory("Pending for CC", _dummy_embedding(3), {
        "source_agent": "cc", "memory_type": "task",
        "action_status": "pending", "assigned_to": "cc", "area": "infra",
    })
    db.insert_memory("Blocked task", _dummy_embedding(4), {
        "source_agent": "cx", "memory_type": "task",
        "action_status": "blocked", "assigned_to": "cx", "area": "governance",
    })

    ctx = db.get_session_context("cc")
    assert len(ctx["pending_tasks"]) == 1
    assert len(ctx["blocked_tasks"]) == 1
    assert len(ctx["other_agents_recent"]) >= 1  # CX insight + CX blocked task
    assert ctx["last_session_summary"] is not None
    assert "CC session summary" in ctx["last_session_summary"]["raw_text"]
    assert ctx["last_reasoning_checkpoint"] is None  # none inserted


def test_session_context_with_reasoning_checkpoint():
    """Reasoning checkpoint appears in session context when one exists."""
    db.insert_memory("Current plan: investigating hash chain bug", _dummy_embedding(1), {
        "source_agent": "cc", "memory_type": "reasoning_checkpoint", "area": "general",
    })
    db.insert_memory("CC session summary", _dummy_embedding(2), {
        "source_agent": "cc", "memory_type": "session_summary", "area": "general",
    })

    ctx = db.get_session_context("cc")
    assert ctx["last_reasoning_checkpoint"] is not None
    assert "hash chain bug" in ctx["last_reasoning_checkpoint"]["raw_text"]
    assert ctx["last_session_summary"] is not None


def test_reasoning_checkpoint_returns_most_recent():
    """When multiple reasoning checkpoints exist, session context returns the latest."""
    db.insert_memory("Old checkpoint: started analysis", _dummy_embedding(1), {
        "source_agent": "cc", "memory_type": "reasoning_checkpoint", "area": "general",
    })
    db.insert_memory("New checkpoint: analysis complete, writing tests", _dummy_embedding(2), {
        "source_agent": "cc", "memory_type": "reasoning_checkpoint", "area": "general",
    })

    ctx = db.get_session_context("cc")
    assert ctx["last_reasoning_checkpoint"] is not None
    assert "writing tests" in ctx["last_reasoning_checkpoint"]["raw_text"]


def test_reasoning_checkpoint_agent_isolation():
    """Reasoning checkpoint from another agent does not appear in session context."""
    db.insert_memory("CX reasoning state", _dummy_embedding(1), {
        "source_agent": "cx", "memory_type": "reasoning_checkpoint", "area": "general",
    })

    ctx = db.get_session_context("cc")
    assert ctx["last_reasoning_checkpoint"] is None
