"""Tests for hash chain integrity, export, import, and verification.

These are integration tests that hit the real database (open_brain_test).
"""

import json
import os
import tempfile

import pytest

from open_brain import db
from open_brain.capture import capture_memory
from open_brain.hashing import compute_content_hash, verify_chain, GENESIS_HASH


# ---------------------------------------------------------------------------
# Hash chain tests (via capture pipeline)
# ---------------------------------------------------------------------------


def test_first_memory_links_to_genesis():
    """First memory in an empty chain links to GENESIS_HASH."""
    mem_id = capture_memory(
        text="First memory ever",
        source_agent="cc",
        memory_type="insight",
        area="general",
    )

    results = db.list_recent(limit=1)
    assert len(results) == 1

    # Verify via full export (which includes hash columns)
    exported = db.export_memories()
    assert len(exported) == 1
    assert exported[0]["previous_hash"] == GENESIS_HASH
    assert exported[0]["content_hash"] is not None
    assert exported[0]["content_hash"].startswith("sha256:")


def test_chain_links_sequential():
    """Second memory links to first memory's content_hash."""
    capture_memory(
        text="Memory one",
        source_agent="cc",
        memory_type="insight",
        area="general",
    )
    capture_memory(
        text="Memory two",
        source_agent="cc",
        memory_type="decision",
        area="general",
    )

    exported = db.export_memories()
    assert len(exported) == 2
    assert exported[0]["previous_hash"] == GENESIS_HASH
    assert exported[1]["previous_hash"] == exported[0]["content_hash"]


def test_content_hash_matches_content():
    """Stored content_hash matches recomputation from raw_text + metadata."""
    capture_memory(
        text="Verify this content",
        source_agent="cc",
        memory_type="insight",
        area="infra",
    )

    exported = db.export_memories()
    mem = exported[0]
    recomputed = compute_content_hash(mem["raw_text"], mem["metadata"])
    assert mem["content_hash"] == recomputed


def test_node_id_in_metadata():
    """Capture pipeline injects node_id into metadata."""
    from open_brain import config

    capture_memory(
        text="Check node_id provenance",
        source_agent="cc",
        memory_type="insight",
        area="general",
    )

    results = db.list_recent(limit=1)
    assert "node_id" in results[0]["metadata"]
    assert results[0]["metadata"]["node_id"] == config.node_id()


def test_verify_chain_from_db():
    """Full chain verification via DB retrieval."""
    for i in range(3):
        capture_memory(
            text=f"Memory number {i}",
            source_agent="cc",
            memory_type="insight",
            area="general",
        )

    memories = db.get_all_for_verification()
    result = verify_chain(memories)
    assert result["total"] == 3
    assert result["valid"] == 3
    assert result["broken_content"] == []
    assert result["broken_chain"] == []


def test_memory_count():
    """memory_count returns correct count."""
    assert db.memory_count() == 0

    capture_memory(
        text="Counting test",
        source_agent="cc",
        memory_type="insight",
        area="general",
    )
    assert db.memory_count() == 1


def test_get_latest_content_hash():
    """get_latest_content_hash returns the most recent hash."""
    assert db.get_latest_content_hash() is None

    capture_memory(
        text="First",
        source_agent="cc",
        memory_type="insight",
        area="general",
    )
    h1 = db.get_latest_content_hash()
    assert h1 is not None
    assert h1.startswith("sha256:")

    capture_memory(
        text="Second",
        source_agent="cc",
        memory_type="insight",
        area="general",
    )
    h2 = db.get_latest_content_hash()
    assert h2 != h1  # different memory, different hash


# ---------------------------------------------------------------------------
# Export / Import tests
# ---------------------------------------------------------------------------


def test_export_empty():
    """Export from empty DB returns empty list."""
    assert db.export_memories() == []


def test_export_includes_embeddings():
    """Exported memories include embedding as list of floats."""
    capture_memory(
        text="Export test",
        source_agent="cc",
        memory_type="insight",
        area="general",
    )

    exported = db.export_memories()
    assert len(exported) == 1
    assert "embedding" in exported[0]
    assert isinstance(exported[0]["embedding"], list)
    assert len(exported[0]["embedding"]) == 384
    assert all(isinstance(x, float) for x in exported[0]["embedding"])


def test_export_chronological_order():
    """Exports are ordered by created_at ASC for chain consistency."""
    for i in range(3):
        capture_memory(
            text=f"Order test {i}",
            source_agent="cc",
            memory_type="insight",
            area="general",
        )

    exported = db.export_memories()
    assert len(exported) == 3
    # ASC order: first created is first in list
    assert "Order test 0" in exported[0]["raw_text"]
    assert "Order test 2" in exported[2]["raw_text"]


def test_import_new_memory():
    """Import a memory that doesn't exist yet."""
    capture_memory(
        text="Source memory",
        source_agent="cc",
        memory_type="insight",
        area="general",
    )

    exported = db.export_memories()
    mem = exported[0]

    # Clear the database
    import psycopg2
    from open_brain import config
    conn = psycopg2.connect(config.dsn("admin"))
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("TRUNCATE memories")
    conn.close()

    assert db.memory_count() == 0

    result = db.import_memory(mem)
    assert result == "inserted"
    assert db.memory_count() == 1

    # Verify content is intact
    verification = db.get_all_for_verification()
    assert verification[0]["content_hash"] == mem["content_hash"]


def test_import_idempotent_skip():
    """Importing same memory twice skips the duplicate."""
    capture_memory(
        text="Idempotent test",
        source_agent="cc",
        memory_type="insight",
        area="general",
    )

    exported = db.export_memories()
    mem = exported[0]

    # Import again — should skip
    result = db.import_memory(mem)
    assert result == "skipped"
    assert db.memory_count() == 1


def test_import_conflict_detection():
    """Same UUID with different content_hash is detected as conflict."""
    capture_memory(
        text="Original content",
        source_agent="cc",
        memory_type="insight",
        area="general",
    )

    exported = db.export_memories()
    mem = exported[0]

    # Tamper with the content but keep the UUID
    tampered = dict(mem)
    tampered["raw_text"] = "Tampered content"
    tampered["content_hash"] = compute_content_hash(
        "Tampered content", mem["metadata"]
    )

    result = db.import_memory(tampered)
    assert result == "conflict"
    assert db.memory_count() == 1  # original still there


def test_jsonl_roundtrip():
    """Full roundtrip: capture → export JSONL → clear → import → verify."""
    # Capture 3 memories
    for i in range(3):
        capture_memory(
            text=f"Roundtrip memory {i}",
            source_agent="cc",
            memory_type="insight",
            area="general",
        )

    # Export to JSONL
    exported = db.export_memories()
    assert len(exported) == 3

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        for mem in exported:
            f.write(json.dumps(mem, separators=(",", ":")) + "\n")
        jsonl_path = f.name

    try:
        # Clear DB
        import psycopg2
        from open_brain import config
        conn = psycopg2.connect(config.dsn("admin"))
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("TRUNCATE memories")
        conn.close()

        assert db.memory_count() == 0

        # Import from JSONL
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                mem = json.loads(line.strip())
                db.import_memory(mem)

        assert db.memory_count() == 3

        # Verify chain integrity
        memories = db.get_all_for_verification()
        result = verify_chain(memories)
        assert result["valid"] == 3
        assert result["broken_content"] == []
        assert result["broken_chain"] == []

    finally:
        os.unlink(jsonl_path)
