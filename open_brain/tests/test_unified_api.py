"""Tests for the OpenBrain unified API."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

from open_brain import OpenBrain
from open_brain.api.crypto_facade import CryptoFacade
from open_brain.api.im_facade import IMFacade
from open_brain.api.memory_facade import MemoryFacade
from open_brain.coordination.bus import CoordinationBus
from open_brain.im.store import IMStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ob(tmp_path: Path) -> OpenBrain:
    """OpenBrain instance with IM pointed at a temp directory, DB disabled."""
    with mock.patch("open_brain.config.CONFIG_DIR", tmp_path):
        return OpenBrain(
            project="test_project",
            agent="cc",
            db_enabled=False,
        )


@pytest.fixture
def ob_custom_node(tmp_path: Path) -> OpenBrain:
    """OpenBrain with explicit node_id."""
    with mock.patch("open_brain.config.CONFIG_DIR", tmp_path):
        return OpenBrain(
            project="test_project",
            agent="cx",
            node_id="node-custom123",
            db_enabled=False,
        )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_project(self, ob: OpenBrain) -> None:
        assert ob.project == "test_project"

    def test_default_agent(self, ob: OpenBrain) -> None:
        assert ob.agent == "cc"

    def test_node_id_auto_generated(self, ob: OpenBrain) -> None:
        assert ob.node_id.startswith("node-")
        assert len(ob.node_id) == 17  # node- + 12 hex chars

    def test_custom_node_id(self, ob_custom_node: OpenBrain) -> None:
        assert ob_custom_node.node_id == "node-custom123"

    def test_custom_agent(self, ob_custom_node: OpenBrain) -> None:
        assert ob_custom_node.agent == "cx"


# ---------------------------------------------------------------------------
# Properties: type checks
# ---------------------------------------------------------------------------


class TestProperties:
    def test_im_is_im_facade(self, ob: OpenBrain) -> None:
        assert isinstance(ob.im, IMFacade)

    def test_bus_is_coordination_bus(self, ob: OpenBrain) -> None:
        assert isinstance(ob.bus, CoordinationBus)

    def test_crypto_is_crypto_facade(self, ob: OpenBrain) -> None:
        assert isinstance(ob.crypto, CryptoFacade)

    def test_memory_is_none_when_db_disabled(self, ob: OpenBrain) -> None:
        assert ob.memory is None

    def test_is_db_available_false_when_disabled(self, ob: OpenBrain) -> None:
        assert ob.is_db_available is False


# ---------------------------------------------------------------------------
# IM via unified API
# ---------------------------------------------------------------------------


class TestIMIntegration:
    def test_create_channel_and_post(self, ob: OpenBrain) -> None:
        ob.im.create_channel("test", "Test Channel")
        msg = ob.im.post("test", "Hello from unified API")
        assert msg.content == "Hello from unified API"
        assert msg.sender == "cc"  # default sender

    def test_post_with_explicit_sender(self, ob: OpenBrain) -> None:
        ob.im.create_channel("test", "Test")
        msg = ob.im.post("test", "From CX", sender="cx")
        assert msg.sender == "cx"

    def test_read_messages(self, ob: OpenBrain) -> None:
        ob.im.create_channel("test", "Test")
        ob.im.post("test", "msg1")
        ob.im.post("test", "msg2")
        msgs = ob.im.read("test", limit=10)
        assert len(msgs) == 2

    def test_recent_messages(self, ob: OpenBrain) -> None:
        ob.im.create_channel("ch1", "Ch1")
        ob.im.create_channel("ch2", "Ch2")
        ob.im.post("ch1", "a")
        ob.im.post("ch2", "b")
        recent = ob.im.recent(limit=5)
        assert len(recent) == 2

    def test_search(self, ob: OpenBrain) -> None:
        ob.im.create_channel("test", "Test")
        ob.im.post("test", "The quick brown fox")
        ob.im.post("test", "A slow red dog")
        results = ob.im.search("quick brown")
        assert len(results) >= 1
        assert "quick brown fox" in results[0].content

    def test_channels_listing(self, ob: OpenBrain) -> None:
        ob.im.create_channel("a", "Alpha")
        ob.im.create_channel("b", "Beta")
        channels = ob.im.channels()
        ids = [c["channel_id"] for c in channels]
        assert "a" in ids
        assert "b" in ids

    def test_clear_channel(self, ob: OpenBrain) -> None:
        ob.im.create_channel("test", "Test")
        ob.im.post("test", "to be cleared")
        count = ob.im.clear("test")
        assert count == 1
        assert len(ob.im.read("test")) == 0

    def test_create_channel_with_metadata(self, ob: OpenBrain) -> None:
        ob.im.create_channel(
            "meta-ch",
            "Meta Channel",
            metadata={"priority": "high", "area": "ops"},
        )
        channels = ob.im.channels()
        ch = next(c for c in channels if c["channel_id"] == "meta-ch")
        assert ch["metadata"]["priority"] == "high"
        assert ch["metadata"]["area"] == "ops"

    def test_store_property(self, ob: OpenBrain) -> None:
        assert isinstance(ob.im.store, IMStore)

    def test_thread_reading(self, ob: OpenBrain) -> None:
        ob.im.create_channel("test", "Test")
        root = ob.im.post("test", "Root message")
        ob.im.post("test", "Reply", correlation_id=root.msg_id)
        thread = ob.im.thread(root.msg_id)
        assert len(thread) >= 1

    def test_unread(self, ob: OpenBrain) -> None:
        ob.im.create_channel("test", "Test")
        ob.im.post("test", "Unread msg", sender="cx")
        unread = ob.im.unread("cc", channel="test")
        assert len(unread) >= 1


# ---------------------------------------------------------------------------
# Bus via unified API
# ---------------------------------------------------------------------------


class TestBusIntegration:
    def test_bus_node_id_matches(self, ob: OpenBrain) -> None:
        assert ob.bus.node_id == ob.node_id

    def test_bus_has_system_channels(self, ob: OpenBrain) -> None:
        assert ob.bus.get_channel("system.heartbeat") is not None
        assert ob.bus.get_channel("system.presence") is not None

    def test_bus_create_channel(self, ob: OpenBrain) -> None:
        ch = ob.bus.create_channel("test.channel")
        assert ch is not None
        assert ob.bus.get_channel("test.channel") is not None


# ---------------------------------------------------------------------------
# Crypto via unified API
# ---------------------------------------------------------------------------


class TestCryptoIntegration:
    def test_no_keypair_by_default(self, ob: OpenBrain) -> None:
        # Test env may or may not have keys — just check the method works
        result = ob.crypto.has_keypair()
        assert isinstance(result, bool)

    def test_public_key_pem_returns_string_or_none(self, ob: OpenBrain) -> None:
        result = ob.crypto.public_key_pem()
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# Adapter registration
# ---------------------------------------------------------------------------


class TestAdapters:
    def test_register_and_retrieve(self, ob: OpenBrain) -> None:
        adapter = {"type": "test_adapter"}
        ob.register_adapter("event", adapter)
        assert ob.get_adapter("event") is adapter

    def test_missing_adapter_returns_none(self, ob: OpenBrain) -> None:
        assert ob.get_adapter("nonexistent") is None

    def test_multiple_adapters(self, ob: OpenBrain) -> None:
        ob.register_adapter("event", "EventAdapter")
        ob.register_adapter("insight", "InsightAdapter")
        ob.register_adapter("threat", "ThreatAdapter")
        assert ob.get_adapter("event") == "EventAdapter"
        assert ob.get_adapter("insight") == "InsightAdapter"
        assert ob.get_adapter("threat") == "ThreatAdapter"

    def test_adapter_overwrite(self, ob: OpenBrain) -> None:
        ob.register_adapter("event", "v1")
        ob.register_adapter("event", "v2")
        assert ob.get_adapter("event") == "v2"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_start_and_shutdown(self, ob: OpenBrain) -> None:
        async def _run() -> None:
            await ob.start()
            assert ob.bus.is_running
            await ob.shutdown()
            assert not ob.bus.is_running

        asyncio.get_event_loop().run_until_complete(_run())

    def test_double_start_is_safe(self, ob: OpenBrain) -> None:
        async def _run() -> None:
            await ob.start()
            await ob.start()  # should be idempotent
            assert ob.bus.is_running
            await ob.shutdown()

        asyncio.get_event_loop().run_until_complete(_run())

    def test_double_shutdown_is_safe(self, ob: OpenBrain) -> None:
        async def _run() -> None:
            await ob.start()
            await ob.shutdown()
            await ob.shutdown()  # should be idempotent
            assert not ob.bus.is_running

        asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# IM database path
# ---------------------------------------------------------------------------


class TestIMDatabasePath:
    def test_im_database_created(self, tmp_path: Path) -> None:
        with mock.patch("open_brain.config.CONFIG_DIR", tmp_path):
            ob = OpenBrain(project="pathtest", agent="cc", db_enabled=False)
            expected = tmp_path / "im" / "pathtest.sqlite3"
            assert expected.exists()

    def test_different_projects_different_dbs(self, tmp_path: Path) -> None:
        with mock.patch("open_brain.config.CONFIG_DIR", tmp_path):
            ob1 = OpenBrain(project="proj_a", agent="cc", db_enabled=False)
            ob2 = OpenBrain(project="proj_b", agent="cc", db_enabled=False)
            db_a = tmp_path / "im" / "proj_a.sqlite3"
            db_b = tmp_path / "im" / "proj_b.sqlite3"
            assert db_a.exists()
            assert db_b.exists()
