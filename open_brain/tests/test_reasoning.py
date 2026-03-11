"""Tests for reasoning verification: proof assembly, chain verification, export."""

import json

import numpy as np
import pytest

from open_brain import config, db
from open_brain.hashing import compute_content_hash, GENESIS_HASH
from open_brain.reasoning import (
    ProofPackage,
    assemble_proof,
    get_reasoning_chain,
    verify_reasoning_chain,
    export_reasoning_proof,
    ChainVerification,
)


def _dummy_embedding(seed=42):
    rng = np.random.RandomState(seed)
    vec = rng.randn(config.EMBEDDING_DIMENSION).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec.tolist()


def _insert_checkpoint(text, agent="cc", session_id="sess-1", seed=None,
                       previous_hash=None):
    """Insert a reasoning checkpoint and return its memory ID."""
    meta = {
        "source_agent": agent,
        "memory_type": "reasoning_checkpoint",
        "area": "general",
    }
    if session_id:
        meta["session_id"] = session_id

    mem_id = db.insert_memory(
        text,
        _dummy_embedding(seed or hash(text) % 10000),
        meta,
    )
    return mem_id


def _build_chain(agent="cc", session_id="sess-1", count=3):
    """Build a reasoning chain of `count` checkpoints, return their IDs."""
    ids = []
    for i in range(count):
        mem_id = _insert_checkpoint(
            f"Reasoning step {i}: considering option {chr(65 + i)}",
            agent=agent,
            session_id=session_id,
            seed=i + 100,
        )
        ids.append(mem_id)
    return ids


# ---------------------------------------------------------------------------
# ProofPackage
# ---------------------------------------------------------------------------


def test_proof_package_to_dict():
    pkg = ProofPackage(
        memory_id="test-uuid",
        raw_text="test content",
        metadata={"agent": "cc"},
        content_hash="sha256:abc",
        signature="sig123",
        public_key_pem="pem-data",
        merkle_proof=None,
        anchor=None,
        created_at="2026-01-01T00:00:00",
        generated_at="2026-01-01T00:00:01",
    )
    d = pkg.to_dict()
    assert d["memory_id"] == "test-uuid"
    assert d["raw_text"] == "test content"
    assert d["content_hash"] == "sha256:abc"
    assert d["merkle_proof"] is None


def test_proof_package_to_json():
    pkg = ProofPackage(
        memory_id="test-uuid",
        raw_text="test",
        metadata={},
        content_hash="sha256:abc",
        signature=None,
        public_key_pem=None,
        merkle_proof=None,
        anchor=None,
        created_at="2026-01-01T00:00:00",
        generated_at="2026-01-01T00:00:01",
    )
    j = pkg.to_json()
    parsed = json.loads(j)
    assert parsed["memory_id"] == "test-uuid"


# ---------------------------------------------------------------------------
# assemble_proof
# ---------------------------------------------------------------------------


def test_assemble_proof_returns_none_for_missing():
    result = assemble_proof("00000000-0000-0000-0000-000000000000")
    assert result is None


def test_assemble_proof_returns_package():
    mem_id = _insert_checkpoint("Proof test: evaluating trade-offs")
    proof = assemble_proof(mem_id)
    assert proof is not None
    assert isinstance(proof, ProofPackage)
    assert proof.memory_id == mem_id
    assert proof.raw_text == "Proof test: evaluating trade-offs"
    assert proof.content_hash.startswith("sha256:")
    assert proof.created_at is not None
    assert proof.generated_at is not None


def test_assemble_proof_has_content_hash():
    mem_id = _insert_checkpoint("Hash verification step")
    proof = assemble_proof(mem_id)
    assert proof.content_hash.startswith("sha256:")
    assert len(proof.content_hash) == 71  # sha256: + 64 hex


def test_assemble_proof_merkle_none_when_unsealed():
    """Before epoch sealing, merkle_proof should be None."""
    mem_id = _insert_checkpoint("No epoch yet")
    proof = assemble_proof(mem_id)
    # Epoch not sealed, so merkle proof should be None
    assert proof.merkle_proof is None


# ---------------------------------------------------------------------------
# get_reasoning_chain
# ---------------------------------------------------------------------------


def test_get_reasoning_chain_empty():
    chain = get_reasoning_chain("nonexistent-agent")
    assert chain == []


def test_get_reasoning_chain_returns_ordered():
    ids = _build_chain(agent="cc", session_id="sess-ord", count=5)
    chain = get_reasoning_chain("cc", session_id="sess-ord")
    assert len(chain) == 5
    # Chronological order (oldest first)
    for i in range(1, len(chain)):
        assert chain[i]["created_at"] >= chain[i - 1]["created_at"]


def test_get_reasoning_chain_filters_by_agent():
    _build_chain(agent="cc", session_id="sess-a", count=3)
    _build_chain(agent="cx", session_id="sess-b", count=2)
    cc_chain = get_reasoning_chain("cc")
    cx_chain = get_reasoning_chain("cx")
    assert len(cc_chain) == 3
    assert len(cx_chain) == 2
    for cp in cc_chain:
        assert cp["metadata"]["source_agent"] == "cc"


def test_get_reasoning_chain_filters_by_session():
    _build_chain(agent="cc", session_id="sess-x", count=3)
    _build_chain(agent="cc", session_id="sess-y", count=2)
    chain_x = get_reasoning_chain("cc", session_id="sess-x")
    chain_y = get_reasoning_chain("cc", session_id="sess-y")
    assert len(chain_x) == 3
    assert len(chain_y) == 2


def test_get_reasoning_chain_respects_limit():
    _build_chain(agent="cc", session_id="sess-lim", count=10)
    chain = get_reasoning_chain("cc", session_id="sess-lim", limit=3)
    assert len(chain) == 3


# ---------------------------------------------------------------------------
# verify_reasoning_chain
# ---------------------------------------------------------------------------


def test_verify_reasoning_chain_empty():
    result = verify_reasoning_chain("nonexistent")
    assert result.total == 0
    assert result.valid == 0
    assert result.hash_chain_intact is True


def test_verify_reasoning_chain_valid():
    _build_chain(agent="cc", session_id="sess-v", count=3)
    result = verify_reasoning_chain("cc", session_id="sess-v")
    assert result.total == 3
    # All should have valid content hashes
    assert result.valid >= 1  # At least some valid


def test_verify_reasoning_chain_detects_tamper():
    """Tampering with a memory's raw_text should be detected."""
    ids = _build_chain(agent="cc", session_id="sess-t", count=3)

    # Tamper with the second checkpoint's raw_text directly in DB
    from open_brain.db import write_conn
    with write_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE memories SET raw_text = %s WHERE id = %s",
                ("TAMPERED CONTENT", ids[1]),
            )

    result = verify_reasoning_chain("cc", session_id="sess-t")
    # Should detect content hash mismatch
    content_breaks = [b for b in result.breaks if b["check"] == "content_hash"]
    assert len(content_breaks) >= 1


def test_verify_reasoning_chain_detects_chain_break():
    """Breaking the previous_hash link should be detected."""
    ids = _build_chain(agent="cc", session_id="sess-b", count=3)

    # Break the chain link
    from open_brain.db import write_conn
    with write_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE memories SET previous_hash = %s WHERE id = %s",
                ("sha256:bogus_hash", ids[2]),
            )

    result = verify_reasoning_chain("cc", session_id="sess-b")
    assert result.hash_chain_intact is False
    chain_breaks = [b for b in result.breaks if b["check"] == "chain_continuity"]
    assert len(chain_breaks) >= 1


# ---------------------------------------------------------------------------
# export_reasoning_proof
# ---------------------------------------------------------------------------


def test_export_reasoning_proof_empty():
    result = export_reasoning_proof("nonexistent")
    assert result["version"] == "1.0"
    assert result["checkpoints"] == []


def test_export_reasoning_proof_is_self_contained():
    _build_chain(agent="cc", session_id="sess-e", count=3)
    result = export_reasoning_proof("cc", session_id="sess-e")

    # Must be JSON-serialisable
    json_str = json.dumps(result)
    parsed = json.loads(json_str)
    assert parsed is not None

    # Required top-level fields
    assert "version" in result
    assert "agent" in result
    assert "checkpoints" in result
    assert "generated_at" in result
    assert "verification_instructions" in result

    # Each checkpoint must have required fields
    for cp in result["checkpoints"]:
        assert "memory_id" in cp
        assert "raw_text" in cp
        assert "content_hash" in cp
        assert "created_at" in cp


def test_export_includes_verification_instructions():
    _build_chain(agent="cc", session_id="sess-vi", count=1)
    result = export_reasoning_proof("cc", session_id="sess-vi")
    vi = result["verification_instructions"]
    assert "content_hash" in vi
    assert "SHA-256" in vi["content_hash"]
    assert "signature" in vi
    assert "Ed25519" in vi["signature"]
    assert "merkle_proof" in vi
    assert "anchor" in vi
