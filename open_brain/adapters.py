"""Adapter protocols for project integration.

OB defines these protocols. Projects implement them. Zero OB-to-project
imports. The project registers adapters at startup via
``OpenBrain.register_adapter()``.

Design:
  - ``Any`` for all signal/event parameters — OB never inspects project types.
  - ``Dict[str, Any]`` for payloads — same envelope format as the bus.
  - ``runtime_checkable`` — adapters can be validated with ``isinstance()``.

Example (Genesis registration)::

    ob = OpenBrain(project="project_genesis", agent="cc")
    ob.register_adapter("event", GenesisEventAdapter())
    ob.register_adapter("insight", GenesisInsightAdapter())
    ob.register_adapter("threat", GenesisThreatAdapter())
    ob.register_adapter("epoch", GenesisEpochAdapter(epoch_service))
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class EventAdapter(Protocol):
    """Adapts project-specific events to OB envelope payloads.

    Genesis implements this for its 90+ EventKind types.
    Other projects implement it for their own event types.

    Required payload fields:
      - ``event_kind``: str — project-specific event type
      - ``event_hash``: str — content integrity hash (e.g. ``sha256:<hex>``)
      - ``source_project``: str — project identifier
    """

    def to_envelope_payload(self, event: Any) -> Dict[str, Any]:
        """Convert a project event to an OB envelope payload."""
        ...

    def from_envelope_payload(self, payload: Dict[str, Any]) -> Any:
        """Convert an OB envelope payload back to a project event.

        Raises ``ValueError`` if the payload is not from this project.
        """
        ...


@runtime_checkable
class InsightAdapter(Protocol):
    """Adapts project-specific insight signals to OB bus messages.

    Maps to ``MessageType.INSIGHT_SIGNAL`` on the coordination bus.

    Required payload fields:
      - ``signal_id``: str
      - ``signal_type``: str
      - ``confidence``: float (0.0–1.0)
      - ``provenance_hash``: str — content integrity hash (e.g. ``sha256:<hex>``)
      - ``source_project``: str
    """

    def to_bus_payload(self, signal: Any) -> Dict[str, Any]:
        """Convert a project insight signal to bus payload."""
        ...

    def validate(self, signal: Any) -> List[str]:
        """Validate the signal. Returns list of violations (empty = valid)."""
        ...


@runtime_checkable
class ThreatAdapter(Protocol):
    """Adapts project-specific threat signals to OB bus messages.

    Maps to ``MessageType.THREAT_SIGNAL`` on the coordination bus.

    Required payload fields:
      - ``signal_id``: str
      - ``threat_type``: str
      - ``severity``: str
      - ``evidence_hash``: str — content integrity hash (e.g. ``sha256:<hex>``)
      - ``affected_actors``: List[str]
      - ``source_project``: str
    """

    def to_bus_payload(self, signal: Any) -> Dict[str, Any]:
        """Convert a project threat signal to bus payload."""
        ...

    def severity_requires_human(self, signal: Any) -> bool:
        """Whether this severity level requires human oversight."""
        ...


@runtime_checkable
class EpochAdapter(Protocol):
    """Adapts project epoch/commitment events to OB epoch sealing.

    Genesis four-domain commitment is canonical. OB epoch uses
    single-domain Merkle. The adapter bridges them.

    Domain roots are returned as ``Dict[str, str]`` where keys are
    domain names and values are ``sha256:<hex>`` Merkle roots.
    """

    def domain_roots(self) -> Dict[str, str]:
        """Return Merkle roots for each domain.

        Genesis returns: ``{"mission": ..., "trust": ...,
        "governance": ..., "review": ...}``.
        Other projects return their own domain set.
        """
        ...

    def leaf_hashes(self, domain: str) -> List[str]:
        """Return ordered leaf hashes for a specific domain."""
        ...
