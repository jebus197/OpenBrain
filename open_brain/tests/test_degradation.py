"""Tests for graceful degradation — OpenBrain works without PostgreSQL."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest import mock

import pytest

from open_brain import OpenBrain


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ob_no_db(tmp_path: Path) -> OpenBrain:
    """OpenBrain with DB explicitly disabled."""
    with mock.patch("open_brain.config.CONFIG_DIR", tmp_path):
        return OpenBrain(project="degrade", agent="cc", db_enabled=False)


# ---------------------------------------------------------------------------
# Core degradation: no PostgreSQL
# ---------------------------------------------------------------------------


class TestNoPostgres:
    def test_memory_is_none(self, ob_no_db: OpenBrain) -> None:
        assert ob_no_db.memory is None

    def test_is_db_available_false(self, ob_no_db: OpenBrain) -> None:
        assert ob_no_db.is_db_available is False

    def test_im_still_works(self, ob_no_db: OpenBrain) -> None:
        ob_no_db.im.create_channel("test", "Test")
        msg = ob_no_db.im.post("test", "Works without PostgreSQL")
        assert msg.content == "Works without PostgreSQL"
        msgs = ob_no_db.im.read("test")
        assert len(msgs) == 1

    def test_bus_still_works(self, ob_no_db: OpenBrain) -> None:
        assert ob_no_db.bus is not None
        assert ob_no_db.bus.node_id == ob_no_db.node_id

    def test_crypto_still_works(self, ob_no_db: OpenBrain) -> None:
        result = ob_no_db.crypto.has_keypair()
        assert isinstance(result, bool)

    def test_bus_lifecycle_without_db(self, ob_no_db: OpenBrain) -> None:
        async def _run() -> None:
            await ob_no_db.start()
            assert ob_no_db.bus.is_running
            await ob_no_db.shutdown()
            assert not ob_no_db.bus.is_running

        asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# Auto-detect degradation (db_enabled=None)
# ---------------------------------------------------------------------------


class TestAutoDetect:
    def test_auto_detect_no_postgres(self, tmp_path: Path) -> None:
        """When db_enabled is None and PostgreSQL is unreachable, memory=None."""
        with (
            mock.patch("open_brain.config.CONFIG_DIR", tmp_path),
            mock.patch(
                "open_brain.db.verify_connection",
                side_effect=Exception("Connection refused"),
            ),
        ):
            ob = OpenBrain(project="autodetect", agent="cc", db_enabled=None)
            assert ob.memory is None
            # But IM still works
            ob.im.create_channel("test", "Test")
            msg = ob.im.post("test", "Auto-detect fallback works")
            assert msg.content == "Auto-detect fallback works"

    def test_auto_detect_with_mock_postgres(self, tmp_path: Path) -> None:
        """When db_enabled is None and PostgreSQL IS reachable, memory is set."""
        with (
            mock.patch("open_brain.config.CONFIG_DIR", tmp_path),
            mock.patch("open_brain.db.verify_connection", return_value=True),
        ):
            ob = OpenBrain(project="autodetect2", agent="cc", db_enabled=None)
            assert ob.memory is not None
            assert ob.is_db_available is True


# ---------------------------------------------------------------------------
# Explicit db_enabled=True with no PostgreSQL
# ---------------------------------------------------------------------------


class TestExplicitDBEnabled:
    def test_raises_when_db_required_but_absent(self, tmp_path: Path) -> None:
        """db_enabled=True should raise if PostgreSQL is unreachable."""
        with (
            mock.patch("open_brain.config.CONFIG_DIR", tmp_path),
            mock.patch(
                "open_brain.db.verify_connection",
                side_effect=Exception("Connection refused"),
            ),
            pytest.raises(Exception, match="Connection refused"),
        ):
            OpenBrain(project="mustfail", agent="cc", db_enabled=True)


# ---------------------------------------------------------------------------
# No keypair: messages posted unsigned
# ---------------------------------------------------------------------------


class TestNoKeypair:
    def test_post_without_keypair_succeeds(self, ob_no_db: OpenBrain) -> None:
        """IM posts should work even when no Ed25519 keypair exists."""
        ob_no_db.im.create_channel("test", "Test")
        msg = ob_no_db.im.post("test", "Unsigned message")
        assert msg.signature is None
        assert msg.content_hash  # content hash is always present

    def test_bus_works_without_keypair(self, ob_no_db: OpenBrain) -> None:
        """Bus should operate without a signing key."""
        async def _run() -> None:
            received = []

            async def handler(env):
                received.append(env)

            await ob_no_db.bus.subscribe("test.ch", handler)
            env = await ob_no_db.bus.publish(
                "test.ch", "test.event", {"data": "value"}
            )
            assert env is not None
            # Give dispatch a moment
            await asyncio.sleep(0.01)
            assert len(received) == 1

        asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# Multiple subsystem interactions
# ---------------------------------------------------------------------------


class TestCrossSubsystem:
    def test_im_and_bus_both_work(self, ob_no_db: OpenBrain) -> None:
        """IM and bus should operate independently."""
        # IM
        ob_no_db.im.create_channel("im_test", "IM Test")
        ob_no_db.im.post("im_test", "IM message")
        msgs = ob_no_db.im.read("im_test")
        assert len(msgs) == 1

        # Bus
        async def _bus_test() -> None:
            ch = ob_no_db.bus.create_channel("bus_test")
            assert ch is not None

        asyncio.get_event_loop().run_until_complete(_bus_test())

    def test_adapters_work_without_db(self, ob_no_db: OpenBrain) -> None:
        """Adapter registration is independent of DB state."""
        ob_no_db.register_adapter("event", {"type": "mock_event"})
        assert ob_no_db.get_adapter("event") is not None
        assert ob_no_db.memory is None  # DB still not available
