"""Coordination protocol — message envelope and type definitions.

Design principles (financial market infrastructure parallel):
  FIX protocol     → Typed envelope with mandatory header fields
  Session-level ID → Monotonic sequence per (sender, channel)
  Body checksum    → SHA-256 content hash (same scheme as memories)
  Tag-value pairs  → Typed payload dict with per-type schemas

Every message on the bus uses the same Envelope structure. The bus
routes on (channel, msg_type) — it never inspects the payload. This
makes the protocol extensible: new message types can be added without
modifying the bus, sequencer, or channel logic.

Wire format:
  Scale 0-1 (in-process): Python dataclass instances, zero serialisation.
  Scale 2+  (network):    msgpack encoding of the envelope dict.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class MessageType(str, Enum):
    """Well-known message types routed by the coordination bus.

    Dot-separated namespace: category.action.
    System types are handled by the bus itself.
    Application types are routed to channel subscribers.
    """

    # --- System messages (bus-internal) ---
    HEARTBEAT = "system.heartbeat"
    HEARTBEAT_ACK = "system.heartbeat_ack"
    NODE_ANNOUNCE = "system.node_announce"
    NODE_DEPART = "system.node_depart"
    SYNC_REQUEST = "system.sync_request"
    SYNC_RESPONSE = "system.sync_response"

    # --- Memory lifecycle ---
    MEMORY_CREATED = "memory.created"
    MEMORY_UPDATED = "memory.updated"

    # --- Intelligence signals (Genesis InsightSignal carriers) ---
    INSIGHT_SIGNAL = "insight.signal"

    # --- Auto-immune signals (Genesis ThreatSignal carriers) ---
    THREAT_SIGNAL = "threat.signal"

    # --- Task coordination ---
    TASK_ASSIGNED = "task.assigned"
    TASK_STATUS = "task.status"
    TASK_COMPLETED = "task.completed"

    # --- Epoch / verification ---
    EPOCH_SEALED = "epoch.sealed"

    # --- Distributed query ---
    QUERY_REQUEST = "query.request"
    QUERY_RESPONSE = "query.response"

    # --- Governance (project-specific ballot/amendment carriers) ---
    GOVERNANCE_BALLOT = "governance.ballot"
    REVIEW_DECISION = "review.decision"
    TRUST_DELTA = "trust.delta"

    # --- Coordination primitives ---
    CAPABILITY_ANNOUNCE = "coord.capability"
    WORK_OFFER = "coord.work_offer"
    WORK_ACCEPT = "coord.work_accept"
    WORK_REJECT = "coord.work_reject"


# Types that the bus handles internally (not forwarded to subscribers).
SYSTEM_TYPES = frozenset({
    MessageType.HEARTBEAT,
    MessageType.HEARTBEAT_ACK,
    MessageType.NODE_ANNOUNCE,
    MessageType.NODE_DEPART,
    MessageType.SYNC_REQUEST,
    MessageType.SYNC_RESPONSE,
})


@dataclass(frozen=True, slots=True)
class Envelope:
    """Immutable message envelope — the unit of coordination.

    Frozen for hashability and thread safety. Slots for memory
    efficiency under high message rates.

    Fields mirror financial protocol headers:
      msg_id       ↔ FIX ClOrdID      (unique per message)
      msg_type     ↔ FIX MsgType(35)  (type discriminator)
      sender       ↔ FIX SenderCompID (originating node)
      channel      ↔ routing key      (topic / queue name)
      sequence     ↔ FIX MsgSeqNum    (monotonic per sender+channel)
      timestamp_ns ↔ FIX SendingTime  (nanosecond precision)
      content_hash ↔ FIX CheckSum     (SHA-256 of canonical payload)
      signature    ↔ digital sig      (Ed25519 if keypair available)
      ttl_ms       ↔ TimeInForce      (0 = GTC / no expiry)
      payload      ↔ message body     (type-specific fields)
    """

    msg_id: str
    msg_type: str
    sender: str
    channel: str
    sequence: int
    timestamp_ns: int
    content_hash: str
    payload: Dict[str, Any]
    signature: str = ""
    ttl_ms: int = 0
    correlation_id: str = ""  # Links request/response pairs.
    priority: int = 0         # Higher = more urgent. 0 = normal.

    def is_expired(self) -> bool:
        """Check whether this message has exceeded its TTL."""
        if self.ttl_ms <= 0:
            return False
        age_ms = (time.time_ns() - self.timestamp_ns) / 1_000_000
        return age_ms > self.ttl_ms

    def is_system(self) -> bool:
        """Check whether this is a bus-internal system message."""
        return self.msg_type in {t.value for t in SYSTEM_TYPES}

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict (for msgpack / JSON transport)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Envelope:
        """Deserialise from a plain dict."""
        return cls(**d)


def _canonical_payload(payload: Dict[str, Any]) -> str:
    """Produce a deterministic JSON string for hashing.

    Same approach as hashing.py — sorted keys, compact separators.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_message_hash(payload: Dict[str, Any]) -> str:
    """SHA-256 content hash of a message payload.

    Returns the OB canonical format: 'sha256:<hex>'.
    """
    canonical = _canonical_payload(payload)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def make_envelope(
    msg_type: MessageType | str,
    sender: str,
    channel: str,
    payload: Dict[str, Any],
    *,
    sequence: int = 0,
    ttl_ms: int = 0,
    correlation_id: str = "",
    priority: int = 0,
    signature: str = "",
) -> Envelope:
    """Construct an Envelope with auto-generated ID, timestamp, and hash.

    The sequence number defaults to 0 — the Sequencer assigns the real
    value before dispatch. Callers should not set it manually unless
    replaying historical messages.
    """
    type_str = msg_type.value if isinstance(msg_type, MessageType) else msg_type
    content_hash = compute_message_hash(payload)

    return Envelope(
        msg_id=str(uuid.uuid4()),
        msg_type=type_str,
        sender=sender,
        channel=channel,
        sequence=sequence,
        timestamp_ns=time.time_ns(),
        content_hash=content_hash,
        payload=payload,
        signature=signature,
        ttl_ms=ttl_ms,
        correlation_id=correlation_id,
        priority=priority,
    )


def sign_envelope(envelope: Envelope, private_key_bytes: bytes) -> Envelope:
    """Sign an envelope using Ed25519 (same scheme as crypto.py).

    Returns a new Envelope with the signature field set.
    The signed data is the content_hash — signing the hash
    is equivalent to signing the payload (collision-resistant).
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
        key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        sig_bytes = key.sign(envelope.content_hash.encode("utf-8"))
        sig_hex = sig_bytes.hex()
    except Exception:
        sig_hex = ""

    # Envelope is frozen — construct a new one with the signature.
    d = envelope.to_dict()
    d["signature"] = sig_hex
    return Envelope.from_dict(d)


def verify_envelope_signature(
    envelope: Envelope,
    public_key_bytes: bytes,
) -> bool:
    """Verify an envelope's Ed25519 signature.

    Returns False if the signature is missing, invalid, the payload
    has been tampered with, or the cryptography library is unavailable.
    """
    if not envelope.signature:
        return False
    # Re-derive content hash from payload — reject if it doesn't match.
    expected_hash = compute_message_hash(envelope.payload)
    if expected_hash != envelope.content_hash:
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
        key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        sig_bytes = bytes.fromhex(envelope.signature)
        key.verify(sig_bytes, envelope.content_hash.encode("utf-8"))
        return True
    except Exception:
        return False
