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
        project: Optional[str] = None,
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
            project=project,
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
        project: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Semantic search across memories."""
        from open_brain import db

        return db.semantic_search(
            query,
            limit=limit,
            area=area,
            memory_type=memory_type,
            source_agent=source_agent,
            project=project,
        )

    def recent(
        self,
        *,
        limit: int = 20,
        area: Optional[str] = None,
        memory_type: Optional[str] = None,
        source_agent: Optional[str] = None,
        project: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List recent memories (newest first)."""
        from open_brain import db

        return db.list_recent(
            limit=limit,
            area=area,
            memory_type=memory_type,
            source_agent=source_agent,
            project=project,
        )

    def pending_tasks(
        self,
        *,
        assigned_to: Optional[str] = None,
        project: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get pending and blocked tasks."""
        from open_brain import db

        return db.get_pending_tasks(assigned_to=assigned_to, project=project)

    def session_context(
        self,
        agent: Optional[str] = None,
        *,
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get composite startup context for an agent.

        Returns pending/blocked tasks, other agents' recent activity,
        last session summary, and last reasoning checkpoint.
        """
        from open_brain import db

        return db.get_session_context(agent or self._agent, project=project)

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
    # Reasoning verification
    # ------------------------------------------------------------------

    def assemble_proof(
        self,
        memory_id: str,
    ) -> Any:
        """Assemble a self-contained proof package for a memory."""
        from open_brain.reasoning import assemble_proof as _assemble_proof

        return _assemble_proof(memory_id)

    def get_reasoning_chain(
        self,
        agent: Optional[str] = None,
        *,
        session_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Retrieve chronological reasoning checkpoints for an agent."""
        from open_brain.reasoning import get_reasoning_chain as _get_chain

        return _get_chain(agent or self._agent, session_id=session_id, limit=limit)

    def verify_reasoning_chain(
        self,
        agent: Optional[str] = None,
        *,
        session_id: Optional[str] = None,
    ) -> Any:
        """Verify a reasoning checkpoint chain (5 checks)."""
        from open_brain.reasoning import verify_reasoning_chain as _verify

        return _verify(agent or self._agent, session_id=session_id)

    def export_reasoning_proof(
        self,
        agent: Optional[str] = None,
        *,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Export a self-contained reasoning proof for third-party verification."""
        from open_brain.reasoning import export_reasoning_proof as _export

        return _export(agent or self._agent, session_id=session_id)

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
