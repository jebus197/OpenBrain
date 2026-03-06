"""Database layer for Open Brain.

Role-separated connections: read queries use ob_reader, writes use ob_writer.
All queries are parameterised (no string interpolation of user data).
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import json
import uuid

import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector

from open_brain import config

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

psycopg2.extras.register_uuid()


@contextmanager
def read_conn():
    """Context manager for a read-only database connection."""
    conn = psycopg2.connect(config.dsn("reader"))
    register_vector(conn)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def write_conn():
    """Context manager for a read-write database connection."""
    conn = psycopg2.connect(config.dsn("writer"))
    register_vector(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


def insert_memory(
    raw_text: str,
    embedding: list,
    metadata: Dict[str, Any],
    embedding_model: str = config.EMBEDDING_MODEL_NAME,
) -> str:
    """Insert a memory and return its UUID as a string."""
    import numpy as np

    vec = np.array(embedding, dtype=np.float32)
    mem_id = str(uuid.uuid4())

    with write_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memories (id, raw_text, embedding, embedding_model, metadata)
                VALUES (%s, %s, %s::vector, %s, %s)
                """,
                (mem_id, raw_text, vec, embedding_model, json.dumps(metadata)),
            )
    return mem_id


def update_task_status(
    memory_id: str,
    new_status: str,
    agent: str,
    note: Optional[str] = None,
) -> bool:
    """Update the action_status of a task memory via JSONB merge.

    Returns True if the row was updated, False if not found.
    """
    patch = {
        "action_status": new_status,
        "completed_by": agent,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    if note:
        patch["status_note"] = note

    with write_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE memories
                SET metadata = metadata || %s::jsonb
                WHERE id = %s
                  AND metadata->>'memory_type' = 'task'
                RETURNING id
                """,
                (json.dumps(patch), memory_id),
            )
            return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


def semantic_search(
    query_embedding: list,
    limit: int = 10,
    source_agent: Optional[str] = None,
    memory_type: Optional[str] = None,
    area: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Cosine-distance search with optional metadata pre-filtering."""
    import numpy as np

    vec = np.array(query_embedding, dtype=np.float32)

    conditions = []
    params: list = [vec]

    if source_agent:
        conditions.append("metadata->>'source_agent' = %s")
        params.append(source_agent)
    if memory_type:
        conditions.append("metadata->>'memory_type' = %s")
        params.append(memory_type)
    if area:
        conditions.append("metadata->>'area' = %s")
        params.append(area)

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    with read_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, raw_text, metadata, created_at,
                       (embedding <=> %s::vector) AS distance
                FROM memories
                {where_sql}
                ORDER BY distance ASC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()

    return [_row_to_dict(r) for r in rows]


def list_recent(
    limit: int = 20,
    source_agent: Optional[str] = None,
    memory_type: Optional[str] = None,
    area: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List recent memories, newest first, with optional filters."""
    conditions = []
    params: list = []

    if source_agent:
        conditions.append("metadata->>'source_agent' = %s")
        params.append(source_agent)
    if memory_type:
        conditions.append("metadata->>'memory_type' = %s")
        params.append(memory_type)
    if area:
        conditions.append("metadata->>'area' = %s")
        params.append(area)

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    with read_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, raw_text, metadata, created_at
                FROM memories
                {where_sql}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()

    return [_row_to_dict(r) for r in rows]


def get_pending_tasks(
    assigned_to: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get tasks with action_status in ('pending', 'blocked').

    If assigned_to is given, returns tasks assigned to that agent OR 'all'.
    """
    conditions = [
        "metadata->>'memory_type' = 'task'",
        "metadata->>'action_status' IN ('pending', 'blocked')",
    ]
    params: list = []

    if assigned_to:
        conditions.append(
            "(metadata->>'assigned_to' = %s OR metadata->>'assigned_to' = 'all')"
        )
        params.append(assigned_to)

    where_sql = "WHERE " + " AND ".join(conditions)

    with read_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, raw_text, metadata, created_at
                FROM memories
                {where_sql}
                ORDER BY created_at DESC
                LIMIT 50
                """,
                params,
            )
            rows = cur.fetchall()

    return [_row_to_dict(r) for r in rows]


def get_session_context(agent: str) -> Dict[str, Any]:
    """Composite context for an agent starting a session.

    Returns:
        {
            "pending_tasks": [...],
            "blocked_tasks": [...],
            "other_agents_recent": [...],
            "last_session_summary": {...} or None,
        }
    """
    result: Dict[str, Any] = {
        "pending_tasks": [],
        "blocked_tasks": [],
        "other_agents_recent": [],
        "last_session_summary": None,
    }

    with read_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Discover other agents — use registry if available, else query DB
            if config.REGISTERED_AGENTS:
                other_agents = [a for a in config.REGISTERED_AGENTS if a != agent]
            else:
                cur.execute(
                    """
                    SELECT DISTINCT metadata->>'source_agent' AS agent
                    FROM memories
                    WHERE metadata->>'source_agent' IS NOT NULL
                      AND metadata->>'source_agent' != %s
                    """,
                    (agent,),
                )
                other_agents = [r["agent"] for r in cur.fetchall()]

            # 1. Pending tasks for this agent or 'all'
            cur.execute(
                """
                SELECT id, raw_text, metadata, created_at
                FROM memories
                WHERE metadata->>'memory_type' = 'task'
                  AND metadata->>'action_status' = 'pending'
                  AND (metadata->>'assigned_to' = %s OR metadata->>'assigned_to' = 'all')
                ORDER BY created_at DESC
                LIMIT 20
                """,
                (agent,),
            )
            result["pending_tasks"] = [_row_to_dict(r) for r in cur.fetchall()]

            # 2. All blocked tasks
            cur.execute(
                """
                SELECT id, raw_text, metadata, created_at
                FROM memories
                WHERE metadata->>'memory_type' = 'task'
                  AND metadata->>'action_status' = 'blocked'
                ORDER BY created_at DESC
                LIMIT 20
                """,
            )
            result["blocked_tasks"] = [_row_to_dict(r) for r in cur.fetchall()]

            # 3. Last 5 from each other agent
            for other in other_agents:
                cur.execute(
                    """
                    SELECT id, raw_text, metadata, created_at
                    FROM memories
                    WHERE metadata->>'source_agent' = %s
                    ORDER BY created_at DESC
                    LIMIT 5
                    """,
                    (other,),
                )
                result["other_agents_recent"].extend(
                    [_row_to_dict(r) for r in cur.fetchall()]
                )

            # 4. Most recent session_summary from this agent
            cur.execute(
                """
                SELECT id, raw_text, metadata, created_at
                FROM memories
                WHERE metadata->>'source_agent' = %s
                  AND metadata->>'memory_type' = 'session_summary'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (agent,),
            )
            row = cur.fetchone()
            if row:
                result["last_session_summary"] = _row_to_dict(row)

    return result


def verify_connection() -> bool:
    """Smoke test — returns True if the DB is reachable."""
    try:
        with read_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone()[0] == 1
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a RealDictRow to a plain dict with serialisable types."""
    d = dict(row)
    if "id" in d:
        d["id"] = str(d["id"])
    if "created_at" in d:
        d["created_at"] = d["created_at"].isoformat()
    if "distance" in d:
        d["distance"] = float(d["distance"])
    # metadata is already a dict from JSONB
    return d
