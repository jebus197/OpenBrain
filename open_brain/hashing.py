"""Content hashing and hash chain verification for Open Brain.

Implements the foundational axiom: all truth should be anchored and
independently verifiable. Content hashes anchor each memory; the hash
chain makes deletion and insertion detectable.

Hash computation:
    content_hash = SHA-256 of canonical JSON {raw_text, metadata}
    Canonical JSON: sorted keys, no whitespace separators.
    Embedding is excluded (derived data, not content).
    created_at is excluded (temporal metadata, not content).
    id is excluded (address, not content).

    The hash chain (previous_hash) provides ordering integrity.
    Content hash provides content integrity. Together they give
    tamper evidence at Scales 0-3 without any blockchain dependency.
"""

import hashlib
import json
from typing import Any, Dict, List, Optional

GENESIS_HASH = "sha256:genesis"


def compute_content_hash(raw_text: str, metadata: Dict[str, Any]) -> str:
    """Compute SHA-256 content hash of a memory.

    Canonical form: JSON with sorted keys, compact separators.
    Fields hashed: raw_text, metadata.
    """
    canonical = json.dumps(
        {"raw_text": raw_text, "metadata": metadata},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def verify_content_hash(
    raw_text: str,
    metadata: Dict[str, Any],
    expected_hash: str,
) -> bool:
    """Verify that a content hash matches the given content."""
    computed = compute_content_hash(raw_text, metadata)
    return computed == expected_hash


def verify_chain(
    memories: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Walk a list of memories (ordered by created_at ASC) and verify integrity.

    Returns:
        {
            "total": int,
            "valid": int,
            "broken_content": [{"id": str, "expected": str, "actual": str}],
            "broken_chain": [{"id": str, "expected_prev": str, "actual_prev": str}],
            "unhashed": int,  # memories without content_hash (pre-migration)
        }
    """
    result: Dict[str, Any] = {
        "total": len(memories),
        "valid": 0,
        "broken_content": [],
        "broken_chain": [],
        "unhashed": 0,
    }

    expected_prev: Optional[str] = None

    for mem in memories:
        content_hash = mem.get("content_hash")

        # Skip unhashed memories (pre-migration)
        if not content_hash:
            result["unhashed"] += 1
            continue

        # Verify content hash
        computed = compute_content_hash(mem["raw_text"], mem["metadata"])
        if computed != content_hash:
            result["broken_content"].append({
                "id": str(mem["id"]),
                "expected": computed,
                "actual": content_hash,
            })
        else:
            result["valid"] += 1

        # Verify chain link
        actual_prev = mem.get("previous_hash")
        if expected_prev is not None and actual_prev != expected_prev:
            result["broken_chain"].append({
                "id": str(mem["id"]),
                "expected_prev": expected_prev,
                "actual_prev": actual_prev,
            })

        # Advance chain — next memory should link to this one
        expected_prev = content_hash

    return result
