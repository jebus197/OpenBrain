"""Coordination bus — the top-level API for machine-to-machine coordination.

This is the central nervous system. Everything flows through the bus:
memories, insights, threats, tasks, queries, heartbeats. The bus ties
together channels, sequencing, circuit breaking, and presence into a
single coherent API.

Financial market parallel: the exchange matching engine + market data
distribution + session management, unified behind one gateway.

Performance targets (Scale 0-1, in-process):
  Message dispatch:  < 100 microseconds (async, zero-copy, no DB on hot path)
  Throughput:        > 100,000 messages/second sustained
  Sequencing:        O(1) per message
  Channel routing:   O(subscribers) per message

Scale 2+ adds network transport beneath this same API. The bus doesn't
know or care whether messages originate locally or remotely — the
transport layer handles that.

Usage:
    bus = CoordinationBus(node_id="node-abc123")
    bus.create_channel("memory.events", mode=ChannelMode.BROADCAST)
    sub_id = await bus.subscribe("memory.events", my_handler)
    await bus.publish("memory.events", MessageType.MEMORY_CREATED, payload)
    await bus.shutdown()
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set

from open_brain.coordination.channel import (
    Channel,
    ChannelConfig,
    ChannelMode,
    Handler,
)
from open_brain.coordination.circuit_breaker import (
    BreakerConfig,
    BreakerRegistry,
    BreakerState,
)
from open_brain.coordination.presence import (
    NodeInfo,
    PresenceConfig,
    PresenceManager,
)
from open_brain.coordination.protocol import (
    Envelope,
    MessageType,
    make_envelope,
    sign_envelope,
)
from open_brain.coordination.sequencer import Sequencer

logger = logging.getLogger(__name__)


class CoordinationBus:
    """High-performance coordination bus for distributed AI agents.

    Single entry point for all coordination operations. Manages
    channels, sequencing, circuit breaking, presence, and message
    dispatch.

    The bus operates in two modes:
      1. In-process (Scale 0-1): All routing is local asyncio.
         Zero serialisation, sub-millisecond dispatch.
      2. Network (Scale 2+): A transport adapter handles remote
         delivery. Same API — the bus is transport-agnostic.

    The bus is NOT thread-safe by design — it runs on a single
    asyncio event loop. Cross-thread access uses
    loop.call_soon_threadsafe().
    """

    def __init__(
        self,
        node_id: str,
        *,
        breaker_config: Optional[BreakerConfig] = None,
        presence_config: Optional[PresenceConfig] = None,
        private_key_bytes: Optional[bytes] = None,
        trust_lookup: Optional[Callable[[str], float]] = None,
    ) -> None:
        self.node_id = node_id
        self._channels: Dict[str, Channel] = {}
        self._sequencer = Sequencer()
        self._breakers = BreakerRegistry(breaker_config)
        self._presence = PresenceManager(node_id, presence_config)
        self._private_key = private_key_bytes
        self._trust_lookup = trust_lookup
        self._running = False
        self._message_log: List[Envelope] = []  # In-memory audit trail.
        self._max_log_size = 100_000
        self._stats = {
            "published": 0,
            "rejected_breaker": 0,
            "rejected_error": 0,
        }

        # Pre-create system channels.
        self.create_channel(
            "system.heartbeat",
            ChannelConfig(mode=ChannelMode.BROADCAST),
        )
        self.create_channel(
            "system.presence",
            ChannelConfig(mode=ChannelMode.BROADCAST),
        )

    # ------------------------------------------------------------------
    # Channel management
    # ------------------------------------------------------------------

    def create_channel(
        self,
        name: str,
        config: Optional[ChannelConfig] = None,
    ) -> Channel:
        """Create a named channel. Idempotent — returns existing if found."""
        if name not in self._channels:
            self._channels[name] = Channel(name, config)
        return self._channels[name]

    def get_channel(self, name: str) -> Optional[Channel]:
        return self._channels.get(name)

    def remove_channel(self, name: str) -> bool:
        return self._channels.pop(name, None) is not None

    def list_channels(self) -> List[Dict[str, Any]]:
        return [ch.stats for ch in self._channels.values()]

    # ------------------------------------------------------------------
    # Subscribe / unsubscribe
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        channel_name: str,
        handler: Handler,
        *,
        type_filter: Optional[Set[str]] = None,
    ) -> str:
        """Subscribe to a channel. Creates the channel if it doesn't exist.

        Returns a subscription ID for later unsubscription.
        """
        channel = self.create_channel(channel_name)
        return channel.subscribe(
            handler,
            self.node_id,
            type_filter=type_filter,
        )

    def unsubscribe(self, channel_name: str, sub_id: str) -> bool:
        channel = self._channels.get(channel_name)
        if channel is None:
            return False
        return channel.unsubscribe(sub_id)

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(
        self,
        channel_name: str,
        msg_type: MessageType | str,
        payload: Dict[str, Any],
        *,
        ttl_ms: int = 0,
        correlation_id: str = "",
        priority: int = 0,
    ) -> Optional[Envelope]:
        """Publish a message to a channel.

        Assigns a sequence number, computes the content hash, optionally
        signs the message, checks the circuit breaker, then dispatches
        to channel subscribers.

        Returns the Envelope on success, None if rejected by circuit breaker.
        """
        # --- Circuit breaker check ---
        sender_key = f"node:{self.node_id}"
        if not self._breakers.allow(sender_key):
            self._stats["rejected_breaker"] += 1
            logger.warning(
                "Circuit breaker tripped for %s on channel %s",
                self.node_id, channel_name,
            )
            return None

        channel_key = f"channel:{channel_name}"
        if not self._breakers.allow(channel_key):
            self._stats["rejected_breaker"] += 1
            return None

        # --- Build envelope ---
        seq = self._sequencer.next(self.node_id, channel_name)
        envelope = make_envelope(
            msg_type=msg_type,
            sender=self.node_id,
            channel=channel_name,
            payload=payload,
            sequence=seq,
            ttl_ms=ttl_ms,
            correlation_id=correlation_id,
            priority=priority,
        )

        # --- Sign if key available ---
        if self._private_key:
            envelope = sign_envelope(envelope, self._private_key)

        # --- Dispatch ---
        channel = self.create_channel(channel_name)
        try:
            await channel.dispatch(envelope, self._trust_lookup)
            self._stats["published"] += 1
        except Exception:
            logger.exception("Dispatch error on channel %s", channel_name)
            self._breakers.get(channel_key).record_error()
            self._stats["rejected_error"] += 1
            return None

        # --- Audit log (bounded) ---
        self._message_log.append(envelope)
        if len(self._message_log) > self._max_log_size:
            self._message_log = self._message_log[-self._max_log_size:]

        return envelope

    async def publish_envelope(self, envelope: Envelope) -> bool:
        """Publish a pre-built envelope (e.g., received from a remote node).

        Validates the sequence number (gap detection) and dispatches.
        Returns True on successful dispatch.
        """
        # Sequence validation (gap detection for remote messages).
        gap = self._sequencer.check(
            envelope.sender,
            envelope.channel,
            envelope.sequence,
            envelope.timestamp_ns,
        )
        if gap:
            logger.warning(
                "Sequence gap on %s/%s: expected %d, got %d (gap=%d)",
                envelope.sender, envelope.channel,
                gap.expected, gap.received, gap.gap_size,
            )

        channel = self._channels.get(envelope.channel)
        if channel is None:
            return False

        try:
            await channel.dispatch(envelope, self._trust_lookup)
            self._message_log.append(envelope)
            if len(self._message_log) > self._max_log_size:
                self._message_log = self._message_log[-self._max_log_size:]
            return True
        except Exception:
            logger.exception(
                "Dispatch error for envelope %s on channel %s",
                envelope.msg_id, envelope.channel,
            )
            return False

    # ------------------------------------------------------------------
    # Request / reply pattern
    # ------------------------------------------------------------------

    async def request(
        self,
        channel_name: str,
        msg_type: MessageType | str,
        payload: Dict[str, Any],
        *,
        timeout_s: float = 5.0,
        ttl_ms: int = 0,
    ) -> Optional[Envelope]:
        """Send a request and wait for a correlated response.

        Returns the response Envelope, or None on timeout.
        Uses correlation_id to match request → response.
        """
        import uuid as _uuid

        correlation_id = str(_uuid.uuid4())
        request_msg_type = (
            msg_type.value if isinstance(msg_type, MessageType) else msg_type
        )
        response_future: asyncio.Future[Envelope] = asyncio.get_event_loop().create_future()

        async def _response_handler(env: Envelope) -> None:
            # Match correlation_id but skip the outgoing request itself.
            # A response MUST have a different msg_type than the request
            # (financial parallel: an order ACK is never the same message
            # type as the order itself).
            if (
                env.correlation_id == correlation_id
                and env.msg_type != request_msg_type
                and not response_future.done()
            ):
                response_future.set_result(env)

        # Subscribe temporarily for the response.
        sub_id = await self.subscribe(channel_name, _response_handler)

        try:
            await self.publish(
                channel_name,
                msg_type,
                payload,
                correlation_id=correlation_id,
                ttl_ms=ttl_ms or int(timeout_s * 1000),
            )

            return await asyncio.wait_for(response_future, timeout=timeout_s)
        except asyncio.TimeoutError:
            return None
        finally:
            self.unsubscribe(channel_name, sub_id)

    # ------------------------------------------------------------------
    # Presence
    # ------------------------------------------------------------------

    @property
    def presence(self) -> PresenceManager:
        return self._presence

    async def announce(
        self,
        capabilities: Optional[Set[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Announce this node's presence and capabilities."""
        self._presence.record_announce(
            self.node_id,
            capabilities=capabilities or set(),
            metadata=metadata or {},
        )
        await self.publish(
            "system.presence",
            MessageType.NODE_ANNOUNCE,
            {
                "node_id": self.node_id,
                "capabilities": list(capabilities or []),
                "metadata": metadata or {},
            },
        )

    async def _send_heartbeat(self) -> None:
        """Send a heartbeat message (called by presence manager loop)."""
        await self.publish(
            "system.heartbeat",
            MessageType.HEARTBEAT,
            {"node_id": self.node_id, "timestamp_ns": time.time_ns()},
            ttl_ms=int(self._presence.config.heartbeat_interval_s * 2000),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the bus: begin heartbeat loop and presence monitoring."""
        if self._running:
            return
        self._running = True
        await self._presence.start(self._send_heartbeat)
        await self.announce()
        logger.info("Coordination bus started (node=%s)", self.node_id)

    async def shutdown(self) -> None:
        """Graceful shutdown: announce departure, stop heartbeats."""
        if not self._running:
            return
        self._running = False

        # Announce departure.
        await self.publish(
            "system.presence",
            MessageType.NODE_DEPART,
            {"node_id": self.node_id},
        )
        self._presence.record_depart(self.node_id)
        await self._presence.stop()
        logger.info("Coordination bus stopped (node=%s)", self.node_id)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def sequencer(self) -> Sequencer:
        return self._sequencer

    @property
    def breakers(self) -> BreakerRegistry:
        return self._breakers

    @property
    def is_running(self) -> bool:
        return self._running

    def recent_messages(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return the most recent messages from the audit log."""
        return [e.to_dict() for e in self._message_log[-limit:]]

    def stats(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "running": self._running,
            "channels": len(self._channels),
            "sequences": self._sequencer.streams(),
            "gaps": [
                {
                    "sender": g.sender,
                    "channel": g.channel,
                    "expected": g.expected,
                    "received": g.received,
                }
                for g in self._sequencer.gaps()
            ],
            "audit_log_size": len(self._message_log),
            "presence": self._presence.summary(),
            **self._stats,
        }
