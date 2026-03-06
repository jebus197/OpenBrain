"""Open Brain configuration.

Settings loaded from:
  1. ~/.openbrain/config.json  (user preferences)
  2. ~/.openbrain/projects.json (registered projects)
  3. Environment variables prefixed OPEN_BRAIN_ (override everything)

Agent names are dynamic — defined per-project in projects.json.
Areas have generic defaults but are fully configurable.
"""

import json
import os
from pathlib import Path
from typing import FrozenSet, Set

# ---------------------------------------------------------------------------
# User config directory
# ---------------------------------------------------------------------------

CONFIG_DIR = Path(os.getenv(
    "OPEN_BRAIN_CONFIG_DIR",
    str(Path.home() / ".openbrain"),
))
CONFIG_FILE = CONFIG_DIR / "config.json"
PROJECTS_FILE = CONFIG_DIR / "projects.json"


def _load_json(path: Path) -> dict:
    """Load a JSON file, returning {} on any failure."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


_user_config = _load_json(CONFIG_FILE)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_HOST = os.getenv("OPEN_BRAIN_DB_HOST", _user_config.get("db_host", "localhost"))
DB_PORT = int(os.getenv("OPEN_BRAIN_DB_PORT", _user_config.get("db_port", "5432")))
DB_NAME = os.getenv("OPEN_BRAIN_DB_NAME", _user_config.get("db_name", "open_brain"))

# Role-separated connections (principle of least privilege)
DB_WRITER_USER = os.getenv("OPEN_BRAIN_DB_WRITER_USER", _user_config.get("db_writer_user", "ob_writer"))
DB_WRITER_PASS = os.getenv("OPEN_BRAIN_DB_WRITER_PASS", _user_config.get("db_writer_pass", "ob_writer_local"))
DB_READER_USER = os.getenv("OPEN_BRAIN_DB_READER_USER", _user_config.get("db_reader_user", "ob_reader"))
DB_READER_PASS = os.getenv("OPEN_BRAIN_DB_READER_PASS", _user_config.get("db_reader_pass", "ob_reader_local"))

# Admin connection (for schema setup only — uses current OS user)
DB_ADMIN_USER = os.getenv(
    "OPEN_BRAIN_DB_ADMIN_USER",
    os.getenv("USER") or os.getenv("USERNAME") or "postgres",
)
DB_ADMIN_PASS = os.getenv("OPEN_BRAIN_DB_ADMIN_PASS", "")


def dsn(role: str = "reader") -> str:
    """Build a libpq connection string for the given role."""
    if role == "writer":
        user, password = DB_WRITER_USER, DB_WRITER_PASS
    elif role == "admin":
        user, password = DB_ADMIN_USER, DB_ADMIN_PASS
    else:
        user, password = DB_READER_USER, DB_READER_PASS

    parts = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={user}"
    if password:
        parts += f" password={password}"
    return parts


# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------

EMBEDDING_MODEL_NAME = _user_config.get("embedding_model", "BAAI/bge-small-en-v1.5")
EMBEDDING_DIMENSION = int(_user_config.get("embedding_dimension", 384))

# ---------------------------------------------------------------------------
# Payload throttling
# ---------------------------------------------------------------------------

TOKEN_BUDGET = int(os.getenv("OPEN_BRAIN_TOKEN_BUDGET", _user_config.get("token_budget", "2000")))


def estimate_tokens(text: str) -> int:
    """Rough token count — word-count * 1.3. No external dependency."""
    return int(len(text.split()) * 1.3)


# ---------------------------------------------------------------------------
# Agents (dynamic — loaded from registered projects)
# ---------------------------------------------------------------------------


def _load_registered_agents() -> FrozenSet[str]:
    """Build agent set from all registered projects + global config."""
    projects_data = _load_json(PROJECTS_FILE)
    agents: Set[str] = set()
    for proj in projects_data.get("projects", {}).values():
        agents.update(proj.get("agents", []))
    # Also include any globally defined agents
    agents.update(_user_config.get("agents", []))
    return frozenset(agents)


REGISTERED_AGENTS = _load_registered_agents()


def is_valid_agent(name: str) -> bool:
    """Check if an agent name is acceptable.

    If agents are registered, validates against them.
    Otherwise accepts any reasonable string (alphanumeric + underscore, 1-30 chars).
    """
    if REGISTERED_AGENTS:
        return name in REGISTERED_AGENTS
    # Open mode: accept any sane identifier
    return bool(name) and len(name) <= 30 and all(
        c.isalnum() or c in "_-" for c in name
    )


def get_valid_agents() -> list:
    """Return sorted list of registered agents, or empty if open mode."""
    return sorted(REGISTERED_AGENTS) if REGISTERED_AGENTS else []


# ---------------------------------------------------------------------------
# Memory types (fixed — these are structural, not project-specific)
# ---------------------------------------------------------------------------

VALID_MEMORY_TYPES = frozenset({
    "decision",
    "task",
    "session_summary",
    "insight",
    "blocker",
    "review",
    "handoff",
})

VALID_ACTION_STATUSES = frozenset({
    "pending",
    "in_progress",
    "blocked",
    "completed",
    "cancelled",
})

# ---------------------------------------------------------------------------
# Areas (configurable — generic software engineering defaults)
# ---------------------------------------------------------------------------

DEFAULT_AREAS = frozenset({
    "general",
    "backend",
    "frontend",
    "api",
    "database",
    "infra",
    "testing",
    "security",
    "devops",
    "ux",
    "docs",
    "ops",
})

VALID_AREAS = frozenset(
    _user_config.get("areas", DEFAULT_AREAS)
)
