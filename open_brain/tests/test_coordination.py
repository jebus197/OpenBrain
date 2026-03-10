"""Tests for the coordination package.

All tests are pure in-process — no database, no network, no external state.
Tests the protocol, sequencer, circuit breaker, channel, presence, and bus.
"""

import asyncio
import time

import pytest

from open_brain.coordination.protocol import (
    Envelope,
    MessageType,
    make_envelope,
    sign_envelope,
    verify_envelope_signature,
)
from open_brain.coordination.sequencer import GapRecord, Sequencer
from open_brain.coordination.circuit_breaker import (
    BreakerConfig,
    BreakerRegistry,
    BreakerState,
    CircuitBreaker,
)
from open_brain.coordination.channel import (
    Channel,
    ChannelConfig,
    ChannelMode,
)
from open_brain.coordination.presence import (
    NodeInfo,
    PresenceConfig,
    PresenceManager,
)
from open_brain.coordination.bus import CoordinationBus


def _run(coro):
    """Run an async coroutine synchronously (no pytest-asyncio needed)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Protocol tests
# ---------------------------------------------------------------------------

class TestProtocol:
    def test_make_envelope(self):
        env = make_envelope(
            msg_type=MessageType.MEMORY_CREATED,
            sender="node-abc",
            channel="memory.events",
            payload={"text": "hello"},
            sequence=1,
        )
        assert env.msg_type == "memory.created"
        assert env.sender == "node-abc"
        assert env.channel == "memory.events"
        assert env.sequence == 1
        assert env.content_hash.startswith("sha256:")
        assert env.timestamp_ns > 0
        assert len(env.msg_id) == 36  # UUID

    def test_envelope_content_hash_deterministic(self):
        kwargs = dict(
            msg_type=MessageType.HEARTBEAT,
            sender="node-x",
            channel="system.heartbeat",
            payload={"ts": 1234},
            sequence=5,
        )
        e1 = make_envelope(**kwargs)
        e2 = make_envelope(**kwargs)
        assert e1.content_hash == e2.content_hash

    def test_envelope_different_payload_different_hash(self):
        e1 = make_envelope(
            msg_type="test", sender="n", channel="c",
            payload={"a": 1}, sequence=1,
        )
        e2 = make_envelope(
            msg_type="test", sender="n", channel="c",
            payload={"a": 2}, sequence=1,
        )
        assert e1.content_hash != e2.content_hash

    def test_envelope_to_dict(self):
        env = make_envelope(
            msg_type="test", sender="n", channel="c",
            payload={"k": "v"}, sequence=1,
        )
        d = env.to_dict()
        assert d["msg_type"] == "test"
        assert d["sender"] == "n"
        assert isinstance(d["payload"], dict)

    def test_envelope_from_dict(self):
        env = make_envelope(
            msg_type="test", sender="n", channel="c",
            payload={"k": "v"}, sequence=1,
        )
        d = env.to_dict()
        restored = Envelope.from_dict(d)
        assert restored.msg_id == env.msg_id
        assert restored.content_hash == env.content_hash

    def test_message_type_enum(self):
        assert MessageType.HEARTBEAT == "system.heartbeat"
        assert MessageType.MEMORY_CREATED == "memory.created"
        assert MessageType.THREAT_SIGNAL == "threat.signal"
        assert MessageType.INSIGHT_SIGNAL == "insight.signal"


# ---------------------------------------------------------------------------
# Signing tests (requires nacl — skip if unavailable)
# ---------------------------------------------------------------------------

class TestSigning:
    @pytest.fixture
    def keypair(self):
        try:
            import nacl.signing
        except ImportError:
            pytest.skip("PyNaCl not installed")
        key = nacl.signing.SigningKey.generate()
        return key.encode(), key.verify_key.encode()

    def test_sign_and_verify(self, keypair):
        private, public = keypair
        env = make_envelope(
            msg_type="test", sender="n", channel="c",
            payload={"data": "value"}, sequence=1,
        )
        signed = sign_envelope(env, private)
        assert signed.signature != ""
        assert verify_envelope_signature(signed, public)

    def test_tampered_payload_fails(self, keypair):
        private, public = keypair
        env = make_envelope(
            msg_type="test", sender="n", channel="c",
            payload={"data": "original"}, sequence=1,
        )
        signed = sign_envelope(env, private)

        # Tamper by creating new envelope with different payload but same sig
        tampered = Envelope(
            msg_id=signed.msg_id,
            msg_type=signed.msg_type,
            sender=signed.sender,
            channel=signed.channel,
            sequence=signed.sequence,
            timestamp_ns=signed.timestamp_ns,
            content_hash=signed.content_hash,
            payload={"data": "tampered"},
            signature=signed.signature,
        )
        assert not verify_envelope_signature(tampered, public)


# ---------------------------------------------------------------------------
# Sequencer tests
# ---------------------------------------------------------------------------

class TestSequencer:
    def test_next_starts_at_one(self):
        seq = Sequencer()
        assert seq.next("node-a", "ch1") == 1

    def test_next_increments(self):
        seq = Sequencer()
        assert seq.next("node-a", "ch1") == 1
        assert seq.next("node-a", "ch1") == 2
        assert seq.next("node-a", "ch1") == 3

    def test_independent_streams(self):
        seq = Sequencer()
        assert seq.next("node-a", "ch1") == 1
        assert seq.next("node-b", "ch1") == 1
        assert seq.next("node-a", "ch2") == 1
        assert seq.next("node-a", "ch1") == 2

    def test_current(self):
        seq = Sequencer()
        assert seq.current("node-a", "ch1") == 0
        seq.next("node-a", "ch1")
        assert seq.current("node-a", "ch1") == 1

    def test_check_no_gap(self):
        seq = Sequencer()
        assert seq.check("node-a", "ch1", 1) is None
        assert seq.check("node-a", "ch1", 2) is None

    def test_check_gap_detected(self):
        seq = Sequencer()
        seq.check("node-a", "ch1", 1)
        gap = seq.check("node-a", "ch1", 5)
        assert gap is not None
        assert gap.expected == 2
        assert gap.received == 5
        assert gap.gap_size == 3

    def test_check_duplicate_returns_none(self):
        seq = Sequencer()
        seq.check("node-a", "ch1", 1)
        assert seq.check("node-a", "ch1", 1) is None

    def test_gaps_logged(self):
        seq = Sequencer()
        seq.check("node-a", "ch1", 1)
        seq.check("node-a", "ch1", 5)
        assert len(seq.gaps()) == 1
        assert seq.gaps()[0].gap_size == 3

    def test_clear_gaps(self):
        seq = Sequencer()
        seq.check("node-a", "ch1", 1)
        seq.check("node-a", "ch1", 5)
        cleared = seq.clear_gaps()
        assert cleared == 1
        assert len(seq.gaps()) == 0

    def test_reset(self):
        seq = Sequencer()
        seq.next("node-a", "ch1")
        seq.next("node-a", "ch1")
        seq.reset("node-a", "ch1")
        assert seq.current("node-a", "ch1") == 0
        assert seq.next("node-a", "ch1") == 1

    def test_streams(self):
        seq = Sequencer()
        seq.next("a", "c1")
        seq.next("b", "c2")
        streams = seq.streams()
        assert len(streams) == 2


# ---------------------------------------------------------------------------
# Circuit breaker tests
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_closed_allows(self):
        cb = CircuitBreaker(BreakerConfig())
        assert cb.allow()
        assert cb.state == BreakerState.CLOSED

    def test_errors_trip_breaker(self):
        cfg = BreakerConfig(error_threshold=3, error_window_seconds=60.0)
        cb = CircuitBreaker(cfg)
        for _ in range(3):
            cb.record_error()
        assert cb.state == BreakerState.OPEN
        assert not cb.allow()

    def test_cooldown_transitions_to_half_open(self):
        cfg = BreakerConfig(
            error_threshold=1, cooldown_seconds=0.01,
        )
        cb = CircuitBreaker(cfg)
        cb.record_error()
        assert cb.state == BreakerState.OPEN

        time.sleep(0.02)
        assert cb.allow()
        assert cb.state == BreakerState.HALF_OPEN

    def test_half_open_success_closes(self):
        cfg = BreakerConfig(
            error_threshold=1, cooldown_seconds=0.01, half_open_max=2,
        )
        cb = CircuitBreaker(cfg)
        cb.record_error()
        time.sleep(0.02)

        # Allow half_open_max messages
        assert cb.allow()
        assert cb.allow()
        # Third should transition to CLOSED
        assert cb.allow()
        assert cb.state == BreakerState.CLOSED

    def test_half_open_error_reopens(self):
        cfg = BreakerConfig(
            error_threshold=1, cooldown_seconds=0.01,
        )
        cb = CircuitBreaker(cfg)
        cb.record_error()
        time.sleep(0.02)

        cb.allow()  # Transition to HALF_OPEN
        cb.record_error()  # Should reopen
        assert cb.state == BreakerState.OPEN

    def test_reset(self):
        cfg = BreakerConfig(error_threshold=1)
        cb = CircuitBreaker(cfg)
        cb.record_error()
        assert cb.state == BreakerState.OPEN
        cb.reset()
        assert cb.state == BreakerState.CLOSED
        assert cb.allow()


class TestBreakerRegistry:
    def test_get_creates_on_demand(self):
        reg = BreakerRegistry()
        cb = reg.get("key1")
        assert isinstance(cb, CircuitBreaker)
        assert reg.get("key1") is cb  # Same instance

    def test_allow_delegates(self):
        reg = BreakerRegistry()
        assert reg.allow("key1")

    def test_trip_all(self):
        reg = BreakerRegistry()
        reg.get("a")
        reg.get("b")
        reg.trip_all()
        assert not reg.allow("a")
        assert not reg.allow("b")


# ---------------------------------------------------------------------------
# Channel tests
# ---------------------------------------------------------------------------

class TestChannel:
    @pytest.fixture
    def broadcast_channel(self):
        return Channel("test.broadcast", ChannelConfig(mode=ChannelMode.BROADCAST))

    @pytest.fixture
    def queue_channel(self):
        return Channel("test.queue", ChannelConfig(mode=ChannelMode.QUEUE))

    def test_subscribe_returns_id(self, broadcast_channel):
        async def handler(env): pass
        sub_id = broadcast_channel.subscribe(handler, "node-a")
        assert len(sub_id) == 36  # UUID format

    def test_unsubscribe(self, broadcast_channel):
        async def handler(env): pass
        sub_id = broadcast_channel.subscribe(handler, "node-a")
        assert broadcast_channel.unsubscribe(sub_id)
        assert not broadcast_channel.unsubscribe(sub_id)  # Already removed

    def test_broadcast_delivers_to_all(self, broadcast_channel):
        received = []

        async def h1(env):
            received.append(("h1", env.msg_id))

        async def h2(env):
            received.append(("h2", env.msg_id))

        broadcast_channel.subscribe(h1, "node-a")
        broadcast_channel.subscribe(h2, "node-b")

        env = make_envelope(
            msg_type="test", sender="node-x", channel="test.broadcast",
            payload={}, sequence=1,
        )
        count = _run(broadcast_channel.dispatch(env))
        assert count == 2
        assert len(received) == 2

    def test_queue_delivers_to_one(self, queue_channel):
        received = []

        async def h1(env):
            received.append("h1")

        async def h2(env):
            received.append("h2")

        queue_channel.subscribe(h1, "node-a")
        queue_channel.subscribe(h2, "node-b")

        env = make_envelope(
            msg_type="test", sender="node-x", channel="test.queue",
            payload={}, sequence=1,
        )
        count = _run(queue_channel.dispatch(env))
        assert count == 1
        assert len(received) == 1

    def test_type_filter(self, broadcast_channel):
        received = []

        async def handler(env):
            received.append(env.msg_type)

        broadcast_channel.subscribe(
            handler, "node-a",
            type_filter={"memory.created"},
        )

        env_match = make_envelope(
            msg_type=MessageType.MEMORY_CREATED, sender="n",
            channel="test.broadcast", payload={}, sequence=1,
        )
        env_no_match = make_envelope(
            msg_type=MessageType.HEARTBEAT, sender="n",
            channel="test.broadcast", payload={}, sequence=2,
        )

        _run(broadcast_channel.dispatch(env_match))
        _run(broadcast_channel.dispatch(env_no_match))

        assert received == ["memory.created"]

    def test_trust_gating(self):
        ch = Channel("gated", ChannelConfig(mode=ChannelMode.BROADCAST, min_trust=0.5))
        received = []

        async def handler(env):
            received.append(env.sender)

        ch.subscribe(handler, "node-a")

        def trust_lookup(sender):
            return 0.8 if sender == "trusted" else 0.2

        env_trusted = make_envelope(
            msg_type="test", sender="trusted", channel="gated",
            payload={}, sequence=1,
        )
        env_untrusted = make_envelope(
            msg_type="test", sender="untrusted", channel="gated",
            payload={}, sequence=2,
        )

        _run(ch.dispatch(env_trusted, trust_lookup))
        _run(ch.dispatch(env_untrusted, trust_lookup))

        assert received == ["trusted"]


# ---------------------------------------------------------------------------
# Presence tests
# ---------------------------------------------------------------------------

class TestPresence:
    def test_local_node_registered(self):
        pm = PresenceManager("node-local")
        assert pm.node_count == 1
        node = pm.get_node("node-local")
        assert node is not None
        assert node.is_alive

    def test_record_announce_new_node(self):
        pm = PresenceManager("node-local")
        pm.record_announce("node-remote", capabilities={"search"}, metadata={})
        assert pm.node_count == 2
        remote = pm.get_node("node-remote")
        assert remote.is_alive
        assert "search" in remote.capabilities

    def test_record_heartbeat(self):
        pm = PresenceManager("node-local")
        pm.record_announce("node-remote", capabilities=set(), metadata={})
        old_hb = pm.get_node("node-remote").last_heartbeat_ns
        time.sleep(0.01)
        pm.record_heartbeat("node-remote")
        assert pm.get_node("node-remote").last_heartbeat_ns > old_hb

    def test_record_depart(self):
        pm = PresenceManager("node-local")
        pm.record_announce("node-remote", capabilities=set(), metadata={})
        pm.record_depart("node-remote")
        assert not pm.get_node("node-remote").is_alive

    def test_check_timeouts(self):
        cfg = PresenceConfig(heartbeat_interval_s=0.01, timeout_multiplier=1)
        pm = PresenceManager("node-local", cfg)
        pm.record_announce("node-remote", capabilities=set(), metadata={})

        time.sleep(0.02)
        departed = pm.check_timeouts()
        assert len(departed) == 1
        assert departed[0].node_id == "node-remote"

    def test_nodes_with_capability(self):
        pm = PresenceManager("node-local")
        pm.record_announce("node-a", capabilities={"search", "embed"}, metadata={})
        pm.record_announce("node-b", capabilities={"search"}, metadata={})
        pm.record_announce("node-c", capabilities={"embed"}, metadata={})

        search_nodes = pm.nodes_with_capability("search")
        assert len(search_nodes) == 2

    def test_max_nodes_cap(self):
        cfg = PresenceConfig(max_nodes=3)
        pm = PresenceManager("node-local", cfg)
        pm.record_announce("node-a", capabilities=set(), metadata={})
        pm.record_announce("node-b", capabilities=set(), metadata={})
        # This should be rejected (max_nodes=3, already have 3).
        pm.record_announce("node-c", capabilities=set(), metadata={})
        assert pm.node_count == 3

    def test_on_join_callback(self):
        joined = []
        pm = PresenceManager("node-local")
        pm.on_join(lambda info: joined.append(info.node_id))
        pm.record_announce("node-new", capabilities=set(), metadata={})
        assert "node-new" in joined

    def test_on_depart_callback(self):
        departed = []
        pm = PresenceManager("node-local")
        pm.on_depart(lambda info: departed.append(info.node_id))
        pm.record_announce("node-temp", capabilities=set(), metadata={})
        pm.record_depart("node-temp")
        assert "node-temp" in departed


# ---------------------------------------------------------------------------
# Bus integration tests
# ---------------------------------------------------------------------------

class TestBus:
    def test_publish_and_subscribe(self):
        async def _test():
            bus = CoordinationBus(node_id="test-node")
            received = []

            async def handler(env):
                received.append(env.payload)

            await bus.subscribe("test.channel", handler)
            await bus.publish(
                "test.channel",
                MessageType.MEMORY_CREATED,
                {"text": "hello"},
            )
            assert len(received) == 1
            assert received[0]["text"] == "hello"

        _run(_test())

    def test_publish_returns_envelope(self):
        async def _test():
            bus = CoordinationBus(node_id="test-node")
            env = await bus.publish(
                "test.channel",
                MessageType.MEMORY_CREATED,
                {"text": "hello"},
            )
            assert env is not None
            assert env.sequence == 1
            assert env.sender == "test-node"

        _run(_test())

    def test_circuit_breaker_rejects(self):
        async def _test():
            bus = CoordinationBus(node_id="test-node")
            # Trip the breaker manually via internal stats.
            sender_key = "node:test-node"
            breaker = bus.breakers.get(sender_key)
            breaker._stats.state = BreakerState.OPEN
            breaker._stats.last_trip_time = time.monotonic()

            result = await bus.publish(
                "test.channel",
                MessageType.HEARTBEAT,
                {},
            )
            assert result is None
            assert bus.stats()["rejected_breaker"] > 0

        _run(_test())

    def test_unsubscribe(self):
        async def _test():
            bus = CoordinationBus(node_id="test-node")
            received = []

            async def handler(env):
                received.append(1)

            sub_id = await bus.subscribe("ch", handler)
            await bus.publish("ch", "test", {})
            assert len(received) == 1

            bus.unsubscribe("ch", sub_id)
            await bus.publish("ch", "test", {})
            assert len(received) == 1  # No more deliveries

        _run(_test())

    def test_request_reply(self):
        async def _test():
            bus = CoordinationBus(node_id="test-node")

            async def responder(env):
                if env.correlation_id:
                    await bus.publish(
                        env.channel,
                        MessageType.QUERY_RESPONSE,
                        {"answer": 42},
                        correlation_id=env.correlation_id,
                    )

            await bus.subscribe("query.ch", responder)

            response = await bus.request(
                "query.ch",
                MessageType.QUERY_REQUEST,
                {"question": "meaning"},
                timeout_s=2.0,
            )
            assert response is not None
            assert response.payload["answer"] == 42

        _run(_test())

    def test_request_timeout(self):
        async def _test():
            bus = CoordinationBus(node_id="test-node")
            # No responder — should timeout.
            response = await bus.request(
                "empty.ch",
                MessageType.QUERY_REQUEST,
                {},
                timeout_s=0.05,
            )
            assert response is None

        _run(_test())

    def test_stats(self):
        async def _test():
            bus = CoordinationBus(node_id="test-node")
            await bus.publish("ch", "test", {})
            s = bus.stats()
            assert s["node_id"] == "test-node"
            assert s["published"] >= 1

        _run(_test())

    def test_lifecycle(self):
        async def _test():
            bus = CoordinationBus(node_id="test-node")
            assert not bus.is_running
            await bus.start()
            assert bus.is_running
            await bus.shutdown()
            assert not bus.is_running

        _run(_test())

    def test_system_channels_exist(self):
        bus = CoordinationBus(node_id="test-node")
        assert bus.get_channel("system.heartbeat") is not None
        assert bus.get_channel("system.presence") is not None

    def test_publish_envelope(self):
        async def _test():
            bus = CoordinationBus(node_id="test-node")
            received = []

            async def handler(env):
                received.append(env)

            await bus.subscribe("ch", handler)

            env = make_envelope(
                msg_type="test", sender="remote-node",
                channel="ch", payload={"data": 1}, sequence=1,
            )
            ok = await bus.publish_envelope(env)
            assert ok
            assert len(received) == 1

        _run(_test())

    def test_create_channel_idempotent(self):
        bus = CoordinationBus(node_id="test-node")
        ch1 = bus.create_channel("test.ch")
        ch2 = bus.create_channel("test.ch")
        assert ch1 is ch2

    def test_remove_channel(self):
        bus = CoordinationBus(node_id="test-node")
        bus.create_channel("temp")
        assert bus.remove_channel("temp")
        assert bus.get_channel("temp") is None

    def test_list_channels(self):
        bus = CoordinationBus(node_id="test-node")
        channels = bus.list_channels()
        assert len(channels) >= 2  # system.heartbeat + system.presence
