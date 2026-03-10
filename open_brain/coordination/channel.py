"""Trust-gated pub/sub channels.

Financial market parallel:
  Broadcast channel → market data feed (one-to-many, all subscribers)
  Queue channel     → order flow (load-balanced, one consumer per message)
  Direct channel    → FIX session (one-to-one, named target)

Trust gating: each channel has a minimum trust level. Senders below
the threshold are rejected. This maps to Genesis trust-gated registration:
machines and actors must earn trust before participating in coordination.

At Scale 0-1 (in-process), channels are asyncio queues.
At Scale 2+, the transport layer handles network delivery, but the
channel abstraction and trust gates remain the same.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from open_brain.coordination.protocol import Envelope

logger = logging.getLogger(__name__)

# Type alias for message handlers.
# Handlers are async callables that receive an Envelope.
Handler = Callable[[Envelope], Awaitable[None]]


class ChannelMode(str, Enum):
    """How messages are distributed to subscribers."""
    BROADCAST = "broadcast"  # Every subscriber gets every message.
    QUEUE = "queue"          # Round-robin: one subscriber per message.
    DIRECT = "direct"        # Named target: only the addressed subscriber.


@dataclass
class ChannelConfig:
    """Configuration for a channel."""
    mode: ChannelMode = ChannelMode.BROADCAST
    min_trust: float = 0.0       # Minimum trust level for senders.
    max_backlog: int = 10_000    # Maximum queued messages before backpressure.
    persistent: bool = False     # Whether to persist messages to DB.
    type_filter: Optional[Set[str]] = None  # If set, only these msg_types allowed.


@dataclass
class Subscription:
    """A registered subscriber on a channel."""
    sub_id: str
    handler: Handler
    node_id: str               # Subscriber's node_id (for DIRECT routing).
    type_filter: Optional[Set[str]] = None  # Additional per-subscriber type filter.
    created_ns: int = field(default_factory=time.time_ns)


class Channel:
    """A named, trust-gated message channel.

    Manages a set of subscribers and dispatches messages according
    to the channel mode (broadcast, queue, direct).

    Thread safety: asyncio-native. All mutation and dispatch happens
    on the event loop — no threading locks needed. For cross-thread
    access, use loop.call_soon_threadsafe().
    """

    def __init__(self, name: str, config: Optional[ChannelConfig] = None) -> None:
        self.name = name
        self.config = config or ChannelConfig()
        self._subscribers: Dict[str, Subscription] = {}
        self._queue_index = 0  # Round-robin counter for QUEUE mode.
        self._stats = {
            "dispatched": 0,
            "dropped_trust": 0,
            "dropped_type": 0,
            "dropped_backlog": 0,
            "dropped_expired": 0,
        }

    def subscribe(
        self,
        handler: Handler,
        node_id: str,
        *,
        type_filter: Optional[Set[str]] = None,
    ) -> str:
        """Register a subscriber. Returns a subscription ID."""
        sub_id = str(uuid.uuid4())
        self._subscribers[sub_id] = Subscription(
            sub_id=sub_id,
            handler=handler,
            node_id=node_id,
            type_filter=type_filter,
        )
        return sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        """Remove a subscriber by ID. Returns True if found."""
        return self._subscribers.pop(sub_id, None) is not None

    async def dispatch(
        self,
        envelope: Envelope,
        trust_lookup: Optional[Callable[[str], float]] = None,
    ) -> int:
        """Dispatch a message to subscribers according to channel mode.

        Args:
            envelope: The message to dispatch.
            trust_lookup: Callable that returns the trust level for a
                          sender node_id. If None, trust gating is skipped.

        Returns:
            Number of subscribers that received the message.
        """
        # --- Gate: TTL expiry ---
        if envelope.is_expired():
            self._stats["dropped_expired"] += 1
            return 0

        # --- Gate: trust level ---
        if self.config.min_trust > 0 and trust_lookup is not None:
            sender_trust = trust_lookup(envelope.sender)
            if sender_trust < self.config.min_trust:
                self._stats["dropped_trust"] += 1
                logger.debug(
                    "Channel %s rejected sender %s (trust %.2f < %.2f)",
                    self.name, envelope.sender, sender_trust, self.config.min_trust,
                )
                return 0

        # --- Gate: channel-level type filter ---
        if self.config.type_filter and envelope.msg_type not in self.config.type_filter:
            self._stats["dropped_type"] += 1
            return 0

        # --- Dispatch by mode ---
        if self.config.mode == ChannelMode.BROADCAST:
            return await self._dispatch_broadcast(envelope)
        elif self.config.mode == ChannelMode.QUEUE:
            return await self._dispatch_queue(envelope)
        elif self.config.mode == ChannelMode.DIRECT:
            return await self._dispatch_direct(envelope)
        return 0

    async def _dispatch_broadcast(self, envelope: Envelope) -> int:
        """Send to all matching subscribers."""
        targets = self._matching_subscribers(envelope)
        delivered = 0
        for sub in targets:
            try:
                await sub.handler(envelope)
                delivered += 1
            except Exception:
                logger.exception(
                    "Handler error on channel %s, sub %s",
                    self.name, sub.sub_id,
                )
        self._stats["dispatched"] += delivered
        return delivered

    async def _dispatch_queue(self, envelope: Envelope) -> int:
        """Send to one subscriber (round-robin)."""
        targets = self._matching_subscribers(envelope)
        if not targets:
            return 0

        idx = self._queue_index % len(targets)
        self._queue_index += 1
        sub = targets[idx]
        try:
            await sub.handler(envelope)
            self._stats["dispatched"] += 1
            return 1
        except Exception:
            logger.exception(
                "Handler error on channel %s, sub %s",
                self.name, sub.sub_id,
            )
            return 0

    async def _dispatch_direct(self, envelope: Envelope) -> int:
        """Send to the subscriber whose node_id matches the payload target."""
        target_node = envelope.payload.get("target_node", "")
        if not target_node:
            return 0

        for sub in self._subscribers.values():
            if sub.node_id == target_node:
                if not self._type_matches(sub, envelope):
                    continue
                try:
                    await sub.handler(envelope)
                    self._stats["dispatched"] += 1
                    return 1
                except Exception:
                    logger.exception(
                        "Handler error on channel %s, sub %s",
                        self.name, sub.sub_id,
                    )
                    return 0
        return 0

    def _matching_subscribers(self, envelope: Envelope) -> List[Subscription]:
        """Filter subscribers by their per-subscription type filters."""
        return [
            sub for sub in self._subscribers.values()
            if self._type_matches(sub, envelope)
        ]

    @staticmethod
    def _type_matches(sub: Subscription, envelope: Envelope) -> bool:
        if sub.type_filter is None:
            return True
        return envelope.msg_type in sub.type_filter

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "mode": self.config.mode.value,
            "subscribers": self.subscriber_count,
            "min_trust": self.config.min_trust,
            **self._stats,
        }
