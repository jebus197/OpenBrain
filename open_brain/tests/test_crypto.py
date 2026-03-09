"""Unit tests for open_brain.crypto — Ed25519 signing and AES-256-GCM encryption.

These tests use temporary directories for key storage so they never
touch the real ~/.openbrain/keys/ directory.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from open_brain import crypto


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_keys_dir(tmp_path):
    """Redirect KEYS_DIR to a temporary directory for test isolation."""
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir()
    with mock.patch.object(crypto, "KEYS_DIR", keys_dir):
        yield keys_dir


@pytest.fixture
def keypair(temp_keys_dir):
    """Generate a fresh keypair in the temp directory."""
    crypto.generate_keypair()
    return temp_keys_dir


# ---------------------------------------------------------------------------
# Ed25519 key management
# ---------------------------------------------------------------------------


class TestKeyManagement:

    def test_generate_keypair_creates_files(self, temp_keys_dir):
        pub_path = crypto.generate_keypair()
        assert pub_path.exists()
        assert (temp_keys_dir / "_PRIVATE_KEY_FILE").exists() is False  # sanity
        assert (temp_keys_dir / "ed25519_private.pem").exists()
        assert (temp_keys_dir / "ed25519_public.pem").exists()

    def test_generate_keypair_refuses_overwrite(self, keypair):
        with pytest.raises(FileExistsError):
            crypto.generate_keypair()

    def test_generate_keypair_force_overwrites(self, keypair):
        old_pub = (keypair / "ed25519_public.pem").read_bytes()
        crypto.generate_keypair(force=True)
        new_pub = (keypair / "ed25519_public.pem").read_bytes()
        # New keypair should be different (probabilistically certain)
        assert old_pub != new_pub

    def test_has_keypair_false_when_empty(self, temp_keys_dir):
        assert crypto.has_keypair() is False

    def test_has_keypair_true_after_generation(self, keypair):
        assert crypto.has_keypair() is True

    def test_load_private_key(self, keypair):
        key = crypto.load_private_key()
        # Should be an Ed25519PrivateKey instance
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        assert isinstance(key, Ed25519PrivateKey)

    def test_load_private_key_missing_raises(self, temp_keys_dir):
        with pytest.raises(FileNotFoundError):
            crypto.load_private_key()

    def test_load_public_key(self, keypair):
        key = crypto.load_public_key()
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        assert isinstance(key, Ed25519PublicKey)

    def test_get_public_key_pem(self, keypair):
        pem = crypto.get_public_key_pem()
        assert pem.startswith(b"-----BEGIN PUBLIC KEY-----")


# ---------------------------------------------------------------------------
# Ed25519 signing
# ---------------------------------------------------------------------------


class TestSigning:

    def test_sign_produces_hex_string(self, keypair):
        sig = crypto.sign_memory("hello", {"agent": "test"})
        # Ed25519 signature is 64 bytes = 128 hex chars
        assert len(sig) == 128
        assert all(c in "0123456789abcdef" for c in sig)

    def test_sign_is_deterministic(self, keypair):
        sig1 = crypto.sign_memory("hello", {"agent": "test"})
        sig2 = crypto.sign_memory("hello", {"agent": "test"})
        # Ed25519 is deterministic (RFC 8032 §5.1.6)
        assert sig1 == sig2

    def test_different_content_different_signature(self, keypair):
        sig1 = crypto.sign_memory("hello", {"agent": "test"})
        sig2 = crypto.sign_memory("world", {"agent": "test"})
        assert sig1 != sig2

    def test_different_metadata_different_signature(self, keypair):
        sig1 = crypto.sign_memory("hello", {"agent": "a"})
        sig2 = crypto.sign_memory("hello", {"agent": "b"})
        assert sig1 != sig2

    def test_verify_valid_signature(self, keypair):
        sig = crypto.sign_memory("hello", {"agent": "test"})
        assert crypto.verify_signature("hello", {"agent": "test"}, sig) is True

    def test_verify_tampered_text(self, keypair):
        sig = crypto.sign_memory("hello", {"agent": "test"})
        assert crypto.verify_signature("TAMPERED", {"agent": "test"}, sig) is False

    def test_verify_tampered_metadata(self, keypair):
        sig = crypto.sign_memory("hello", {"agent": "test"})
        assert crypto.verify_signature("hello", {"agent": "FAKE"}, sig) is False

    def test_verify_wrong_key(self, keypair, tmp_path):
        """Signature from one keypair fails verification against another."""
        sig = crypto.sign_memory("hello", {"agent": "test"})

        # Generate a second keypair in a different directory
        other_dir = tmp_path / "other_keys"
        other_dir.mkdir()
        with mock.patch.object(crypto, "KEYS_DIR", other_dir):
            crypto.generate_keypair()
            other_pub_pem = crypto.get_public_key_pem()

        # Verify against the OTHER key should fail
        assert crypto.verify_signature(
            "hello", {"agent": "test"}, sig, public_key_pem=other_pub_pem
        ) is False

    def test_verify_with_explicit_public_key(self, keypair):
        """Verify using explicit PEM bytes (as would happen on another node)."""
        sig = crypto.sign_memory("hello", {"agent": "test"})
        pub_pem = crypto.get_public_key_pem()
        assert crypto.verify_signature(
            "hello", {"agent": "test"}, sig, public_key_pem=pub_pem
        ) is True

    def test_metadata_key_order_invariance(self, keypair):
        """Signing uses canonical JSON (sorted keys), so key order doesn't matter."""
        sig = crypto.sign_memory("hello", {"b": 2, "a": 1})
        assert crypto.verify_signature("hello", {"a": 1, "b": 2}, sig) is True


# ---------------------------------------------------------------------------
# AES-256-GCM encryption
# ---------------------------------------------------------------------------


class TestEncryption:

    def test_encrypt_decrypt_bytes_roundtrip(self):
        plaintext = b"The quick brown fox jumps over the lazy dog"
        passphrase = "test-passphrase-123"
        encrypted = crypto.encrypt_bytes(plaintext, passphrase)
        decrypted = crypto.decrypt_bytes(encrypted, passphrase)
        assert decrypted == plaintext

    def test_different_passphrase_fails(self):
        plaintext = b"secret data"
        encrypted = crypto.encrypt_bytes(plaintext, "correct-passphrase")
        with pytest.raises(Exception):  # InvalidTag from GCM
            crypto.decrypt_bytes(encrypted, "wrong-passphrase")

    def test_tampered_ciphertext_fails(self):
        plaintext = b"secret data"
        encrypted = crypto.encrypt_bytes(plaintext, "passphrase")
        # Flip a byte in the ciphertext (after salt+nonce header)
        corrupted = bytearray(encrypted)
        corrupted[-10] ^= 0xFF
        with pytest.raises(Exception):  # InvalidTag — GCM detects tampering
            crypto.decrypt_bytes(bytes(corrupted), "passphrase")

    def test_encrypt_produces_different_ciphertext_each_time(self):
        """Random salt + nonce means same plaintext encrypts differently."""
        plaintext = b"identical content"
        enc1 = crypto.encrypt_bytes(plaintext, "pass")
        enc2 = crypto.encrypt_bytes(plaintext, "pass")
        assert enc1 != enc2  # Different salt/nonce each time

    def test_encrypted_output_is_larger(self):
        """Ciphertext includes 32-byte salt + 12-byte nonce + 16-byte GCM tag."""
        plaintext = b"short"
        encrypted = crypto.encrypt_bytes(plaintext, "pass")
        overhead = 32 + 12 + 16  # salt + nonce + tag
        assert len(encrypted) == len(plaintext) + overhead

    def test_data_too_short_raises(self):
        with pytest.raises(ValueError, match="too short"):
            crypto.decrypt_bytes(b"tiny", "pass")

    def test_encrypt_decrypt_file_roundtrip(self, tmp_path):
        plaintext_file = tmp_path / "data.jsonl"
        encrypted_file = tmp_path / "data.jsonl.enc"
        decrypted_file = tmp_path / "data_restored.jsonl"

        content = '{"id":"abc","text":"hello"}\n{"id":"def","text":"world"}\n'
        plaintext_file.write_text(content)

        crypto.encrypt_file(str(plaintext_file), str(encrypted_file), "my-pass")
        assert encrypted_file.exists()

        # Encrypted file should not contain plaintext
        enc_bytes = encrypted_file.read_bytes()
        assert b"hello" not in enc_bytes

        crypto.decrypt_file(str(encrypted_file), str(decrypted_file), "my-pass")
        assert decrypted_file.read_text() == content

    def test_encrypt_file_wrong_passphrase(self, tmp_path):
        plaintext_file = tmp_path / "data.jsonl"
        encrypted_file = tmp_path / "data.jsonl.enc"
        decrypted_file = tmp_path / "data_bad.jsonl"

        plaintext_file.write_text("sensitive data")
        crypto.encrypt_file(str(plaintext_file), str(encrypted_file), "correct")

        with pytest.raises(Exception):
            crypto.decrypt_file(str(encrypted_file), str(decrypted_file), "wrong")

    def test_empty_file_encryption(self, tmp_path):
        """Edge case: encrypting an empty file should work."""
        plaintext_file = tmp_path / "empty.jsonl"
        encrypted_file = tmp_path / "empty.enc"
        decrypted_file = tmp_path / "empty_restored.jsonl"

        plaintext_file.write_text("")
        crypto.encrypt_file(str(plaintext_file), str(encrypted_file), "pass")
        crypto.decrypt_file(str(encrypted_file), str(decrypted_file), "pass")
        assert decrypted_file.read_text() == ""

    def test_large_content_encryption(self, tmp_path):
        """Verify encryption works with larger payloads (~1MB)."""
        plaintext_file = tmp_path / "large.jsonl"
        encrypted_file = tmp_path / "large.enc"
        decrypted_file = tmp_path / "large_restored.jsonl"

        # ~1MB of JSONL
        line = json.dumps({"id": "x", "text": "A" * 1000}) + "\n"
        content = line * 1000
        plaintext_file.write_text(content)

        crypto.encrypt_file(str(plaintext_file), str(encrypted_file), "pass")
        crypto.decrypt_file(str(encrypted_file), str(decrypted_file), "pass")
        assert decrypted_file.read_text() == content
