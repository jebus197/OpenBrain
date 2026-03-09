"""Cryptographic signing and encryption for Open Brain.

Ed25519 signing: each node has a keypair. Every memory gets a signature
over its canonical JSON (the same form used for content hashing). This
provides cryptographic proof of origin — not just a claimed node_id
string, but a verifiable assertion that this specific key produced
this specific content.

AES-256-GCM encryption: JSONL export files can be encrypted before
transport between machines. The encryption key is derived from a
human-chosen passphrase via Scrypt (RFC 7914), which is deliberately
slow to resist brute-force guessing.

Standards used:
    Ed25519  — RFC 8032 (same as SSH, Signal, WireGuard)
    AES-256-GCM — NIST SP 800-38D (authenticated encryption)
    Scrypt   — RFC 7914 (memory-hard key derivation)

All primitives come from Python's `cryptography` library, which wraps
OpenSSL. No hand-rolled crypto. Platform-agnostic (macOS, Linux, Windows).
"""

import json
import os
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.exceptions import InvalidSignature

from open_brain import config

# ---------------------------------------------------------------------------
# Key storage paths
# ---------------------------------------------------------------------------

KEYS_DIR = config.CONFIG_DIR / "keys"

# Ed25519 key filenames — one keypair per node
_PRIVATE_KEY_FILE = "ed25519_private.pem"
_PUBLIC_KEY_FILE = "ed25519_public.pem"


def _keys_path() -> Path:
    """Return the keys directory, creating it with restricted permissions."""
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    # Best-effort permission restriction — works on POSIX (macOS, Linux).
    # On Windows, NTFS ACLs are the equivalent; the directory is still
    # created, just without POSIX permission enforcement.
    try:
        KEYS_DIR.chmod(0o700)
    except OSError:
        pass  # Windows or restricted filesystem — acceptable at Scale 1
    return KEYS_DIR


# ---------------------------------------------------------------------------
# Ed25519 signing — key management
# ---------------------------------------------------------------------------


def generate_keypair(*, force: bool = False) -> Path:
    """Generate an Ed25519 keypair and save to ~/.openbrain/keys/.

    Returns the path to the public key file.

    If keys already exist and force is False, raises FileExistsError.
    This prevents accidental key rotation (which would invalidate all
    existing signatures from this node).
    """
    kdir = _keys_path()
    priv_path = kdir / _PRIVATE_KEY_FILE
    pub_path = kdir / _PUBLIC_KEY_FILE

    if priv_path.exists() and not force:
        raise FileExistsError(
            f"Keypair already exists at {kdir}. "
            "Use force=True to regenerate (this invalidates existing signatures)."
        )

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Private key — PEM format, no encryption (protected by filesystem
    # permissions + FileVault / OS-level disk encryption)
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    priv_path.write_bytes(priv_pem)
    try:
        priv_path.chmod(0o600)  # Owner read/write only
    except OSError:
        pass

    # Public key — PEM format, shareable
    pub_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_path.write_bytes(pub_pem)

    return pub_path


def has_keypair() -> bool:
    """Check whether a keypair exists for this node."""
    kdir = _keys_path()
    return (kdir / _PRIVATE_KEY_FILE).exists()


def load_private_key() -> Ed25519PrivateKey:
    """Load the node's Ed25519 private key from disk."""
    priv_path = _keys_path() / _PRIVATE_KEY_FILE
    if not priv_path.exists():
        raise FileNotFoundError(
            f"No private key at {priv_path}. "
            "Run `python3 -m open_brain.cli generate-keys` first."
        )
    priv_pem = priv_path.read_bytes()
    key = serialization.load_pem_private_key(priv_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError(f"Expected Ed25519 private key, got {type(key).__name__}")
    return key


def load_public_key(pem_bytes: Optional[bytes] = None) -> Ed25519PublicKey:
    """Load an Ed25519 public key.

    If pem_bytes is None, loads this node's own public key from disk.
    Otherwise, loads from the provided PEM bytes (for verifying
    memories from other nodes).
    """
    if pem_bytes is None:
        pub_path = _keys_path() / _PUBLIC_KEY_FILE
        if not pub_path.exists():
            raise FileNotFoundError(f"No public key at {pub_path}")
        pem_bytes = pub_path.read_bytes()

    key = serialization.load_pem_public_key(pem_bytes)
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError(f"Expected Ed25519 public key, got {type(key).__name__}")
    return key


def get_public_key_pem() -> bytes:
    """Return this node's public key as PEM bytes (for embedding in exports)."""
    pub_path = _keys_path() / _PUBLIC_KEY_FILE
    if not pub_path.exists():
        raise FileNotFoundError(f"No public key at {pub_path}")
    return pub_path.read_bytes()


# ---------------------------------------------------------------------------
# Ed25519 signing — sign and verify
# ---------------------------------------------------------------------------


def sign_memory(raw_text: str, metadata: dict) -> str:
    """Sign a memory's canonical content and return the hex signature.

    Signs the same canonical JSON used for content hashing — sorted keys,
    compact separators, UTF-8 encoded. This means the signature covers
    exactly what the content_hash covers.

    Returns: hex-encoded Ed25519 signature (128 hex chars = 64 bytes).
    """
    private_key = load_private_key()
    canonical = json.dumps(
        {"raw_text": raw_text, "metadata": metadata},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    sig = private_key.sign(canonical)
    return sig.hex()


def verify_signature(
    raw_text: str,
    metadata: dict,
    signature_hex: str,
    public_key_pem: Optional[bytes] = None,
) -> bool:
    """Verify an Ed25519 signature against memory content.

    Args:
        raw_text: The memory's raw text.
        metadata: The memory's metadata dict.
        signature_hex: The hex-encoded signature to verify.
        public_key_pem: PEM bytes of the signer's public key.
                        If None, uses this node's own public key.

    Returns True if valid, False if signature doesn't match.
    """
    try:
        public_key = load_public_key(public_key_pem)
        canonical = json.dumps(
            {"raw_text": raw_text, "metadata": metadata},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        sig_bytes = bytes.fromhex(signature_hex)
        public_key.verify(sig_bytes, canonical)
        return True
    except (InvalidSignature, ValueError):
        return False


# ---------------------------------------------------------------------------
# AES-256-GCM encryption — for JSONL export files
# ---------------------------------------------------------------------------

# Scrypt parameters (RFC 7914 recommendations for interactive use)
_SCRYPT_N = 2**18  # CPU/memory cost (262144 — ~1s on modern hardware)
_SCRYPT_R = 8      # Block size
_SCRYPT_P = 1      # Parallelism
_SALT_BYTES = 32   # 256-bit salt
_NONCE_BYTES = 12  # 96-bit nonce (standard for AES-GCM)
_KEY_BYTES = 32    # 256-bit key


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 256-bit encryption key from a passphrase using Scrypt.

    Scrypt is memory-hard: an attacker trying billions of passphrases
    needs not just CPU time but large amounts of RAM for each attempt,
    making brute-force economically prohibitive.
    """
    kdf = Scrypt(
        salt=salt,
        length=_KEY_BYTES,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_file(plaintext_path: str, output_path: str, passphrase: str) -> None:
    """Encrypt a file (typically JSONL export) with AES-256-GCM.

    File format:
        [32 bytes salt] [12 bytes nonce] [ciphertext + 16 bytes GCM tag]

    The salt and nonce are randomly generated per encryption.
    The passphrase is never stored — only used to derive the key.
    """
    salt = os.urandom(_SALT_BYTES)
    nonce = os.urandom(_NONCE_BYTES)
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)

    plaintext = Path(plaintext_path).read_bytes()
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    with open(output_path, "wb") as f:
        f.write(salt)
        f.write(nonce)
        f.write(ciphertext)


def decrypt_file(encrypted_path: str, output_path: str, passphrase: str) -> None:
    """Decrypt an AES-256-GCM encrypted file.

    Reads the salt and nonce from the file header, derives the key from
    the passphrase, and decrypts. Raises cryptography.exceptions.InvalidTag
    if the passphrase is wrong or the file has been tampered with — GCM's
    authentication tag catches both.
    """
    data = Path(encrypted_path).read_bytes()

    if len(data) < _SALT_BYTES + _NONCE_BYTES + 16:
        raise ValueError(
            "File too small to be a valid encrypted export "
            f"(need at least {_SALT_BYTES + _NONCE_BYTES + 16} bytes, "
            f"got {len(data)})"
        )

    salt = data[:_SALT_BYTES]
    nonce = data[_SALT_BYTES : _SALT_BYTES + _NONCE_BYTES]
    ciphertext = data[_SALT_BYTES + _NONCE_BYTES :]

    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)

    Path(output_path).write_bytes(plaintext)


def encrypt_bytes(plaintext: bytes, passphrase: str) -> bytes:
    """Encrypt bytes in memory. Returns salt + nonce + ciphertext."""
    salt = os.urandom(_SALT_BYTES)
    nonce = os.urandom(_NONCE_BYTES)
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return salt + nonce + ciphertext


def decrypt_bytes(data: bytes, passphrase: str) -> bytes:
    """Decrypt bytes in memory. Input is salt + nonce + ciphertext."""
    min_len = _SALT_BYTES + _NONCE_BYTES + 16
    if len(data) < min_len:
        raise ValueError(f"Data too short ({len(data)} < {min_len})")
    salt = data[:_SALT_BYTES]
    nonce = data[_SALT_BYTES : _SALT_BYTES + _NONCE_BYTES]
    ciphertext = data[_SALT_BYTES + _NONCE_BYTES :]
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)
