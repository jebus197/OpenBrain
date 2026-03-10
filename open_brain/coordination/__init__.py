"""High-performance coordination layer for distributed AI agents.

Modelled on financial market infrastructure: deterministic sequencing,
sub-millisecond in-process dispatch, trust-gated channels, circuit
breakers, and auditable message trails. Every message is content-hashed
and (optionally) signed — the same integrity model as memories.

Architecture
------------
At Scale 0-1 (single machine), the bus routes messages in-process via
asyncio queues — zero network overhead, sub-millisecond dispatch.
At Scale 2+, a network transport layer plugs in beneath the same API.
The coordination protocol is scale-invariant: same message format, same
sequencing guarantees, same trust gates, regardless of topology.

Components
----------
protocol    Envelope format, message types, serialisation.
sequencer   Monotonic ordering, gap detection, replay support.
channel     Trust-gated pub/sub (broadcast, queue, direct).
circuit_breaker  Rate limiting, anomaly detection, graduated response.
presence    Node heartbeat, capability advertisement, discovery.
bus         Top-level API tying all components together.
"""

from open_brain.coordination.protocol import (
    Envelope,
    MessageType,
    make_envelope,
)
from open_brain.coordination.bus import CoordinationBus

__all__ = [
    "CoordinationBus",
    "Envelope",
    "MessageType",
    "make_envelope",
]
