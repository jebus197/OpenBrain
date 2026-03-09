"""Integration tests for Ed25519 signing through the full pipeline.

Tests that signing works end-to-end: capture → store → export → verify.
Uses real database (open_brain_test) and temporary keypairs.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from open_brain import crypto, db, config
from open_brain.capture import capture_memory
from open_brain.hashing import compute_content_hash


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def use_test_db():
    """Point all DB operations at the test database."""
    with mock.patch.object(config, "DB_NAME", "open_brain_test"):
        yield


@pytest.fixture
def temp_keypair(tmp_path):
    """Generate a temporary keypair for testing."""
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir()
    with mock.patch.object(crypto, "KEYS_DIR", keys_dir):
        crypto.generate_keypair()
        yield keys_dir


@pytest.fixture
def clean_test_memories():
    """Delete test memories after each test."""
    created_ids = []
    yield created_ids
    # Cleanup
    import psycopg2
    conn = psycopg2.connect(config.dsn("admin"))
    conn.autocommit = True
    with conn.cursor() as cur:
        for mid in created_ids:
            cur.execute("DELETE FROM memories WHERE id = %s", (mid,))
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSignedCapture:

    def test_memory_is_signed_when_keypair_exists(
        self, temp_keypair, clean_test_memories
    ):
        """When a keypair exists, insert_memory signs automatically."""
        with mock.patch.object(crypto, "KEYS_DIR", temp_keypair):
            import numpy as np
            embedding = [0.1] * 384
            metadata = {"source_agent": "cc", "memory_type": "insight",
                         "area": "testing", "node_id": config.node_id()}
            mem_id = db.insert_memory(
                raw_text="signed test memory",
                embedding=embedding,
                metadata=metadata,
            )
            clean_test_memories.append(mem_id)

            # Fetch and check signature exists
            with db.read_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT signature FROM memories WHERE id = %s",
                        (mem_id,),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    signature = row[0]
                    assert signature is not None
                    assert len(signature) == 128  # 64 bytes hex

            # Verify the signature
            assert crypto.verify_signature(
                "signed test memory", metadata, signature
            ) is True

    def test_memory_unsigned_when_no_keypair(self, clean_test_memories):
        """Without a keypair, memories are stored without signatures."""
        # Use a temp dir with no keys
        empty_keys = Path(tempfile.mkdtemp()) / "empty_keys"
        empty_keys.mkdir()
        with mock.patch.object(crypto, "KEYS_DIR", empty_keys):
            embedding = [0.1] * 384
            metadata = {"source_agent": "cc", "memory_type": "insight",
                         "area": "testing", "node_id": config.node_id()}
            mem_id = db.insert_memory(
                raw_text="unsigned test memory",
                embedding=embedding,
                metadata=metadata,
            )
            clean_test_memories.append(mem_id)

            with db.read_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT signature FROM memories WHERE id = %s",
                        (mem_id,),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    assert row[0] is None  # No signature

    def test_signature_in_export(self, temp_keypair, clean_test_memories):
        """Exported memories include the signature field."""
        with mock.patch.object(crypto, "KEYS_DIR", temp_keypair):
            embedding = [0.1] * 384
            metadata = {"source_agent": "cc", "memory_type": "insight",
                         "area": "testing", "node_id": config.node_id()}
            mem_id = db.insert_memory(
                raw_text="export signature test",
                embedding=embedding,
                metadata=metadata,
            )
            clean_test_memories.append(mem_id)

            memories = db.export_memories()
            # Find our memory in the export
            our_mem = next(
                (m for m in memories if m["id"] == mem_id), None
            )
            assert our_mem is not None
            assert "signature" in our_mem
            assert our_mem["signature"] is not None

    def test_signed_export_import_roundtrip(
        self, temp_keypair, clean_test_memories, tmp_path
    ):
        """Signatures survive export → import roundtrip."""
        with mock.patch.object(crypto, "KEYS_DIR", temp_keypair):
            embedding = [0.1] * 384
            metadata = {"source_agent": "cc", "memory_type": "insight",
                         "area": "testing", "node_id": config.node_id()}
            mem_id = db.insert_memory(
                raw_text="roundtrip signature test",
                embedding=embedding,
                metadata=metadata,
            )
            clean_test_memories.append(mem_id)

            # Export
            memories = db.export_memories()
            our_mem = next(m for m in memories if m["id"] == mem_id)
            original_sig = our_mem["signature"]

            # Delete from DB
            import psycopg2
            conn = psycopg2.connect(config.dsn("admin"))
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("DELETE FROM memories WHERE id = %s", (mem_id,))
            conn.close()

            # Import back
            result = db.import_memory(our_mem)
            assert result == "inserted"

            # Verify signature survived
            with db.read_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT signature FROM memories WHERE id = %s",
                        (mem_id,),
                    )
                    row = cur.fetchone()
                    assert row[0] == original_sig

            # Verify signature is still valid
            assert crypto.verify_signature(
                "roundtrip signature test", metadata, original_sig
            ) is True

    def test_encrypted_export_import_roundtrip(
        self, temp_keypair, clean_test_memories, tmp_path
    ):
        """Full pipeline: capture → signed → export encrypted → decrypt → import."""
        with mock.patch.object(crypto, "KEYS_DIR", temp_keypair):
            embedding = [0.1] * 384
            metadata = {"source_agent": "cc", "memory_type": "insight",
                         "area": "testing", "node_id": config.node_id()}
            mem_id = db.insert_memory(
                raw_text="encrypted roundtrip test",
                embedding=embedding,
                metadata=metadata,
            )
            clean_test_memories.append(mem_id)

            # Export to JSONL
            memories = db.export_memories()
            jsonl = ""
            for m in memories:
                jsonl += json.dumps(m, separators=(",", ":")) + "\n"

            # Encrypt
            passphrase = "test-passphrase-for-ci"
            encrypted = crypto.encrypt_bytes(jsonl.encode("utf-8"), passphrase)

            # Verify ciphertext doesn't contain plaintext
            assert b"encrypted roundtrip test" not in encrypted

            # Decrypt
            decrypted = crypto.decrypt_bytes(encrypted, passphrase)
            assert decrypted == jsonl.encode("utf-8")

            # Parse and verify signatures survive
            lines = decrypted.decode("utf-8").strip().split("\n")
            our_line = next(
                l for l in lines
                if json.loads(l)["id"] == mem_id
            )
            restored = json.loads(our_line)
            assert restored["signature"] is not None
            assert crypto.verify_signature(
                restored["raw_text"],
                restored["metadata"],
                restored["signature"],
            ) is True

    def test_verification_includes_signatures(
        self, temp_keypair, clean_test_memories
    ):
        """get_all_for_verification returns signature field."""
        with mock.patch.object(crypto, "KEYS_DIR", temp_keypair):
            embedding = [0.1] * 384
            metadata = {"source_agent": "cc", "memory_type": "insight",
                         "area": "testing", "node_id": config.node_id()}
            mem_id = db.insert_memory(
                raw_text="verify sig field test",
                embedding=embedding,
                metadata=metadata,
            )
            clean_test_memories.append(mem_id)

            memories = db.get_all_for_verification()
            our_mem = next(
                (m for m in memories if m["id"] == mem_id), None
            )
            assert our_mem is not None
            assert "signature" in our_mem
            assert our_mem["signature"] is not None
