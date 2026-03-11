"""Capture pipeline — validate, sanitise, embed, store."""

from typing import Any, Dict, Optional

from open_brain import config
from open_brain.sanitise import sanitise
from open_brain import db

# ---------------------------------------------------------------------------
# Lazy-loaded embedding model (~130 MB, 2-3s first load)
# ---------------------------------------------------------------------------

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
    return _model


def embed_text(text: str) -> list:
    """Embed text and return a list of 384 floats (normalised)."""
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


# ---------------------------------------------------------------------------
# Main capture function
# ---------------------------------------------------------------------------


class CaptureError(ValueError):
    """Raised when capture validation fails."""


def capture_memory(
    text: str,
    source_agent: str,
    memory_type: str,
    area: str = "general",
    action_status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    priority: Optional[str] = None,
    project: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Full capture pipeline: validate -> sanitise -> embed -> store.

    Returns the UUID of the stored memory.
    """
    # Validate enums
    if not config.is_valid_agent(source_agent):
        agents = config.get_valid_agents()
        hint = f" Must be one of: {agents}" if agents else " Must be alphanumeric, 1-30 chars."
        raise CaptureError(f"Invalid source_agent '{source_agent}'.{hint}")
    if memory_type not in config.VALID_MEMORY_TYPES:
        raise CaptureError(
            f"Invalid memory_type '{memory_type}'. "
            f"Must be one of: {sorted(config.VALID_MEMORY_TYPES)}"
        )
    if area not in config.VALID_AREAS:
        raise CaptureError(
            f"Invalid area '{area}'. "
            f"Must be one of: {sorted(config.VALID_AREAS)}"
        )
    if action_status and action_status not in config.VALID_ACTION_STATUSES:
        raise CaptureError(
            f"Invalid action_status '{action_status}'. "
            f"Must be one of: {sorted(config.VALID_ACTION_STATUSES)}"
        )
    if assigned_to and assigned_to != "all" and not config.is_valid_agent(assigned_to):
        agents = config.get_valid_agents()
        hint = f" Must be one of: {agents + ['all']}" if agents else ""
        raise CaptureError(f"Invalid assigned_to '{assigned_to}'.{hint}")

    # Tasks must have action_status
    if memory_type == "task" and not action_status:
        raise CaptureError("Tasks require an action_status")

    # Sanitise
    cleaned = sanitise(text)

    # Build metadata
    metadata: Dict[str, Any] = {
        "source_agent": source_agent,
        "memory_type": memory_type,
        "area": area,
        "node_id": config.node_id(),
    }
    if action_status:
        metadata["action_status"] = action_status
    if assigned_to:
        metadata["assigned_to"] = assigned_to
    if priority:
        metadata["priority"] = priority
    if project:
        metadata["project"] = project
    if extra_metadata:
        metadata.update(extra_metadata)

    # Embed
    embedding = embed_text(cleaned)

    # Store (content_hash and previous_hash computed by db.insert_memory)
    return db.insert_memory(
        raw_text=cleaned,
        embedding=embedding,
        metadata=metadata,
    )
