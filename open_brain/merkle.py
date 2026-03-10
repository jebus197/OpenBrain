"""Merkle tree for batch verification of memory integrity.

Binary hash tree over content hashes. Enables:
  - O(log N) inclusion proofs (prove a memory belongs to an epoch)
  - Single root hash per epoch (one blockchain anchor for many memories)
  - Scale 2+ verification without downloading the entire chain

Hash function: SHA-256 (same as content hashing in hashing.py).
Leaf nodes: content_hash values from memories.
Internal nodes: SHA-256(left_child_bytes || right_child_bytes).
Odd leaf count: last leaf promoted (not duplicated — avoids
the second-preimage vulnerability present in Bitcoin's approach).

Same construction as Certificate Transparency (RFC 6962).
Mathematically proven, widely audited.
"""

import hashlib
from typing import List, Optional, Tuple

# Direction constants for proof steps.
# LEFT: sibling is to the left of the target node.
# RIGHT: sibling is to the right of the target node.
LEFT = 0
RIGHT = 1


def _parse_hash(h: str) -> bytes:
    """Extract raw bytes from a prefixed hash string.

    Accepts 'sha256:<hex>' (OB canonical format) or bare hex.
    """
    if ":" in h:
        hex_part = h.split(":", 1)[1]
    else:
        hex_part = h
    return bytes.fromhex(hex_part)


def _format_hash(digest_bytes: bytes) -> str:
    """Format raw hash bytes into the OB canonical string."""
    return f"sha256:{digest_bytes.hex()}"


def _hash_pair(left: str, right: str) -> str:
    """Hash two child nodes into a parent.

    Concatenates raw bytes (not hex strings) for efficiency
    and compatibility with standard Merkle tree constructions.
    """
    combined = _parse_hash(left) + _parse_hash(right)
    return _format_hash(hashlib.sha256(combined).digest())


def compute_root(hashes: List[str]) -> Optional[str]:
    """Compute the Merkle root of a list of content hashes.

    Args:
        hashes: List of content hash strings in leaf order.

    Returns:
        The root hash, or None if the list is empty.
        For a single element, returns that element unchanged.
    """
    if not hashes:
        return None
    if len(hashes) == 1:
        return hashes[0]

    level = list(hashes)
    while len(level) > 1:
        next_level: List[str] = []
        i = 0
        while i < len(level):
            if i + 1 < len(level):
                next_level.append(_hash_pair(level[i], level[i + 1]))
                i += 2
            else:
                # Odd element — promote without hashing (RFC 6962 style).
                next_level.append(level[i])
                i += 1
        level = next_level

    return level[0]


def inclusion_proof(hashes: List[str], index: int) -> List[Tuple[str, int]]:
    """Generate a Merkle inclusion proof for the leaf at *index*.

    Returns a list of (sibling_hash, direction) tuples. Direction
    indicates where the sibling sits relative to the proved node:
      LEFT  — sibling is on the left  → hash(sibling || current)
      RIGHT — sibling is on the right → hash(current || sibling)

    Raises:
        ValueError: If index is out of range.
    """
    if not hashes or index < 0 or index >= len(hashes):
        raise ValueError(
            f"Index {index} out of range for {len(hashes)} hashes"
        )

    proof: List[Tuple[str, int]] = []
    level = list(hashes)
    target_idx = index

    while len(level) > 1:
        next_level: List[str] = []
        next_target_idx = target_idx // 2
        i = 0

        while i < len(level):
            if i + 1 < len(level):
                if i == target_idx:
                    proof.append((level[i + 1], RIGHT))
                elif i + 1 == target_idx:
                    proof.append((level[i], LEFT))
                next_level.append(_hash_pair(level[i], level[i + 1]))
                i += 2
            else:
                # Odd element — promoted, no sibling to include.
                next_level.append(level[i])
                i += 1

        level = next_level
        target_idx = next_target_idx

    return proof


def verify_proof(
    leaf_hash: str,
    proof: List[Tuple[str, int]],
    expected_root: str,
) -> bool:
    """Verify a Merkle inclusion proof.

    Walks the proof path from leaf to root, hashing at each step.
    Returns True if the computed root matches *expected_root*.
    """
    current = leaf_hash
    for sibling, direction in proof:
        if direction == LEFT:
            current = _hash_pair(sibling, current)
        else:
            current = _hash_pair(current, sibling)
    return current == expected_root
