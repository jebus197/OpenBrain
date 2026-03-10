"""Crypto facade — key management and signing operations.

Wraps :mod:`open_brain.crypto` with a consistent object-oriented API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class CryptoFacade:
    """Ed25519 key management and signing."""

    def has_keypair(self) -> bool:
        """Check whether a node keypair exists on disk."""
        from open_brain import crypto

        return crypto.has_keypair()

    def generate_keypair(self, *, force: bool = False) -> Path:
        """Generate an Ed25519 keypair.  Returns path to public key file.

        Raises :class:`FileExistsError` if keys already exist and
        *force* is ``False``.
        """
        from open_brain import crypto

        return crypto.generate_keypair(force=force)

    def sign(self, data: bytes) -> str:
        """Sign *data* with the node's private key.

        Returns the hex-encoded signature.
        Raises :class:`FileNotFoundError` if no keypair exists.
        """
        from open_brain import crypto

        private_key = crypto.load_private_key()
        sig_bytes = private_key.sign(data)
        return sig_bytes.hex()

    def verify(self, data: bytes, signature_hex: str) -> bool:
        """Verify a signature against the node's public key.

        Returns ``True`` if valid, ``False`` otherwise.
        """
        from open_brain import crypto

        try:
            public_key = crypto.load_public_key()
            public_key.verify(bytes.fromhex(signature_hex), data)
            return True
        except Exception:
            return False

    def public_key_pem(self) -> Optional[str]:
        """Return the PEM-encoded public key, or ``None`` if absent."""
        from open_brain import crypto

        if not crypto.has_keypair():
            return None
        return crypto.get_public_key_pem().decode()

    def private_key_bytes(self) -> Optional[bytes]:
        """Return raw private key bytes for bus signing, or ``None``."""
        from open_brain import crypto

        if not crypto.has_keypair():
            return None
        pk = crypto.load_private_key()
        return pk.private_bytes(
            encoding=crypto.serialization.Encoding.Raw,
            format=crypto.serialization.PrivateFormat.Raw,
            encryption_algorithm=crypto.serialization.NoEncryption(),
        )
