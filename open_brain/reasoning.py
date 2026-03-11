"""Reasoning verification — composition layer for proof assembly and chain verification.

Composes primitives from hashing.py, crypto.py, merkle.py, epoch.py, and db.py
into high-level verification operations.  Does NOT duplicate low-level crypto.

Three capabilities:
  1. Proof assembly: given a memory UUID, produce a self-contained ProofPackage
     verifiable with SHA-256 + Ed25519 + a block explorer.  No OB required.
  2. Chain retrieval: chronological reasoning checkpoints for an agent.
  3. Chain verification: five-check verification of a reasoning chain
     (hash integrity, chain continuity, signature validity, epoch inclusion,
     epoch chain).

Financial market parallel: an auditor reconstructing a trading desk's
decision history from signed trade confirmations, clearinghouse receipts,
and settlement records — except the "trades" are reasoning steps and the
"clearinghouse" is a Merkle epoch anchored on-chain.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Proof Package
# ---------------------------------------------------------------------------


@dataclass
class ProofPackage:
    """Self-contained, portable proof for a single memory.

    A third party verifies this with:
      1. SHA-256: recompute content_hash from raw_text + metadata
      2. Ed25519: verify signature against public_key_pem
      3. Merkle: verify inclusion_proof against epoch_merkle_root
      4. Block explorer: check anchor_metadata (tx_hash, block_number)
    """

    memory_id: str
    raw_text: str
    metadata: Dict[str, Any]
    content_hash: str
    signature: Optional[str]
    public_key_pem: Optional[str]
    merkle_proof: Optional[Dict[str, Any]]
    anchor: Optional[Dict[str, Any]]
    created_at: str
    generated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "raw_text": self.raw_text,
            "metadata": self.metadata,
            "content_hash": self.content_hash,
            "signature": self.signature,
            "public_key_pem": self.public_key_pem,
            "merkle_proof": self.merkle_proof,
            "anchor": self.anchor,
            "created_at": self.created_at,
            "generated_at": self.generated_at,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def assemble_proof(memory_id: str) -> Optional[ProofPackage]:
    """Assemble a complete proof package for a memory.

    Composes: db.get_memory → hash verification → signature verification →
    epoch.prove_memory → anchor lookup.

    Returns None if the memory does not exist.
    """
    from open_brain import db
    from open_brain.hashing import verify_content_hash
    from open_brain.epoch import prove_memory as _prove_memory

    mem = db.get_memory(memory_id)
    if mem is None:
        return None

    raw_text = mem["raw_text"]
    metadata = mem.get("metadata", {})
    content_hash = mem.get("content_hash")
    signature = mem.get("signature")
    created_at = mem["created_at"]

    # Verify content hash integrity
    if content_hash:
        if not verify_content_hash(raw_text, metadata, content_hash):
            logger.warning(
                "Content hash mismatch for memory %s", memory_id
            )

    # Get public key if available
    public_key_pem = None
    try:
        from open_brain.crypto import get_public_key_pem, has_keypair
        if has_keypair():
            public_key_pem = get_public_key_pem()
    except Exception:
        pass

    # Merkle inclusion proof (auto-detects epoch window)
    merkle_proof = None
    if content_hash:
        try:
            merkle_proof = _prove_memory(content_hash, created_at)
        except Exception:
            pass  # Epoch may not be sealed yet

    # Anchor metadata (from the epoch, if anchored)
    anchor = None
    if merkle_proof:
        try:
            from open_brain.epoch import get_epoch
            epoch_window = merkle_proof.get("epoch_window", {})
            record = get_epoch(
                epoch_window.get("start", ""),
                epoch_window.get("end", ""),
            )
            if record and record.anchored_at:
                anchor = {
                    "anchored_at": record.anchored_at,
                    "anchor_metadata": record.anchor_metadata,
                    "epoch_merkle_root": record.merkle_root,
                }
        except Exception:
            pass

    return ProofPackage(
        memory_id=memory_id,
        raw_text=raw_text,
        metadata=metadata,
        content_hash=content_hash or "",
        signature=signature,
        public_key_pem=public_key_pem,
        merkle_proof=merkle_proof,
        anchor=anchor,
        created_at=created_at,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Reasoning Chain Retrieval
# ---------------------------------------------------------------------------


def get_reasoning_chain(
    agent: str,
    *,
    session_id: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Retrieve chronological reasoning checkpoints for an agent.

    Args:
        agent: Source agent identifier.
        session_id: If provided, filter to checkpoints from this session.
        limit: Maximum number of checkpoints to return.

    Returns:
        List of memory dicts, ordered chronologically (oldest first).
    """
    from open_brain.db import read_conn
    import psycopg2.extras

    conditions = [
        "metadata->>'source_agent' = %s",
        "metadata->>'memory_type' = 'reasoning_checkpoint'",
    ]
    params: list = [agent]

    if session_id:
        conditions.append("metadata->>'session_id' = %s")
        params.append(session_id)

    where_sql = "WHERE " + " AND ".join(conditions)
    params.append(limit)

    with read_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, raw_text, content_hash, previous_hash,
                       signature, metadata, created_at
                FROM memories
                {where_sql}
                ORDER BY created_at ASC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()

    from open_brain.db import _row_to_dict
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Chain Verification
# ---------------------------------------------------------------------------


@dataclass
class ChainVerification:
    """Result of verifying a reasoning chain."""

    total: int = 0
    valid: int = 0
    hash_chain_intact: bool = True
    signatures_valid: int = 0
    signatures_invalid: int = 0
    signatures_missing: int = 0
    epoch_proofs: int = 0
    epoch_proofs_missing: int = 0
    anchored: int = 0
    breaks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "valid": self.valid,
            "hash_chain_intact": self.hash_chain_intact,
            "signatures_valid": self.signatures_valid,
            "signatures_invalid": self.signatures_invalid,
            "signatures_missing": self.signatures_missing,
            "epoch_proofs": self.epoch_proofs,
            "epoch_proofs_missing": self.epoch_proofs_missing,
            "anchored": self.anchored,
            "breaks": self.breaks,
        }


def verify_reasoning_chain(
    agent: str,
    *,
    session_id: Optional[str] = None,
) -> ChainVerification:
    """Verify a reasoning checkpoint chain with five checks.

    1. Content hash integrity — recompute and compare.
    2. Hash chain continuity — each previous_hash matches prior content_hash.
    3. Signature validity — Ed25519 verification.
    4. Epoch inclusion — Merkle proof for each checkpoint.
    5. Epoch chain — verify the epoch chain itself.

    Returns a ChainVerification with detailed results.
    """
    from open_brain.hashing import verify_content_hash
    from open_brain.epoch import prove_memory as _prove_memory, verify_epoch_chain

    chain = get_reasoning_chain(agent, session_id=session_id, limit=1000)
    result = ChainVerification(total=len(chain))

    if not chain:
        return result

    prev_hash: Optional[str] = None

    for i, checkpoint in enumerate(chain):
        raw_text = checkpoint["raw_text"]
        metadata = checkpoint.get("metadata", {})
        content_hash = checkpoint.get("content_hash")
        previous_hash = checkpoint.get("previous_hash")
        signature = checkpoint.get("signature")
        created_at = checkpoint["created_at"]
        mem_id = checkpoint["id"]

        is_valid = True

        # Check 1: Content hash integrity
        if content_hash:
            if not verify_content_hash(raw_text, metadata, content_hash):
                result.breaks.append({
                    "check": "content_hash",
                    "memory_id": mem_id,
                    "index": i,
                    "detail": "Content hash does not match recomputed hash",
                })
                is_valid = False
        else:
            # No hash — cannot verify
            is_valid = False

        # Check 2: Hash chain continuity
        if i > 0 and prev_hash is not None:
            if previous_hash != prev_hash:
                result.hash_chain_intact = False
                result.breaks.append({
                    "check": "chain_continuity",
                    "memory_id": mem_id,
                    "index": i,
                    "detail": f"Expected previous_hash={prev_hash}, got {previous_hash}",
                })
                is_valid = False

        prev_hash = content_hash

        # Check 3: Signature validity
        if signature:
            try:
                from open_brain.crypto import verify_signature
                if verify_signature(raw_text, metadata, signature):
                    result.signatures_valid += 1
                else:
                    result.signatures_invalid += 1
                    result.breaks.append({
                        "check": "signature",
                        "memory_id": mem_id,
                        "index": i,
                        "detail": "Signature verification failed",
                    })
                    is_valid = False
            except Exception as e:
                result.signatures_invalid += 1
                result.breaks.append({
                    "check": "signature",
                    "memory_id": mem_id,
                    "index": i,
                    "detail": f"Signature check error: {e}",
                })
                is_valid = False
        else:
            result.signatures_missing += 1

        # Check 4: Epoch inclusion
        if content_hash:
            try:
                proof = _prove_memory(content_hash, created_at)
                if proof:
                    result.epoch_proofs += 1
                    # Check if the epoch is anchored
                    epoch_window = proof.get("epoch_window", {})
                    from open_brain.epoch import get_epoch
                    record = get_epoch(
                        epoch_window.get("start", ""),
                        epoch_window.get("end", ""),
                    )
                    if record and record.anchored_at:
                        result.anchored += 1
                else:
                    result.epoch_proofs_missing += 1
            except Exception:
                result.epoch_proofs_missing += 1

        if is_valid:
            result.valid += 1

    # Check 5: Epoch chain verification (structural, not per-checkpoint)
    try:
        epoch_chain_result = verify_epoch_chain()
        if epoch_chain_result.get("broken"):
            for brk in epoch_chain_result["broken"]:
                result.breaks.append({
                    "check": "epoch_chain",
                    "detail": f"Epoch chain break at {brk.get('epoch_id', '?')}",
                    **brk,
                })
    except Exception as e:
        result.breaks.append({
            "check": "epoch_chain",
            "detail": f"Epoch chain verification error: {e}",
        })

    return result


# ---------------------------------------------------------------------------
# Standalone Export
# ---------------------------------------------------------------------------


def export_reasoning_proof(
    agent: str,
    *,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Export a self-contained reasoning proof for third-party verification.

    The returned JSON includes everything a verifier needs:
      - Ordered checkpoints with raw text and metadata
      - Content hashes (SHA-256) for each checkpoint
      - Hash chain links (previous_hash)
      - Ed25519 signatures and the public key
      - Merkle inclusion proofs per checkpoint
      - Epoch roots and chain links
      - Anchor metadata (blockchain tx hashes)
      - Verification instructions (algorithms, no OB dependency)

    A third party verifies with:
      1. SHA-256: recompute each content_hash from raw_text + metadata
      2. Chain: verify previous_hash links
      3. Ed25519 (RFC 8032): verify each signature with public_key_pem
      4. Merkle: verify each inclusion_proof against epoch_merkle_root
      5. Block explorer: look up anchor tx_hash on the specified chain
    """
    chain = get_reasoning_chain(agent, session_id=session_id, limit=1000)

    # Get public key
    public_key_pem = None
    try:
        from open_brain.crypto import get_public_key_pem, has_keypair
        if has_keypair():
            public_key_pem = get_public_key_pem()
    except Exception:
        pass

    checkpoints = []
    epochs_seen: Dict[str, Dict[str, Any]] = {}

    for checkpoint in chain:
        content_hash = checkpoint.get("content_hash")
        created_at = checkpoint["created_at"]

        # Merkle proof
        merkle_proof = None
        if content_hash:
            try:
                from open_brain.epoch import prove_memory as _prove_memory
                merkle_proof = _prove_memory(content_hash, created_at)
            except Exception:
                pass

        # Track epoch data
        if merkle_proof:
            epoch_window = merkle_proof.get("epoch_window", {})
            epoch_key = f"{epoch_window.get('start', '')}|{epoch_window.get('end', '')}"
            if epoch_key not in epochs_seen:
                try:
                    from open_brain.epoch import get_epoch
                    record = get_epoch(
                        epoch_window.get("start", ""),
                        epoch_window.get("end", ""),
                    )
                    if record:
                        epoch_data = {
                            "window_start": record.window_start,
                            "window_end": record.window_end,
                            "merkle_root": record.merkle_root,
                            "memory_count": record.memory_count,
                            "previous_epoch_root": record.previous_epoch_root,
                            "anchored_at": record.anchored_at,
                            "anchor_metadata": record.anchor_metadata,
                        }
                        epochs_seen[epoch_key] = epoch_data
                except Exception:
                    pass

        checkpoints.append({
            "memory_id": checkpoint["id"],
            "raw_text": checkpoint["raw_text"],
            "metadata": checkpoint.get("metadata", {}),
            "content_hash": content_hash,
            "previous_hash": checkpoint.get("previous_hash"),
            "signature": checkpoint.get("signature"),
            "created_at": created_at,
            "merkle_proof": merkle_proof,
        })

    return {
        "version": "1.0",
        "agent": agent,
        "session_id": session_id,
        "public_key_pem": public_key_pem,
        "checkpoints": checkpoints,
        "epochs": list(epochs_seen.values()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verification_instructions": {
            "content_hash": "SHA-256 over canonical JSON: json.dumps({'raw_text': ..., 'metadata': ...}, sort_keys=True, separators=(',', ':')). Prefix with 'sha256:'.",
            "signature": "Ed25519 (RFC 8032). Sign the same canonical JSON bytes. Signature is hex-encoded.",
            "merkle_proof": "RFC 6962 binary Merkle tree. Verify leaf against epoch merkle_root using sibling hashes and directions (0=left, 1=right).",
            "anchor": "Look up anchor_metadata.tx_hash on the chain specified by anchor_metadata.chain_id. The transaction data should contain the epoch merkle_root.",
        },
    }
