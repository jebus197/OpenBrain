"""Node presence — heartbeat, capability advertisement, and discovery.

Financial market parallel: FIX session heartbeats detect dropped
connections. Co-location services advertise capabilities (order types,
instruments). Market participant directories enable routing.

This module tracks which nodes are alive, what capabilities they
advertise (message types they can handle, resources they offer),
and detects node departure via heartbeat timeout.

Heartbeat interval and timeout are configurable. Defaults:
  interval = 5 seconds    (heartbeat sent every 5s)
  timeout  = 3 intervals  (15s silence → node considered down)

The presence manager is async — it runs a background heartbeat loop
and monitors incoming heartbeats from remote nodes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class NodeInfo:
    """Tracked state for a known node."""

    node_id: str
    capabilities: Set[str] = field(default_factory=set)
    last_heartbeat_ns: int = 0
    announced_ns: int = 0
    is_alive: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        if self.last_heartbeat_ns == 0:
            return float("inf")
        return (time.time_ns() - self.last_heartbeat_ns) / 1e9


@dataclass
class PresenceConfig:
    """Heartbeat and timeout configuration."""

    heartbeat_interval_s: float = 5.0
    timeout_multiplier: int = 3  # timeout = interval × multiplier
    max_nodes: int = 10_000       # Hard cap on tracked nodes.

    @property
    def timeout_s(self) -> float:
        return self.heartbeat_interval_s * self.timeout_multiplier


# Callbacks for presence events.
OnNodeJoin = Callable[[NodeInfo], None]
OnNodeDepart = Callable[[NodeInfo], None]


class PresenceManager:
    """Tracks node liveness and capabilities.

    Not async-native internally (uses plain dicts + time checks),
    but provides async methods for integration with the bus event loop.
    The heartbeat loop is started via start() and stopped via stop().
    """

    def __init__(
        self,
        local_node_id: str,
        config: Optional[PresenceConfig] = None,
    ) -> None:
        self.local_node_id = local_node_id
        self.config = config or PresenceConfig()
        self._nodes: Dict[str, NodeInfo] = {}
        self._on_join: Optional[OnNodeJoin] = None
        self._on_depart: Optional[OnNodeDepart] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False

        # Register self.
        self.record_announce(local_node_id, capabilities=set(), metadata={})

    def on_join(self, callback: OnNodeJoin) -> None:
        """Register a callback for node join events."""
        self._on_join = callback

    def on_depart(self, callback: OnNodeDepart) -> None:
        """Register a callback for node departure events."""
        self._on_depart = callback

    def record_announce(
        self,
        node_id: str,
        capabilities: Set[str],
        metadata: Dict[str, Any],
    ) -> None:
        """Record a node announcement (join or capability update)."""
        now = time.time_ns()
        existing = self._nodes.get(node_id)

        if existing is None:
            if len(self._nodes) >= self.config.max_nodes:
                logger.warning(
                    "Max node count (%d) reached, ignoring %s",
                    self.config.max_nodes, node_id,
                )
                return

            info = NodeInfo(
                node_id=node_id,
                capabilities=capabilities,
                last_heartbeat_ns=now,
                announced_ns=now,
                is_alive=True,
                metadata=metadata,
            )
            self._nodes[node_id] = info
            if self._on_join:
                self._on_join(info)
        else:
            existing.capabilities = capabilities
            existing.last_heartbeat_ns = now
            existing.metadata.update(metadata)
            if not existing.is_alive:
                existing.is_alive = True
                if self._on_join:
                    self._on_join(existing)

    def record_heartbeat(self, node_id: str) -> None:
        """Update the last-seen timestamp for a node."""
        info = self._nodes.get(node_id)
        if info is None:
            # Unknown node — record as anonymous announce.
            self.record_announce(node_id, capabilities=set(), metadata={})
            return
        info.last_heartbeat_ns = time.time_ns()
        if not info.is_alive:
            info.is_alive = True
            if self._on_join:
                self._on_join(info)

    def record_depart(self, node_id: str) -> None:
        """Mark a node as departed (graceful leave)."""
        info = self._nodes.get(node_id)
        if info and info.is_alive:
            info.is_alive = False
            if self._on_depart:
                self._on_depart(info)

    def check_timeouts(self) -> List[NodeInfo]:
        """Check all nodes for heartbeat timeout. Returns newly departed."""
        departed: List[NodeInfo] = []
        timeout_ns = int(self.config.timeout_s * 1e9)
        now = time.time_ns()

        for info in self._nodes.values():
            if info.node_id == self.local_node_id:
                continue  # Don't timeout self.
            if info.is_alive and (now - info.last_heartbeat_ns) > timeout_ns:
                info.is_alive = False
                departed.append(info)
                if self._on_depart:
                    self._on_depart(info)

        return departed

    def alive_nodes(self) -> List[NodeInfo]:
        """Return all currently alive nodes."""
        return [n for n in self._nodes.values() if n.is_alive]

    def get_node(self, node_id: str) -> Optional[NodeInfo]:
        return self._nodes.get(node_id)

    def nodes_with_capability(self, capability: str) -> List[NodeInfo]:
        """Find alive nodes that advertise a specific capability."""
        return [
            n for n in self._nodes.values()
            if n.is_alive and capability in n.capabilities
        ]

    async def start(self, send_heartbeat: Callable[[], Any]) -> None:
        """Start the background heartbeat loop.

        Args:
            send_heartbeat: Async callable that sends a heartbeat
                            message to the bus.
        """
        if self._running:
            return
        self._running = True
        self._heartbeat_task = asyncio.ensure_future(
            self._heartbeat_loop(send_heartbeat)
        )

    async def stop(self) -> None:
        """Stop the heartbeat loop."""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

    async def _heartbeat_loop(self, send_heartbeat: Callable[[], Any]) -> None:
        """Periodic heartbeat + timeout check."""
        while self._running:
            try:
                await send_heartbeat()
                self.check_timeouts()
                await asyncio.sleep(self.config.heartbeat_interval_s)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Heartbeat loop error")
                await asyncio.sleep(1.0)

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def alive_count(self) -> int:
        return sum(1 for n in self._nodes.values() if n.is_alive)

    def summary(self) -> Dict[str, Any]:
        return {
            "local_node": self.local_node_id,
            "total_nodes": self.node_count,
            "alive_nodes": self.alive_count,
            "heartbeat_interval_s": self.config.heartbeat_interval_s,
            "timeout_s": self.config.timeout_s,
        }
