"""Open Brain IM — SQLite WAL-mode inter-agent messaging.

Channel-based messaging with Ed25519 signing, FTS5 search,
delivery receipts, and retention policies. Signal-modelled
foundations (mandatory attribution, content hashing, signatures)
without sealed sender — Genesis requires provenance.
"""

from open_brain.im.store import IMMessage, IMStore

__all__ = ["IMMessage", "IMStore"]
