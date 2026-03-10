"""Tests for adapter protocols — structural typing and payload contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from open_brain.adapters import (
    EpochAdapter,
    EventAdapter,
    InsightAdapter,
    ThreatAdapter,
)


# ---------------------------------------------------------------------------
# Mock project types (simulate Genesis-like events/signals)
# ---------------------------------------------------------------------------


@dataclass
class MockEvent:
    kind: str
    content_hash: str
    actor_id: str = "actor-1"


@dataclass
class MockInsight:
    signal_id: str
    signal_type: str
    confidence: float
    provenance_hash: str
    source_mission_id: str = "mission-1"


@dataclass
class MockThreat:
    signal_id: str
    threat_type: str
    severity: str  # "low", "medium", "high", "critical"
    evidence_hash: str
    affected_actor_ids: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Mock adapter implementations (what a project would write)
# ---------------------------------------------------------------------------


class MockEventAdapter:
    """Implements EventAdapter for mock project events."""

    def to_envelope_payload(self, event: Any) -> Dict[str, Any]:
        return {
            "event_kind": event.kind,
            "event_hash": event.content_hash,
            "source_project": "mock_project",
            "actor_id": event.actor_id,
        }

    def from_envelope_payload(self, payload: Dict[str, Any]) -> Any:
        if payload.get("source_project") != "mock_project":
            raise ValueError("Not a mock_project event")
        return MockEvent(
            kind=payload["event_kind"],
            content_hash=payload["event_hash"],
            actor_id=payload.get("actor_id", "unknown"),
        )


class MockInsightAdapter:
    """Implements InsightAdapter for mock insight signals."""

    def to_bus_payload(self, signal: Any) -> Dict[str, Any]:
        return {
            "signal_id": signal.signal_id,
            "signal_type": signal.signal_type,
            "confidence": signal.confidence,
            "provenance_hash": signal.provenance_hash,
            "source_project": "mock_project",
            "source_mission_id": signal.source_mission_id,
        }

    def validate(self, signal: Any) -> List[str]:
        violations = []
        if not 0.0 <= signal.confidence <= 1.0:
            violations.append("confidence must be between 0.0 and 1.0")
        if not signal.provenance_hash.startswith("sha256:"):
            violations.append("provenance_hash must start with 'sha256:'")
        return violations


class MockThreatAdapter:
    """Implements ThreatAdapter for mock threat signals."""

    HUMAN_REQUIRED = {"high", "critical"}

    def to_bus_payload(self, signal: Any) -> Dict[str, Any]:
        return {
            "signal_id": signal.signal_id,
            "threat_type": signal.threat_type,
            "severity": signal.severity,
            "evidence_hash": signal.evidence_hash,
            "affected_actors": signal.affected_actor_ids,
            "source_project": "mock_project",
        }

    def severity_requires_human(self, signal: Any) -> bool:
        return signal.severity in self.HUMAN_REQUIRED


class MockEpochAdapter:
    """Implements EpochAdapter for mock epoch sealing."""

    def __init__(self) -> None:
        self._domains: Dict[str, List[str]] = {
            "mission": [
                "sha256:aaa111",
                "sha256:aaa222",
            ],
            "trust": [
                "sha256:bbb111",
            ],
        }

    def domain_roots(self) -> Dict[str, str]:
        import hashlib

        roots = {}
        for domain, leaves in self._domains.items():
            combined = "|".join(leaves)
            digest = hashlib.sha256(combined.encode()).hexdigest()
            roots[domain] = f"sha256:{digest}"
        return roots

    def leaf_hashes(self, domain: str) -> List[str]:
        return self._domains.get(domain, [])


# ---------------------------------------------------------------------------
# Protocol satisfaction tests (isinstance with runtime_checkable)
# ---------------------------------------------------------------------------


class TestProtocolSatisfaction:
    def test_event_adapter_satisfies_protocol(self) -> None:
        adapter = MockEventAdapter()
        assert isinstance(adapter, EventAdapter)

    def test_insight_adapter_satisfies_protocol(self) -> None:
        adapter = MockInsightAdapter()
        assert isinstance(adapter, InsightAdapter)

    def test_threat_adapter_satisfies_protocol(self) -> None:
        adapter = MockThreatAdapter()
        assert isinstance(adapter, ThreatAdapter)

    def test_epoch_adapter_satisfies_protocol(self) -> None:
        adapter = MockEpochAdapter()
        assert isinstance(adapter, EpochAdapter)

    def test_plain_object_does_not_satisfy_event(self) -> None:
        assert not isinstance(object(), EventAdapter)

    def test_plain_object_does_not_satisfy_insight(self) -> None:
        assert not isinstance(object(), InsightAdapter)

    def test_plain_object_does_not_satisfy_threat(self) -> None:
        assert not isinstance(object(), ThreatAdapter)

    def test_plain_object_does_not_satisfy_epoch(self) -> None:
        assert not isinstance(object(), EpochAdapter)


# ---------------------------------------------------------------------------
# EventAdapter tests
# ---------------------------------------------------------------------------


class TestEventAdapter:
    def test_to_envelope_payload(self) -> None:
        adapter = MockEventAdapter()
        event = MockEvent(kind="mission.created", content_hash="sha256:abc123")
        payload = adapter.to_envelope_payload(event)
        assert payload["event_kind"] == "mission.created"
        assert payload["event_hash"] == "sha256:abc123"
        assert payload["source_project"] == "mock_project"
        assert payload["actor_id"] == "actor-1"

    def test_from_envelope_payload_roundtrip(self) -> None:
        adapter = MockEventAdapter()
        original = MockEvent(
            kind="trust.updated",
            content_hash="sha256:def456",
            actor_id="actor-7",
        )
        payload = adapter.to_envelope_payload(original)
        reconstructed = adapter.from_envelope_payload(payload)
        assert reconstructed.kind == original.kind
        assert reconstructed.content_hash == original.content_hash
        assert reconstructed.actor_id == original.actor_id

    def test_from_envelope_payload_wrong_project(self) -> None:
        adapter = MockEventAdapter()
        payload = {
            "event_kind": "some.event",
            "event_hash": "sha256:xxx",
            "source_project": "other_project",
        }
        with pytest.raises(ValueError, match="Not a mock_project"):
            adapter.from_envelope_payload(payload)

    def test_payload_has_required_fields(self) -> None:
        adapter = MockEventAdapter()
        event = MockEvent(kind="test.event", content_hash="sha256:test")
        payload = adapter.to_envelope_payload(event)
        required = {"event_kind", "event_hash", "source_project"}
        assert required.issubset(payload.keys())


# ---------------------------------------------------------------------------
# InsightAdapter tests
# ---------------------------------------------------------------------------


class TestInsightAdapter:
    def test_to_bus_payload(self) -> None:
        adapter = MockInsightAdapter()
        signal = MockInsight(
            signal_id="ins-001",
            signal_type="pattern_detected",
            confidence=0.85,
            provenance_hash="sha256:provenance123",
        )
        payload = adapter.to_bus_payload(signal)
        assert payload["signal_id"] == "ins-001"
        assert payload["signal_type"] == "pattern_detected"
        assert payload["confidence"] == 0.85
        assert payload["provenance_hash"] == "sha256:provenance123"
        assert payload["source_project"] == "mock_project"

    def test_validate_valid_signal(self) -> None:
        adapter = MockInsightAdapter()
        signal = MockInsight(
            signal_id="ins-002",
            signal_type="anomaly",
            confidence=0.5,
            provenance_hash="sha256:abc",
        )
        violations = adapter.validate(signal)
        assert violations == []

    def test_validate_confidence_out_of_range(self) -> None:
        adapter = MockInsightAdapter()
        signal = MockInsight(
            signal_id="ins-003",
            signal_type="anomaly",
            confidence=1.5,
            provenance_hash="sha256:abc",
        )
        violations = adapter.validate(signal)
        assert len(violations) == 1
        assert "confidence" in violations[0]

    def test_validate_bad_provenance_hash(self) -> None:
        adapter = MockInsightAdapter()
        signal = MockInsight(
            signal_id="ins-004",
            signal_type="anomaly",
            confidence=0.7,
            provenance_hash="md5:notsha256",
        )
        violations = adapter.validate(signal)
        assert len(violations) == 1
        assert "provenance_hash" in violations[0]

    def test_validate_multiple_violations(self) -> None:
        adapter = MockInsightAdapter()
        signal = MockInsight(
            signal_id="ins-005",
            signal_type="anomaly",
            confidence=-0.1,
            provenance_hash="bad_hash",
        )
        violations = adapter.validate(signal)
        assert len(violations) == 2

    def test_payload_has_required_fields(self) -> None:
        adapter = MockInsightAdapter()
        signal = MockInsight(
            signal_id="ins-006",
            signal_type="test",
            confidence=0.5,
            provenance_hash="sha256:test",
        )
        payload = adapter.to_bus_payload(signal)
        required = {
            "signal_id",
            "signal_type",
            "confidence",
            "provenance_hash",
            "source_project",
        }
        assert required.issubset(payload.keys())


# ---------------------------------------------------------------------------
# ThreatAdapter tests
# ---------------------------------------------------------------------------


class TestThreatAdapter:
    def test_to_bus_payload(self) -> None:
        adapter = MockThreatAdapter()
        threat = MockThreat(
            signal_id="thr-001",
            threat_type="collusion",
            severity="high",
            evidence_hash="sha256:evidence123",
            affected_actor_ids=["actor-1", "actor-2"],
        )
        payload = adapter.to_bus_payload(threat)
        assert payload["signal_id"] == "thr-001"
        assert payload["threat_type"] == "collusion"
        assert payload["severity"] == "high"
        assert payload["evidence_hash"] == "sha256:evidence123"
        assert payload["affected_actors"] == ["actor-1", "actor-2"]
        assert payload["source_project"] == "mock_project"

    def test_severity_requires_human_high(self) -> None:
        adapter = MockThreatAdapter()
        threat = MockThreat(
            signal_id="thr-002",
            threat_type="sybil",
            severity="high",
            evidence_hash="sha256:xxx",
        )
        assert adapter.severity_requires_human(threat) is True

    def test_severity_requires_human_critical(self) -> None:
        adapter = MockThreatAdapter()
        threat = MockThreat(
            signal_id="thr-003",
            threat_type="sybil",
            severity="critical",
            evidence_hash="sha256:xxx",
        )
        assert adapter.severity_requires_human(threat) is True

    def test_severity_no_human_for_low(self) -> None:
        adapter = MockThreatAdapter()
        threat = MockThreat(
            signal_id="thr-004",
            threat_type="anomaly",
            severity="low",
            evidence_hash="sha256:xxx",
        )
        assert adapter.severity_requires_human(threat) is False

    def test_severity_no_human_for_medium(self) -> None:
        adapter = MockThreatAdapter()
        threat = MockThreat(
            signal_id="thr-005",
            threat_type="anomaly",
            severity="medium",
            evidence_hash="sha256:xxx",
        )
        assert adapter.severity_requires_human(threat) is False

    def test_payload_has_required_fields(self) -> None:
        adapter = MockThreatAdapter()
        threat = MockThreat(
            signal_id="thr-006",
            threat_type="test",
            severity="low",
            evidence_hash="sha256:test",
        )
        payload = adapter.to_bus_payload(threat)
        required = {
            "signal_id",
            "threat_type",
            "severity",
            "evidence_hash",
            "affected_actors",
            "source_project",
        }
        assert required.issubset(payload.keys())


# ---------------------------------------------------------------------------
# EpochAdapter tests
# ---------------------------------------------------------------------------


class TestEpochAdapter:
    def test_domain_roots_returns_dict(self) -> None:
        adapter = MockEpochAdapter()
        roots = adapter.domain_roots()
        assert isinstance(roots, dict)
        assert "mission" in roots
        assert "trust" in roots

    def test_domain_roots_are_sha256(self) -> None:
        adapter = MockEpochAdapter()
        roots = adapter.domain_roots()
        for root in roots.values():
            assert root.startswith("sha256:")
            hex_part = root.split(":")[1]
            assert len(hex_part) == 64  # SHA-256 hex length

    def test_leaf_hashes_known_domain(self) -> None:
        adapter = MockEpochAdapter()
        leaves = adapter.leaf_hashes("mission")
        assert len(leaves) == 2
        assert all(h.startswith("sha256:") for h in leaves)

    def test_leaf_hashes_unknown_domain(self) -> None:
        adapter = MockEpochAdapter()
        leaves = adapter.leaf_hashes("nonexistent")
        assert leaves == []

    def test_domain_roots_deterministic(self) -> None:
        adapter = MockEpochAdapter()
        roots1 = adapter.domain_roots()
        roots2 = adapter.domain_roots()
        assert roots1 == roots2


# ---------------------------------------------------------------------------
# Integration: adapter registration on OpenBrain
# ---------------------------------------------------------------------------


class TestAdapterRegistration:
    def test_register_and_retrieve_event_adapter(self, tmp_path) -> None:
        from unittest import mock

        from open_brain import OpenBrain

        with mock.patch("open_brain.config.CONFIG_DIR", tmp_path):
            ob = OpenBrain(project="adapter_test", agent="cc", db_enabled=False)

        adapter = MockEventAdapter()
        ob.register_adapter("event", adapter)
        retrieved = ob.get_adapter("event")
        assert retrieved is adapter
        assert isinstance(retrieved, EventAdapter)

    def test_register_all_four_adapters(self, tmp_path) -> None:
        from unittest import mock

        from open_brain import OpenBrain

        with mock.patch("open_brain.config.CONFIG_DIR", tmp_path):
            ob = OpenBrain(project="adapter_test2", agent="cc", db_enabled=False)

        ob.register_adapter("event", MockEventAdapter())
        ob.register_adapter("insight", MockInsightAdapter())
        ob.register_adapter("threat", MockThreatAdapter())
        ob.register_adapter("epoch", MockEpochAdapter())

        assert isinstance(ob.get_adapter("event"), EventAdapter)
        assert isinstance(ob.get_adapter("insight"), InsightAdapter)
        assert isinstance(ob.get_adapter("threat"), ThreatAdapter)
        assert isinstance(ob.get_adapter("epoch"), EpochAdapter)

    def test_unregistered_adapter_returns_none(self, tmp_path) -> None:
        from unittest import mock

        from open_brain import OpenBrain

        with mock.patch("open_brain.config.CONFIG_DIR", tmp_path):
            ob = OpenBrain(project="adapter_test3", agent="cc", db_enabled=False)

        assert ob.get_adapter("nonexistent") is None
