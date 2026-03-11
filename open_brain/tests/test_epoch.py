"""Tests for epoch service — sealing, chain linking, anchoring, verification."""

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from open_brain import config, db
from open_brain.epoch import (
    EpochRecord,
    GENESIS_EPOCH_ROOT,
    _align_window,
    seal_epoch,
    get_epoch,
    list_epochs,
    prove_inclusion,
    prove_memory,
    record_anchor,
    get_unanchored_epochs,
    verify_epoch_chain,
)


def _dummy_embedding(seed=42):
    rng = np.random.RandomState(seed)
    vec = rng.randn(config.EMBEDDING_DIMENSION).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec.tolist()


def _insert_in_window(text, window_start, offset_minutes=0, seed=None):
    """Insert a memory with created_at inside a specific epoch window."""
    from open_brain.db import write_conn

    meta = {"source_agent": "cc", "memory_type": "insight", "area": "general"}
    mem_id = db.insert_memory(
        text,
        _dummy_embedding(seed or hash(text) % 10000),
        meta,
    )
    # Override created_at to place it in the target window.
    created = window_start + timedelta(minutes=offset_minutes)
    with write_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE memories SET created_at = %s WHERE id = %s",
                (created, mem_id),
            )
    return mem_id


# ---------------------------------------------------------------------------
# _align_window
# ---------------------------------------------------------------------------


def test_align_window_midnight():
    dt = datetime(2026, 3, 11, 0, 30, 0, tzinfo=timezone.utc)
    start, end = _align_window(dt, 3600)
    assert start == datetime(2026, 3, 11, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 11, 1, 0, 0, tzinfo=timezone.utc)


def test_align_window_afternoon():
    dt = datetime(2026, 3, 11, 14, 45, 0, tzinfo=timezone.utc)
    start, end = _align_window(dt, 3600)
    assert start == datetime(2026, 3, 11, 14, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 11, 15, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# seal_epoch
# ---------------------------------------------------------------------------


def test_seal_epoch_basic():
    """Seal an epoch containing memories and verify the record."""
    ws = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    we = datetime(2020, 1, 1, 1, 0, 0, tzinfo=timezone.utc)

    _insert_in_window("Epoch memory A", ws, offset_minutes=10, seed=1)
    _insert_in_window("Epoch memory B", ws, offset_minutes=20, seed=2)
    _insert_in_window("Epoch memory C", ws, offset_minutes=30, seed=3)

    record = seal_epoch(window_start=ws, window_end=we)
    assert record is not None
    assert isinstance(record, EpochRecord)
    assert record.memory_count == 3
    assert record.merkle_root.startswith("sha256:")
    assert record.previous_epoch_root == GENESIS_EPOCH_ROOT
    assert len(record.leaf_hashes) == 3


def test_seal_epoch_idempotent():
    """Re-sealing the same window returns None (already sealed)."""
    ws = datetime(2020, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    we = datetime(2020, 2, 1, 1, 0, 0, tzinfo=timezone.utc)

    _insert_in_window("Idempotent test", ws, offset_minutes=5, seed=10)

    first = seal_epoch(window_start=ws, window_end=we)
    assert first is not None

    second = seal_epoch(window_start=ws, window_end=we)
    assert second is None


def test_seal_epoch_empty_window():
    """Sealing a window with no memories returns None."""
    ws = datetime(2019, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    we = datetime(2019, 1, 1, 1, 0, 0, tzinfo=timezone.utc)
    record = seal_epoch(window_start=ws, window_end=we)
    assert record is None


# ---------------------------------------------------------------------------
# Epoch chain linking
# ---------------------------------------------------------------------------


def test_epoch_chain_linking():
    """Second epoch links to first epoch's merkle_root."""
    ws1 = datetime(2020, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
    we1 = datetime(2020, 3, 1, 1, 0, 0, tzinfo=timezone.utc)
    ws2 = datetime(2020, 3, 1, 1, 0, 0, tzinfo=timezone.utc)
    we2 = datetime(2020, 3, 1, 2, 0, 0, tzinfo=timezone.utc)

    _insert_in_window("Chain A", ws1, offset_minutes=5, seed=20)
    _insert_in_window("Chain B", ws2, offset_minutes=5, seed=21)

    first = seal_epoch(window_start=ws1, window_end=we1)
    second = seal_epoch(window_start=ws2, window_end=we2)

    assert first is not None
    assert second is not None
    assert first.previous_epoch_root == GENESIS_EPOCH_ROOT
    assert second.previous_epoch_root == first.merkle_root


# ---------------------------------------------------------------------------
# get_epoch / list_epochs
# ---------------------------------------------------------------------------


def test_get_epoch_retrieves_sealed():
    ws = datetime(2020, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
    we = datetime(2020, 4, 1, 1, 0, 0, tzinfo=timezone.utc)
    _insert_in_window("Retrieve test", ws, offset_minutes=15, seed=30)
    seal_epoch(window_start=ws, window_end=we)

    record = get_epoch(ws.isoformat(), we.isoformat())
    assert record is not None
    assert record.memory_count == 1


def test_get_epoch_returns_none_for_unsealed():
    ws = datetime(2019, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    we = datetime(2019, 6, 1, 1, 0, 0, tzinfo=timezone.utc)
    record = get_epoch(ws.isoformat(), we.isoformat())
    assert record is None


def test_list_epochs_returns_sealed():
    ws = datetime(2020, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    we = datetime(2020, 5, 1, 1, 0, 0, tzinfo=timezone.utc)
    _insert_in_window("List test", ws, offset_minutes=10, seed=40)
    seal_epoch(window_start=ws, window_end=we)

    epochs = list_epochs(limit=100)
    assert len(epochs) >= 1
    assert any(e["window_start"] == ws.isoformat() for e in epochs)


# ---------------------------------------------------------------------------
# prove_inclusion / prove_memory
# ---------------------------------------------------------------------------


def test_prove_inclusion_returns_proof():
    ws = datetime(2020, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    we = datetime(2020, 6, 1, 1, 0, 0, tzinfo=timezone.utc)
    _insert_in_window("Inclusion A", ws, offset_minutes=10, seed=50)
    _insert_in_window("Inclusion B", ws, offset_minutes=20, seed=51)

    record = seal_epoch(window_start=ws, window_end=we)
    assert record is not None

    proof = prove_inclusion(
        record.leaf_hashes[0], ws.isoformat(), we.isoformat()
    )
    assert proof is not None
    assert proof["content_hash"] == record.leaf_hashes[0]
    assert proof["epoch_merkle_root"] == record.merkle_root
    assert proof["leaf_index"] == 0


def test_prove_memory_auto_boundary():
    """prove_memory auto-detects epoch window from created_at."""
    ws = datetime(2020, 7, 1, 3, 0, 0, tzinfo=timezone.utc)
    we = datetime(2020, 7, 1, 4, 0, 0, tzinfo=timezone.utc)
    _insert_in_window("Auto boundary", ws, offset_minutes=15, seed=60)

    record = seal_epoch(window_start=ws, window_end=we)
    assert record is not None

    created_at = (ws + timedelta(minutes=15)).isoformat()
    proof = prove_memory(record.leaf_hashes[0], created_at)
    assert proof is not None
    assert proof["epoch_merkle_root"] == record.merkle_root


# ---------------------------------------------------------------------------
# record_anchor / get_unanchored_epochs
# ---------------------------------------------------------------------------


def test_record_anchor_stores_metadata():
    ws = datetime(2020, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
    we = datetime(2020, 8, 1, 1, 0, 0, tzinfo=timezone.utc)
    _insert_in_window("Anchor test", ws, offset_minutes=5, seed=70)

    record = seal_epoch(window_start=ws, window_end=we)
    assert record is not None

    anchor_meta = {
        "proof_type": "ethereum",
        "tx_hash": "0xabc123",
        "block_number": 12345,
        "chain_id": 11155111,
        "verifier_uri": "https://sepolia.etherscan.io/tx/0xabc123",
    }
    updated = record_anchor(
        record.epoch_id, "2026-03-11T00:00:00+00:00", anchor_meta
    )
    assert updated is True

    # Retrieve and verify JSONB round-trip
    epoch = get_epoch(ws.isoformat(), we.isoformat())
    assert epoch.anchored_at == "2026-03-11T00:00:00+00:00"
    assert epoch.anchor_metadata["proof_type"] == "ethereum"
    assert epoch.anchor_metadata["tx_hash"] == "0xabc123"
    assert epoch.anchor_metadata["block_number"] == 12345


def test_record_anchor_ethereum_schema():
    ws = datetime(2020, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    we = datetime(2020, 9, 1, 1, 0, 0, tzinfo=timezone.utc)
    _insert_in_window("ETH anchor", ws, offset_minutes=5, seed=80)

    record = seal_epoch(window_start=ws, window_end=we)
    anchor_meta = {
        "proof_type": "ethereum",
        "tx_hash": "0xdef456",
        "block_number": 99999,
        "chain_id": 1,
        "verifier_uri": "https://etherscan.io/tx/0xdef456",
    }
    record_anchor(record.epoch_id, "2026-03-11T01:00:00+00:00", anchor_meta)

    epoch = get_epoch(ws.isoformat(), we.isoformat())
    meta = epoch.anchor_metadata
    assert meta["proof_type"] == "ethereum"
    assert all(k in meta for k in ["tx_hash", "block_number", "chain_id", "verifier_uri"])


def test_record_anchor_ots_schema():
    ws = datetime(2020, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
    we = datetime(2020, 10, 1, 1, 0, 0, tzinfo=timezone.utc)
    _insert_in_window("OTS anchor", ws, offset_minutes=5, seed=90)

    record = seal_epoch(window_start=ws, window_end=we)
    anchor_meta = {
        "proof_type": "ots",
        "bitcoin_block": 800000,
        "ots_proof": "base64encodedproof==",
    }
    record_anchor(record.epoch_id, "2026-03-11T02:00:00+00:00", anchor_meta)

    epoch = get_epoch(ws.isoformat(), we.isoformat())
    meta = epoch.anchor_metadata
    assert meta["proof_type"] == "ots"
    assert meta["bitcoin_block"] == 800000


def test_record_anchor_returns_false_for_missing():
    updated = record_anchor(
        "00000000-0000-0000-0000-000000000000",
        "2026-01-01T00:00:00+00:00",
        {"proof_type": "ethereum"},
    )
    assert updated is False


def test_get_unanchored_epochs():
    ws1 = datetime(2020, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
    we1 = datetime(2020, 11, 1, 1, 0, 0, tzinfo=timezone.utc)
    ws2 = datetime(2020, 11, 1, 1, 0, 0, tzinfo=timezone.utc)
    we2 = datetime(2020, 11, 1, 2, 0, 0, tzinfo=timezone.utc)

    _insert_in_window("Unanchored A", ws1, offset_minutes=5, seed=100)
    _insert_in_window("Unanchored B", ws2, offset_minutes=5, seed=101)

    r1 = seal_epoch(window_start=ws1, window_end=we1)
    r2 = seal_epoch(window_start=ws2, window_end=we2)

    # Anchor only the first
    record_anchor(r1.epoch_id, "2026-03-11T03:00:00+00:00",
                  {"proof_type": "ethereum", "tx_hash": "0x111"})

    unanchored = get_unanchored_epochs()
    epoch_ids = [e["epoch_id"] for e in unanchored]
    assert r2.epoch_id in epoch_ids
    assert r1.epoch_id not in epoch_ids


# ---------------------------------------------------------------------------
# verify_epoch_chain
# ---------------------------------------------------------------------------


def test_verify_epoch_chain_valid():
    ws1 = datetime(2020, 12, 1, 0, 0, 0, tzinfo=timezone.utc)
    we1 = datetime(2020, 12, 1, 1, 0, 0, tzinfo=timezone.utc)
    ws2 = datetime(2020, 12, 1, 1, 0, 0, tzinfo=timezone.utc)
    we2 = datetime(2020, 12, 1, 2, 0, 0, tzinfo=timezone.utc)

    _insert_in_window("Valid chain A", ws1, offset_minutes=5, seed=110)
    _insert_in_window("Valid chain B", ws2, offset_minutes=5, seed=111)

    seal_epoch(window_start=ws1, window_end=we1)
    seal_epoch(window_start=ws2, window_end=we2)

    result = verify_epoch_chain()
    assert result["total"] >= 2
    assert result["valid"] >= 2
    assert len(result["broken"]) == 0


def test_verify_epoch_chain_detects_break():
    """Breaking the previous_epoch_root should be detected."""
    ws1 = datetime(2021, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    we1 = datetime(2021, 1, 1, 1, 0, 0, tzinfo=timezone.utc)
    ws2 = datetime(2021, 1, 1, 1, 0, 0, tzinfo=timezone.utc)
    we2 = datetime(2021, 1, 1, 2, 0, 0, tzinfo=timezone.utc)

    _insert_in_window("Break A", ws1, offset_minutes=5, seed=120)
    _insert_in_window("Break B", ws2, offset_minutes=5, seed=121)

    r1 = seal_epoch(window_start=ws1, window_end=we1)
    r2 = seal_epoch(window_start=ws2, window_end=we2)

    # Tamper with the chain link
    from open_brain.db import write_conn
    with write_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE epochs SET previous_epoch_root = %s WHERE epoch_id = %s",
                ("sha256:tampered_root", r2.epoch_id),
            )

    result = verify_epoch_chain()
    assert len(result["broken"]) >= 1
    broken_ids = [b["epoch_id"] for b in result["broken"]]
    assert r2.epoch_id in broken_ids
