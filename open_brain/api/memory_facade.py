"""Memory facade — project-aware wrapper around db.py functions.

Graceful degradation: if PostgreSQL is unavailable, the ``OpenBrain``
class sets ``memory`` to ``None``.  Callers check
``ob.memory is not None`` before using this facade.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class MemoryFacade:
    """Wrapper around :mod:`open_brain.db` with sane defaults.

    All methods delegate to the db module functions.  The facade adds
    default ``source_agent`` injection and consistent return types.
    """

    def __init__(self, default_agent: str) -> None:
        self._agent = default_agent

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def capture(
        self,
        text: str,
        *,
        memory_type: str,
        area: str = "general",
        source_agent: Optional[str] = None,
        assigned_to: Optional[str] = None,
        action_status: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> str:
        """Capture a memory.  Returns the UUID string."""
        from open_brain import capture as cap

        return cap.capture_memory(
            text=text,
            source_agent=source_agent or self._agent,
            memory_type=memory_type,
            area=area,
            assigned_to=assigned_to,
            action_status=action_status,
            priority=priority,
        )

    def update_task(
        self,
        memory_id: str,
        status: str,
        *,
        agent: Optional[str] = None,
        note: Optional[str] = None,
    ) -> bool:
        """Update a task memory's status.  Returns ``True`` on success."""
        from open_brain import db

        return db.update_task_status(
            memory_id=memory_id,
            new_status=status,
            agent=agent or self._agent,
            note=note,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        area: Optional[str] = None,
        memory_type: Optional[str] = None,
        source_agent: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Semantic search across memories."""
        from open_brain import db

        return db.semantic_search(
            query,
            limit=limit,
            area=area,
            memory_type=memory_type,
            source_agent=source_agent,
        )

    def recent(
        self,
        *,
        limit: int = 20,
        area: Optional[str] = None,
        memory_type: Optional[str] = None,
        source_agent: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List recent memories (newest first)."""
        from open_brain import db

        return db.list_recent(
            limit=limit,
            area=area,
            memory_type=memory_type,
            source_agent=source_agent,
        )

    def pending_tasks(
        self,
        *,
        assigned_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get pending and blocked tasks."""
        from open_brain import db

        return db.get_pending_tasks(assigned_to=assigned_to)

    def session_context(
        self,
        agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get composite startup context for an agent."""
        from open_brain import db

        return db.get_session_context(agent or self._agent)

    def export(
        self,
        path: str,
        *,
        encrypt_passphrase: Optional[str] = None,
    ) -> int:
        """Export memories to JSONL.  Returns count exported."""
        from open_brain import db

        return db.export_memories(path, encrypt_passphrase=encrypt_passphrase)

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Total memory count."""
        from open_brain import db

        return db.memory_count()

    def verify_connection(self) -> bool:
        """Check if the database is reachable."""
        from open_brain import db

        return db.verify_connection()
