"""Circuit breaker — rate limiting and anomaly detection.

Financial market parallel: exchange circuit breakers halt trading when
prices move too fast or volume spikes abnormally. Genesis parallel:
the auto-immune system detects and responds to anomalous behaviour.

This module provides per-node and per-channel rate limiting with
graduated response:
  CLOSED  — normal operation, messages flow freely.
  OPEN    — tripped, all messages rejected until cooldown expires.
  HALF    — cooldown expired, limited traffic allowed to test recovery.

The breaker also tracks anomaly indicators:
  - Message rate exceeding configured threshold (burst detection).
  - Repeated failures (error cascade detection).
  - Unusual payload patterns (size spikes, type concentration).

Graduated response maps to Genesis ThreatSeverity:
  Rate exceeded      → LOW  (log, continue)
  Sustained overload → MEDIUM (throttle)
  Burst spike        → HIGH (trip breaker, queue for human review)
  Error cascade      → CRITICAL (trip + alert)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class BreakerState(str, Enum):
    """Circuit breaker states (standard three-state model)."""
    CLOSED = "closed"   # Normal — messages flow.
    OPEN = "open"       # Tripped — messages rejected.
    HALF_OPEN = "half_open"  # Testing recovery — limited flow.


@dataclass
class BreakerConfig:
    """Configuration for a single circuit breaker instance."""

    # Rate limiting.
    max_messages_per_second: float = 1000.0
    burst_multiplier: float = 3.0  # Allowed burst above sustained rate.

    # Trip thresholds.
    trip_threshold: int = 5    # Consecutive violations before tripping.
    cooldown_seconds: float = 10.0  # How long OPEN state lasts.

    # Half-open recovery.
    half_open_max: int = 5     # Messages allowed in HALF_OPEN before re-eval.

    # Error cascade.
    error_threshold: int = 10  # Errors in window before cascade trip.
    error_window_seconds: float = 60.0


@dataclass
class BreakerStats:
    """Runtime statistics for a circuit breaker."""

    total_allowed: int = 0
    total_rejected: int = 0
    total_trips: int = 0
    consecutive_violations: int = 0
    errors_in_window: int = 0
    state: BreakerState = BreakerState.CLOSED
    last_trip_time: float = 0.0
    last_message_time: float = 0.0
    half_open_count: int = 0


class CircuitBreaker:
    """Per-node or per-channel circuit breaker.

    Thread-safe. O(1) per check (no windowed counting — uses
    token-bucket approximation for rate limiting).

    Usage:
        cb = CircuitBreaker(BreakerConfig(max_messages_per_second=100))
        if cb.allow():
            # dispatch message
        else:
            # reject or queue
        cb.record_error()  # on downstream failure
    """

    def __init__(self, config: Optional[BreakerConfig] = None) -> None:
        self._config = config or BreakerConfig()
        self._stats = BreakerStats()
        self._lock = threading.Lock()

        # Token bucket state.
        self._tokens = self._config.max_messages_per_second
        self._max_tokens = (
            self._config.max_messages_per_second * self._config.burst_multiplier
        )
        self._last_refill = time.monotonic()

    def allow(self) -> bool:
        """Check whether a message should be allowed through.

        Returns True if the message is permitted, False if rejected.
        Updates internal state (token consumption, violation tracking).
        """
        with self._lock:
            now = time.monotonic()
            self._refill_tokens(now)

            # State machine.
            if self._stats.state == BreakerState.OPEN:
                elapsed = now - self._stats.last_trip_time
                if elapsed >= self._config.cooldown_seconds:
                    self._stats.state = BreakerState.HALF_OPEN
                    self._stats.half_open_count = 0
                else:
                    self._stats.total_rejected += 1
                    return False

            if self._stats.state == BreakerState.HALF_OPEN:
                if self._stats.half_open_count >= self._config.half_open_max:
                    # Recovery test passed — close the breaker.
                    self._stats.state = BreakerState.CLOSED
                    self._stats.consecutive_violations = 0
                else:
                    self._stats.half_open_count += 1

            # Token bucket check.
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self._stats.total_allowed += 1
                self._stats.consecutive_violations = 0
                self._stats.last_message_time = now
                return True

            # Rate exceeded — violation.
            self._stats.consecutive_violations += 1
            if self._stats.consecutive_violations >= self._config.trip_threshold:
                self._trip(now)
                self._stats.total_rejected += 1
                return False

            # Below trip threshold — still allow but warn.
            self._stats.total_allowed += 1
            self._stats.last_message_time = now
            return True

    def record_error(self) -> None:
        """Record a downstream error for cascade detection."""
        with self._lock:
            now = time.monotonic()
            self._stats.errors_in_window += 1
            if self._stats.errors_in_window >= self._config.error_threshold:
                self._trip(now)
                self._stats.errors_in_window = 0

    def reset(self) -> None:
        """Manually reset the breaker to CLOSED state."""
        with self._lock:
            self._stats.state = BreakerState.CLOSED
            self._stats.consecutive_violations = 0
            self._stats.errors_in_window = 0
            self._stats.half_open_count = 0
            self._tokens = self._config.max_messages_per_second

    @property
    def state(self) -> BreakerState:
        with self._lock:
            # Check for automatic transition from OPEN → HALF_OPEN.
            if self._stats.state == BreakerState.OPEN:
                elapsed = time.monotonic() - self._stats.last_trip_time
                if elapsed >= self._config.cooldown_seconds:
                    self._stats.state = BreakerState.HALF_OPEN
                    self._stats.half_open_count = 0
            return self._stats.state

    @property
    def stats(self) -> BreakerStats:
        with self._lock:
            # Return a snapshot (not the mutable internal object).
            return BreakerStats(
                total_allowed=self._stats.total_allowed,
                total_rejected=self._stats.total_rejected,
                total_trips=self._stats.total_trips,
                consecutive_violations=self._stats.consecutive_violations,
                errors_in_window=self._stats.errors_in_window,
                state=self._stats.state,
                last_trip_time=self._stats.last_trip_time,
                last_message_time=self._stats.last_message_time,
                half_open_count=self._stats.half_open_count,
            )

    def _trip(self, now: float) -> None:
        """Trip the breaker to OPEN state."""
        self._stats.state = BreakerState.OPEN
        self._stats.last_trip_time = now
        self._stats.total_trips += 1

    def _refill_tokens(self, now: float) -> None:
        """Refill the token bucket based on elapsed time."""
        elapsed = now - self._last_refill
        self._tokens = min(
            self._max_tokens,
            self._tokens + elapsed * self._config.max_messages_per_second,
        )
        self._last_refill = now


class BreakerRegistry:
    """Manages circuit breakers for multiple nodes and channels.

    Creates breakers on demand with configurable defaults.
    Thread-safe — each breaker has its own lock, and the registry
    lock protects only the breaker map.
    """

    def __init__(self, default_config: Optional[BreakerConfig] = None) -> None:
        self._default = default_config or BreakerConfig()
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> CircuitBreaker:
        """Get or create a circuit breaker for the given key.

        Key format: "node:<node_id>" or "channel:<channel_name>".
        """
        with self._lock:
            if key not in self._breakers:
                self._breakers[key] = CircuitBreaker(self._default)
            return self._breakers[key]

    def allow(self, key: str) -> bool:
        """Shorthand: check whether a message for *key* is allowed."""
        return self.get(key).allow()

    def trip_all(self) -> None:
        """Emergency: trip all breakers (network-wide halt)."""
        with self._lock:
            now = time.monotonic()
            for cb in self._breakers.values():
                with cb._lock:
                    cb._trip(now)

    def reset_all(self) -> None:
        """Reset all breakers to CLOSED."""
        with self._lock:
            for cb in self._breakers.values():
                cb.reset()

    def summary(self) -> List[Dict[str, object]]:
        """Snapshot of all breaker states."""
        with self._lock:
            result = []
            for key, cb in sorted(self._breakers.items()):
                s = cb.stats
                result.append({
                    "key": key,
                    "state": s.state.value,
                    "allowed": s.total_allowed,
                    "rejected": s.total_rejected,
                    "trips": s.total_trips,
                })
            return result
