"""Deterministic message sequencer — total ordering and gap detection.

Financial market parallel: FIX session-level sequence numbers. Every
message within a (sender, channel) pair gets a monotonically increasing
sequence number. Gaps indicate message loss; duplicates indicate replay.

Properties:
  - Monotonic: sequence numbers never decrease within a stream.
  - Gap-free: any gap between consecutive numbers is a detectable fault.
  - Per-stream: each (sender, channel) pair has an independent counter.
  - Replayable: given a starting sequence, all subsequent messages can
    be replayed in exact order.

The sequencer is synchronous — no async overhead on the critical path.
Sequence assignment is O(1). Gap detection is O(1).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class GapRecord:
    """A detected gap in a message sequence."""

    sender: str
    channel: str
    expected: int
    received: int
    detected_ns: int  # time.time_ns() when the gap was found

    @property
    def gap_size(self) -> int:
        return self.received - self.expected


class Sequencer:
    """Assigns and validates monotonic sequence numbers.

    Thread-safe via a lock on the counter dict. The lock is fine-grained
    (per-operation, not per-stream) to minimise contention.

    Usage:
        seq = Sequencer()
        n = seq.next("node-abc", "memory.events")  # → 1
        n = seq.next("node-abc", "memory.events")  # → 2
        gaps = seq.check("node-abc", "memory.events", 5)  # gap: expected 3, got 5
    """

    def __init__(self) -> None:
        self._counters: Dict[Tuple[str, str], int] = {}
        self._received: Dict[Tuple[str, str], int] = {}
        self._gaps: List[GapRecord] = []
        self._lock = threading.Lock()

    def next(self, sender: str, channel: str) -> int:
        """Assign the next sequence number for a (sender, channel) stream.

        Returns the new sequence number (1-based).
        """
        key = (sender, channel)
        with self._lock:
            current = self._counters.get(key, 0)
            current += 1
            self._counters[key] = current
            return current

    def current(self, sender: str, channel: str) -> int:
        """Return the current (last assigned) sequence number.

        Returns 0 if no messages have been sequenced for this stream.
        """
        with self._lock:
            return self._counters.get((sender, channel), 0)

    def check(
        self,
        sender: str,
        channel: str,
        received_seq: int,
        timestamp_ns: int = 0,
    ) -> Optional[GapRecord]:
        """Validate a received sequence number against expectations.

        Returns a GapRecord if a gap is detected, None otherwise.
        Duplicate (already-seen) sequence numbers return None but are
        not advanced — the caller should handle deduplication.
        """
        key = (sender, channel)
        with self._lock:
            expected = self._received.get(key, 0) + 1

            if received_seq < expected:
                # Duplicate or out-of-order — caller decides policy.
                return None

            if received_seq > expected:
                gap = GapRecord(
                    sender=sender,
                    channel=channel,
                    expected=expected,
                    received=received_seq,
                    detected_ns=timestamp_ns,
                )
                self._gaps.append(gap)
                self._received[key] = received_seq
                return gap

            # Exactly expected — advance.
            self._received[key] = received_seq
            return None

    def gaps(self) -> List[GapRecord]:
        """Return all detected gaps (oldest first)."""
        with self._lock:
            return list(self._gaps)

    def clear_gaps(self) -> int:
        """Clear the gap log. Returns the number of gaps cleared."""
        with self._lock:
            count = len(self._gaps)
            self._gaps.clear()
            return count

    def reset(self, sender: str, channel: str) -> None:
        """Reset counters for a stream (e.g., after a node restart)."""
        key = (sender, channel)
        with self._lock:
            self._counters.pop(key, None)
            self._received.pop(key, None)

    def streams(self) -> List[Dict[str, object]]:
        """List all known streams with their current sequence numbers."""
        with self._lock:
            result = []
            all_keys = set(self._counters.keys()) | set(self._received.keys())
            for sender, channel in sorted(all_keys):
                result.append({
                    "sender": sender,
                    "channel": channel,
                    "assigned": self._counters.get((sender, channel), 0),
                    "received": self._received.get((sender, channel), 0),
                })
            return result
