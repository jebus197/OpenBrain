"""Tests for Merkle tree implementation."""

from open_brain.merkle import (
    LEFT,
    RIGHT,
    compute_root,
    inclusion_proof,
    verify_proof,
    _hash_pair,
    _parse_hash,
    _format_hash,
)
from open_brain.hashing import compute_content_hash


# ---------------------------------------------------------------------------
# Helper: generate realistic content hashes
# ---------------------------------------------------------------------------

def _make_hashes(n):
    """Generate n distinct content hashes."""
    return [
        compute_content_hash(f"memory-{i}", {"index": i})
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# compute_root
# ---------------------------------------------------------------------------

def test_root_empty():
    assert compute_root([]) is None


def test_root_single():
    h = _make_hashes(1)
    assert compute_root(h) == h[0]


def test_root_two():
    h = _make_hashes(2)
    root = compute_root(h)
    assert root is not None
    assert root.startswith("sha256:")
    assert root == _hash_pair(h[0], h[1])


def test_root_three_odd_promotion():
    """Odd count: last element promoted, not duplicated."""
    h = _make_hashes(3)
    root = compute_root(h)
    assert root is not None
    # Level 1: [hash(h0,h1), h2]  (h2 promoted)
    # Level 2: hash(hash(h0,h1), h2)
    expected = _hash_pair(_hash_pair(h[0], h[1]), h[2])
    assert root == expected


def test_root_four():
    h = _make_hashes(4)
    root = compute_root(h)
    expected = _hash_pair(
        _hash_pair(h[0], h[1]),
        _hash_pair(h[2], h[3]),
    )
    assert root == expected


def test_root_deterministic():
    """Same input always produces same root."""
    h = _make_hashes(10)
    r1 = compute_root(h)
    r2 = compute_root(h)
    assert r1 == r2


def test_root_order_matters():
    """Different leaf order produces different root."""
    h = _make_hashes(4)
    r1 = compute_root(h)
    r2 = compute_root(list(reversed(h)))
    assert r1 != r2


# ---------------------------------------------------------------------------
# inclusion_proof + verify_proof
# ---------------------------------------------------------------------------

def test_proof_single_element():
    h = _make_hashes(1)
    root = compute_root(h)
    proof = inclusion_proof(h, 0)
    assert proof == []
    assert verify_proof(h[0], proof, root)


def test_proof_two_elements():
    h = _make_hashes(2)
    root = compute_root(h)

    # Proof for index 0: sibling is h[1] on the RIGHT
    proof0 = inclusion_proof(h, 0)
    assert len(proof0) == 1
    assert proof0[0] == (h[1], RIGHT)
    assert verify_proof(h[0], proof0, root)

    # Proof for index 1: sibling is h[0] on the LEFT
    proof1 = inclusion_proof(h, 1)
    assert len(proof1) == 1
    assert proof1[0] == (h[0], LEFT)
    assert verify_proof(h[1], proof1, root)


def test_proof_four_elements():
    h = _make_hashes(4)
    root = compute_root(h)

    for i in range(4):
        proof = inclusion_proof(h, i)
        assert verify_proof(h[i], proof, root), f"Proof failed for index {i}"


def test_proof_seven_elements():
    """Odd count with multi-level promotion."""
    h = _make_hashes(7)
    root = compute_root(h)

    for i in range(7):
        proof = inclusion_proof(h, i)
        assert verify_proof(h[i], proof, root), f"Proof failed for index {i}"


def test_proof_large_tree():
    """100-element tree — every leaf verifiable."""
    h = _make_hashes(100)
    root = compute_root(h)

    for i in range(100):
        proof = inclusion_proof(h, i)
        assert verify_proof(h[i], proof, root), f"Proof failed for index {i}"


def test_proof_wrong_root_fails():
    h = _make_hashes(4)
    root = compute_root(h)
    proof = inclusion_proof(h, 0)
    fake_root = compute_content_hash("fake", {})
    assert not verify_proof(h[0], proof, fake_root)


def test_proof_wrong_leaf_fails():
    h = _make_hashes(4)
    root = compute_root(h)
    proof = inclusion_proof(h, 0)
    fake_leaf = compute_content_hash("tampered", {})
    assert not verify_proof(fake_leaf, proof, root)


def test_proof_index_out_of_range():
    h = _make_hashes(3)
    try:
        inclusion_proof(h, 5)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_proof_negative_index():
    h = _make_hashes(3)
    try:
        inclusion_proof(h, -1)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_proof_empty_list():
    try:
        inclusion_proof([], 0)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# _parse_hash / _format_hash
# ---------------------------------------------------------------------------

def test_parse_hash_with_prefix():
    h = "sha256:abcd1234"
    raw = _parse_hash(h)
    assert raw == bytes.fromhex("abcd1234")


def test_parse_hash_bare_hex():
    raw = _parse_hash("abcd1234")
    assert raw == bytes.fromhex("abcd1234")


def test_format_hash():
    raw = bytes.fromhex("abcd1234")
    assert _format_hash(raw) == "sha256:abcd1234"
