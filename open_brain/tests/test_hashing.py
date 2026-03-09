"""Tests for content hashing and hash chain verification."""

import json

from open_brain.hashing import (
    compute_content_hash,
    verify_content_hash,
    verify_chain,
    GENESIS_HASH,
)


def test_compute_content_hash_deterministic():
    """Same input always produces same hash."""
    h1 = compute_content_hash("hello", {"agent": "cc"})
    h2 = compute_content_hash("hello", {"agent": "cc"})
    assert h1 == h2
    assert h1.startswith("sha256:")
    assert len(h1) == 71  # "sha256:" + 64 hex chars


def test_compute_content_hash_different_text():
    """Different text produces different hash."""
    h1 = compute_content_hash("hello", {"agent": "cc"})
    h2 = compute_content_hash("world", {"agent": "cc"})
    assert h1 != h2


def test_compute_content_hash_different_metadata():
    """Different metadata produces different hash."""
    h1 = compute_content_hash("hello", {"agent": "cc"})
    h2 = compute_content_hash("hello", {"agent": "cx"})
    assert h1 != h2


def test_compute_content_hash_key_order_invariant():
    """Metadata key order does not affect hash (sorted keys)."""
    h1 = compute_content_hash("hello", {"a": 1, "b": 2})
    h2 = compute_content_hash("hello", {"b": 2, "a": 1})
    assert h1 == h2


def test_verify_content_hash_valid():
    h = compute_content_hash("test", {"type": "insight"})
    assert verify_content_hash("test", {"type": "insight"}, h) is True


def test_verify_content_hash_tampered():
    h = compute_content_hash("test", {"type": "insight"})
    assert verify_content_hash("tampered", {"type": "insight"}, h) is False


def test_verify_chain_empty():
    result = verify_chain([])
    assert result["total"] == 0
    assert result["valid"] == 0
    assert result["unhashed"] == 0
    assert result["broken_content"] == []
    assert result["broken_chain"] == []


def test_verify_chain_single_valid():
    h = compute_content_hash("first memory", {"agent": "cc"})
    memories = [{
        "id": "aaa",
        "raw_text": "first memory",
        "metadata": {"agent": "cc"},
        "content_hash": h,
        "previous_hash": GENESIS_HASH,
    }]
    result = verify_chain(memories)
    assert result["total"] == 1
    assert result["valid"] == 1
    assert result["broken_content"] == []
    assert result["broken_chain"] == []


def test_verify_chain_valid_sequence():
    """Three memories with correct chain links."""
    h1 = compute_content_hash("first", {"n": 1})
    h2 = compute_content_hash("second", {"n": 2})
    h3 = compute_content_hash("third", {"n": 3})
    memories = [
        {"id": "1", "raw_text": "first", "metadata": {"n": 1},
         "content_hash": h1, "previous_hash": GENESIS_HASH},
        {"id": "2", "raw_text": "second", "metadata": {"n": 2},
         "content_hash": h2, "previous_hash": h1},
        {"id": "3", "raw_text": "third", "metadata": {"n": 3},
         "content_hash": h3, "previous_hash": h2},
    ]
    result = verify_chain(memories)
    assert result["valid"] == 3
    assert result["broken_content"] == []
    assert result["broken_chain"] == []


def test_verify_chain_broken_content():
    """Tampered content detected by hash mismatch."""
    h = compute_content_hash("original", {"n": 1})
    memories = [{
        "id": "1",
        "raw_text": "tampered",  # content changed
        "metadata": {"n": 1},
        "content_hash": h,  # hash still points to "original"
        "previous_hash": GENESIS_HASH,
    }]
    result = verify_chain(memories)
    assert result["valid"] == 0
    assert len(result["broken_content"]) == 1
    assert result["broken_content"][0]["id"] == "1"


def test_verify_chain_broken_link():
    """Deleted or reordered memory detected by chain link mismatch."""
    h1 = compute_content_hash("first", {"n": 1})
    h2 = compute_content_hash("second", {"n": 2})
    memories = [
        {"id": "1", "raw_text": "first", "metadata": {"n": 1},
         "content_hash": h1, "previous_hash": GENESIS_HASH},
        {"id": "2", "raw_text": "second", "metadata": {"n": 2},
         "content_hash": h2, "previous_hash": "sha256:wrong"},  # broken link
    ]
    result = verify_chain(memories)
    assert result["valid"] == 2  # content is valid
    assert len(result["broken_chain"]) == 1
    assert result["broken_chain"][0]["id"] == "2"


def test_verify_chain_unhashed_memories():
    """Pre-migration memories (no content_hash) are counted but skipped."""
    memories = [
        {"id": "1", "raw_text": "old", "metadata": {},
         "content_hash": None, "previous_hash": None},
        {"id": "2", "raw_text": "also old", "metadata": {},
         "content_hash": None, "previous_hash": None},
    ]
    result = verify_chain(memories)
    assert result["total"] == 2
    assert result["unhashed"] == 2
    assert result["valid"] == 0
    assert result["broken_content"] == []
    assert result["broken_chain"] == []


def test_genesis_hash_constant():
    assert GENESIS_HASH == "sha256:genesis"
