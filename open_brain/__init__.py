"""Open Brain — persistent cross-agent memory for multi-agent AI projects.

Single entry point::

    from open_brain import OpenBrain

    ob = OpenBrain(project="my_project", agent="cc")
    ob.im.post("cc", "Session starting")
    await ob.bus.publish("memory.events", "memory.created", payload)
"""

from __future__ import annotations

__version__ = "1.0.0"

import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class OpenBrain:
    """Unified entry point for Open Brain.

    Subsystems degrade gracefully:
      - **IM** — always available (SQLite, no server needed).
      - **Bus** — always available (in-process asyncio).
      - **Memory** — requires PostgreSQL; ``None`` when absent.
      - **Crypto** — always available (Ed25519 key management).

    Usage::

        ob = OpenBrain(project="project_genesis", agent="cc")

        # IM (always available)
        ob.im.post("cc", "Session starting")
        messages = ob.im.read("cc", limit=10)

        # Bus (always available)
        await ob.bus.publish("memory.events", MessageType.MEMORY_CREATED, payload)

        # Memory (requires PostgreSQL — graceful degradation)
        if ob.memory is not None:
            mem_id = ob.memory.capture("Insight", memory_type="insight")

        # Crypto (always available)
        if ob.crypto.has_keypair():
            sig = ob.crypto.sign(b"data")
    """

    def __init__(
        self,
        project: str = "default",
        agent: str = "system",
        *,
        node_id: Optional[str] = None,
        db_enabled: Optional[bool] = None,
    ) -> None:
        from open_brain import config
        from open_brain.api.crypto_facade import CryptoFacade
        from open_brain.api.im_facade import IMFacade
        from open_brain.api.memory_facade import MemoryFacade
        from open_brain.coordination.bus import CoordinationBus
        from open_brain.im.store import IMStore

        self._project = project
        self._agent = agent
        self._node_id = node_id or config.node_id()
        self._adapters: Dict[str, Any] = {}

        # ---- IM (always available) ----
        im_dir = config.CONFIG_DIR / "im"
        im_dir.mkdir(parents=True, exist_ok=True)
        im_db_path = im_dir / f"{project}.sqlite3"
        self._im_store = IMStore(im_db_path)
        self._im = IMFacade(self._im_store, default_sender=agent)

        # ---- Crypto (always available) ----
        self._crypto = CryptoFacade()

        # ---- Bus (always available) ----
        private_key = self._crypto.private_key_bytes()
        self._bus = CoordinationBus(
            self._node_id,
            private_key_bytes=private_key,
        )

        # ---- Memory (graceful degradation) ----
        self._memory: Optional[MemoryFacade] = None
        if db_enabled is None:
            try:
                from open_brain import db
                db.verify_connection()
                self._memory = MemoryFacade(default_agent=agent)
            except Exception:
                logger.info(
                    "Memory unavailable — no PostgreSQL connection. "
                    "IM and bus still work."
                )
        elif db_enabled:
            from open_brain import db
            db.verify_connection()  # raises if unreachable
            self._memory = MemoryFacade(default_agent=agent)
        # else: db_enabled=False -> memory stays None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def im(self) -> "IMFacade":
        """IM facade — always available."""
        return self._im

    @property
    def bus(self) -> "CoordinationBus":
        """Coordination bus — always available."""
        return self._bus

    @property
    def memory(self) -> Optional["MemoryFacade"]:
        """Memory facade — ``None`` if PostgreSQL is unavailable."""
        return self._memory

    @property
    def crypto(self) -> "CryptoFacade":
        """Crypto facade — always available."""
        return self._crypto

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def project(self) -> str:
        return self._project

    @property
    def agent(self) -> str:
        return self._agent

    @property
    def is_db_available(self) -> bool:
        return self._memory is not None

    # ------------------------------------------------------------------
    # Adapter registration
    # ------------------------------------------------------------------

    def register_adapter(self, name: str, adapter: Any) -> None:
        """Register a project-specific adapter (event, insight, threat, epoch).

        Adapters implement the protocols defined in :mod:`open_brain.adapters`.
        OB never imports project code — projects register adapters at startup.
        """
        self._adapters[name] = adapter

    def get_adapter(self, name: str) -> Optional[Any]:
        """Retrieve a registered adapter by name."""
        return self._adapters.get(name)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the bus: begin heartbeat loop and presence monitoring."""
        await self._bus.start()
        logger.info(
            "OpenBrain started (project=%s, agent=%s, node=%s, db=%s)",
            self._project,
            self._agent,
            self._node_id,
            "yes" if self._memory else "no",
        )

    async def shutdown(self) -> None:
        """Graceful shutdown: stop bus, release resources."""
        await self._bus.shutdown()
        logger.info("OpenBrain shut down (project=%s)", self._project)
