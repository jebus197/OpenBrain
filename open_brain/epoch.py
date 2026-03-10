"""Epoch service — batch verification via Merkle trees.

Groups memories into configurable time windows (epochs), computes a
Merkle root for each epoch, and stores the result. The root hash
anchors an entire batch of memories with a single value — suitable
for blockchain anchoring at Scale 2+ without per-memory cost.

Financial market parallel: end-of-day settlement. Trades execute
all day (memories stored continuously), but the batch is settled
and reconciled once per window (epoch sealed). The Merkle root is
the settlement hash — one proof covers every trade in the batch.

Properties:
  - Epoch windows are non-overlapping, wall-clock-aligned.
  - A memory belongs to exactly one epoch (by created_at).
  - Sealing an epoch is idempotent — re-sealing produces the same root.
  - Inclusion proofs are O(log N) per memory within an epoch.
  - The epoch chain itself is hash-linked (previous_epoch_root).

Default window: 1 hour. Configurable via OPEN_BRAIN_EPOCH_WINDOW_S
environment variable or config.json.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from open_brain import config
from open_brain.merkle import compute_root, inclusion_proof, verify_proof

logger = logging.getLogger(__name__)

# Default epoch window: 1 hour (3600 seconds).
EPOCH_WINDOW_S = int(os.getenv(
    "OPEN_BRAIN_EPOCH_WINDOW_S",
    "3600",
))


@dataclass
class EpochRecord:
    """A sealed epoch with its Merkle root."""

    epoch_id: str               # UUID
    window_start: str           # ISO 8601
    window_end: str             # ISO 8601
    merkle_root: str            # sha256:<hex>
    memory_count: int
    leaf_hashes: List[str]      # Ordered content_hash values
    previous_epoch_root: str    # Chain link to prior epoch
    sealed_at: str              # ISO 8601 when sealed
    sealed_by: str              # node_id that sealed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epoch_id": self.epoch_id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "merkle_root": self.merkle_root,
            "memory_count": self.memory_count,
            "leaf_hashes": self.leaf_hashes,
            "previous_epoch_root": self.previous_epoch_root,
            "sealed_at": self.sealed_at,
            "sealed_by": self.sealed_by,
        }


# Sentinel for the first epoch in the chain.
GENESIS_EPOCH_ROOT = "sha256:epoch_genesis"


def _align_window(dt: datetime, window_s: int) -> Tuple[datetime, datetime]:
    """Compute the epoch window boundaries for a given timestamp.

    Windows align to UTC midnight and tile forward in window_s increments.
    Example: 1-hour windows → 00:00-01:00, 01:00-02:00, etc.
    """
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = (dt - midnight).total_seconds()
    window_index = int(elapsed // window_s)
    from datetime import timedelta
    start = midnight + timedelta(seconds=window_index * window_s)
    end = start + timedelta(seconds=window_s)
    return start, end


def seal_epoch(
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
    window_s: int = EPOCH_WINDOW_S,
) -> Optional[EpochRecord]:
    """Seal an epoch: compute Merkle root for all memories in the window.

    If window_start/window_end are not provided, seals the most recent
    completed window (the one before the current time).

    Returns the EpochRecord on success, None if no memories in window
    or if the epoch was already sealed.
    """
    import uuid
    from open_brain.db import read_conn, write_conn

    now = datetime.now(timezone.utc)

    if window_start is None or window_end is None:
        # Seal the most recently completed window.
        aligned_start, aligned_end = _align_window(now, window_s)
        # If we're in the current window, seal the previous one.
        if now < aligned_end:
            from datetime import timedelta
            window_end = aligned_start
            window_start = aligned_start - timedelta(seconds=window_s)
        else:
            window_start = aligned_start
            window_end = aligned_end

    ws_iso = window_start.isoformat()
    we_iso = window_end.isoformat()

    # Check if already sealed.
    with read_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT epoch_id FROM epochs
                WHERE window_start = %s AND window_end = %s
                """,
                (ws_iso, we_iso),
            )
            if cur.fetchone():
                logger.debug("Epoch %s → %s already sealed", ws_iso, we_iso)
                return None

    # Fetch content hashes for memories in this window.
    with read_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content_hash FROM memories
                WHERE content_hash IS NOT NULL
                  AND created_at >= %s
                  AND created_at < %s
                ORDER BY created_at ASC
                """,
                (window_start, window_end),
            )
            rows = cur.fetchall()

    if not rows:
        return None

    leaf_hashes = [r[0] for r in rows]
    merkle_root = compute_root(leaf_hashes)

    # Get previous epoch root for chain linking.
    with read_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT merkle_root FROM epochs
                ORDER BY window_end DESC
                LIMIT 1
                """
            )
            prev_row = cur.fetchone()
            previous_epoch_root = prev_row[0] if prev_row else GENESIS_EPOCH_ROOT

    node = config.node_id()
    epoch_id = str(uuid.uuid4())
    sealed_at = datetime.now(timezone.utc).isoformat()

    record = EpochRecord(
        epoch_id=epoch_id,
        window_start=ws_iso,
        window_end=we_iso,
        merkle_root=merkle_root,
        memory_count=len(leaf_hashes),
        leaf_hashes=leaf_hashes,
        previous_epoch_root=previous_epoch_root,
        sealed_at=sealed_at,
        sealed_by=node,
    )

    # Persist.
    with write_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO epochs
                    (epoch_id, window_start, window_end, merkle_root,
                     memory_count, leaf_hashes, previous_epoch_root,
                     sealed_at, sealed_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (window_start, window_end) DO NOTHING
                """,
                (
                    epoch_id, ws_iso, we_iso, merkle_root,
                    len(leaf_hashes), json.dumps(leaf_hashes),
                    previous_epoch_root, sealed_at, node,
                ),
            )

    logger.info(
        "Sealed epoch %s → %s: %d memories, root=%s",
        ws_iso, we_iso, len(leaf_hashes), merkle_root[:30],
    )
    return record


def get_epoch(
    window_start: str,
    window_end: str,
) -> Optional[EpochRecord]:
    """Retrieve a sealed epoch by its window boundaries."""
    from open_brain.db import read_conn

    with read_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT epoch_id, window_start, window_end, merkle_root,
                       memory_count, leaf_hashes, previous_epoch_root,
                       sealed_at, sealed_by
                FROM epochs
                WHERE window_start = %s AND window_end = %s
                """,
                (window_start, window_end),
            )
            row = cur.fetchone()

    if not row:
        return None

    return EpochRecord(
        epoch_id=row[0],
        window_start=row[1],
        window_end=row[2],
        merkle_root=row[3],
        memory_count=row[4],
        leaf_hashes=json.loads(row[5]) if isinstance(row[5], str) else row[5],
        previous_epoch_root=row[6],
        sealed_at=row[7],
        sealed_by=row[8],
    )


def list_epochs(limit: int = 50) -> List[Dict[str, Any]]:
    """List sealed epochs, newest first."""
    from open_brain.db import read_conn

    with read_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT epoch_id, window_start, window_end, merkle_root,
                       memory_count, previous_epoch_root, sealed_at, sealed_by
                FROM epochs
                ORDER BY window_end DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    return [
        {
            "epoch_id": r[0],
            "window_start": r[1],
            "window_end": r[2],
            "merkle_root": r[3],
            "memory_count": r[4],
            "previous_epoch_root": r[5],
            "sealed_at": r[6],
            "sealed_by": r[7],
        }
        for r in rows
    ]


def prove_inclusion(
    content_hash: str,
    epoch_window_start: str,
    epoch_window_end: str,
) -> Optional[Dict[str, Any]]:
    """Generate a Merkle inclusion proof for a memory within an epoch.

    Returns:
        {
            "content_hash": str,
            "epoch_merkle_root": str,
            "proof": [(sibling_hash, direction), ...],
            "leaf_index": int,
            "epoch_window": {"start": str, "end": str},
        }
    Or None if the memory is not in this epoch.
    """
    record = get_epoch(epoch_window_start, epoch_window_end)
    if record is None:
        return None

    try:
        leaf_index = record.leaf_hashes.index(content_hash)
    except ValueError:
        return None

    proof = inclusion_proof(record.leaf_hashes, leaf_index)

    return {
        "content_hash": content_hash,
        "epoch_merkle_root": record.merkle_root,
        "proof": proof,
        "leaf_index": leaf_index,
        "epoch_window": {
            "start": record.window_start,
            "end": record.window_end,
        },
    }


def verify_inclusion(
    content_hash: str,
    proof: List[Tuple[str, int]],
    expected_root: str,
) -> bool:
    """Verify a Merkle inclusion proof.

    Pure function — no database access. Can be run by any verifier
    with only the proof, the leaf hash, and the expected root.
    """
    return verify_proof(content_hash, proof, expected_root)


def verify_epoch_chain(limit: int = 100) -> Dict[str, Any]:
    """Verify the epoch chain: each epoch's previous_epoch_root
    should match the merkle_root of the preceding epoch.

    Returns:
        {
            "total": int,
            "valid": int,
            "broken": [{"epoch_id": str, "expected": str, "actual": str}],
        }
    """
    from open_brain.db import read_conn

    with read_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT epoch_id, merkle_root, previous_epoch_root, window_start
                FROM epochs
                ORDER BY window_start ASC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    result: Dict[str, Any] = {"total": len(rows), "valid": 0, "broken": []}
    expected_prev = GENESIS_EPOCH_ROOT

    for epoch_id, merkle_root, prev_root, window_start in rows:
        if prev_root == expected_prev:
            result["valid"] += 1
        else:
            result["broken"].append({
                "epoch_id": epoch_id,
                "window_start": window_start,
                "expected": expected_prev,
                "actual": prev_root,
            })
        expected_prev = merkle_root

    return result
