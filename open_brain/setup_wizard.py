"""Interactive setup wizard for Open Brain.

Run: ob-setup (after pip install) or python3 -m open_brain.setup_wizard

Walks the user through:
  1. PostgreSQL database setup (creates roles, database, tables, extensions)
  2. Project registration (path, agents, outbox)
  3. Agent wiring (MCP config for Claude Code, CLI aliases for others)
  4. Smoke test (DB connection, capture + search round-trip)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

from open_brain import config

# ---------------------------------------------------------------------------
# Colours (ANSI)
# ---------------------------------------------------------------------------

BOLD = "\033[1m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}OK{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {YELLOW}!!{RESET} {msg}")


def _fail(msg: str) -> None:
    print(f"  {RED}FAIL{RESET} {msg}")


def _header(msg: str) -> None:
    print(f"\n{BOLD}{CYAN}=== {msg} ==={RESET}\n")


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val or default


def _ask_yn(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    val = input(f"  {prompt}{suffix}: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


# ---------------------------------------------------------------------------
# Step 1: PostgreSQL setup
# ---------------------------------------------------------------------------

DB_SCHEMA_SQL = dedent("""\
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS memories (
        id UUID PRIMARY KEY,
        raw_text TEXT NOT NULL,
        embedding vector({dim}),
        embedding_model TEXT NOT NULL DEFAULT '{model}',
        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE INDEX IF NOT EXISTS idx_memories_embedding
        ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
    CREATE INDEX IF NOT EXISTS idx_memories_metadata
        ON memories USING gin (metadata);
    CREATE INDEX IF NOT EXISTS idx_memories_created
        ON memories (created_at DESC);
""")

ROLE_SQL = dedent("""\
    DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{user}') THEN
            CREATE ROLE {user} WITH LOGIN PASSWORD '{password}';
        END IF;
    END $$;
""")

GRANT_READER_SQL = dedent("""\
    GRANT CONNECT ON DATABASE {db} TO {user};
    GRANT USAGE ON SCHEMA public TO {user};
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO {user};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {user};
""")

GRANT_WRITER_SQL = dedent("""\
    GRANT CONNECT ON DATABASE {db} TO {user};
    GRANT USAGE ON SCHEMA public TO {user};
    GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {user};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE ON TABLES TO {user};
""")


def _run_psql(sql: str, dbname: str = "postgres", user: str | None = None) -> tuple[bool, str]:
    """Run SQL via psql. Returns (success, output)."""
    cmd = ["psql", "-d", dbname, "-c", sql, "--no-psqlrc", "-q"]
    if user:
        cmd.extend(["-U", user])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except FileNotFoundError:
        return False, "psql not found — is PostgreSQL installed?"
    except subprocess.TimeoutExpired:
        return False, "psql timed out"


def _check_postgres() -> bool:
    """Check if PostgreSQL is running and accessible."""
    ok, _ = _run_psql("SELECT 1;")
    return ok


def _check_pgvector() -> bool:
    """Check if pgvector extension is available."""
    ok, out = _run_psql("SELECT 1 FROM pg_available_extensions WHERE name = 'vector';")
    return ok and "1" in out


def setup_database() -> bool:
    _header("Step 1: Database Setup")

    if not _check_postgres():
        _fail("Cannot connect to PostgreSQL.")
        print("    Install PostgreSQL and ensure it's running.")
        print("    macOS: brew install postgresql@16 && brew services start postgresql@16")
        print("    Ubuntu: sudo apt install postgresql postgresql-contrib")
        return False
    _ok("PostgreSQL is running")

    if not _check_pgvector():
        _warn("pgvector extension not found. Attempting install...")
        print("    macOS: brew install pgvector")
        print("    Ubuntu: sudo apt install postgresql-16-pgvector")
        if not _ask_yn("Have you installed pgvector? Continue?"):
            return False

    db_name = _ask("Database name", config.DB_NAME)
    db_name_test = f"{db_name}_test"

    # Create databases
    for name in (db_name, db_name_test):
        ok, err = _run_psql(f"CREATE DATABASE {name};")
        if ok:
            _ok(f"Created database '{name}'")
        elif "already exists" in err:
            _ok(f"Database '{name}' already exists")
        else:
            _fail(f"Creating '{name}': {err}")
            return False

    # Create roles
    for target_db in (db_name, db_name_test):
        for user, password, grant_sql in [
            (config.DB_READER_USER, config.DB_READER_PASS, GRANT_READER_SQL),
            (config.DB_WRITER_USER, config.DB_WRITER_PASS, GRANT_WRITER_SQL),
        ]:
            ok, err = _run_psql(ROLE_SQL.format(user=user, password=password))
            if not ok:
                _warn(f"Role '{user}': {err}")
            ok, err = _run_psql(
                grant_sql.format(db=target_db, user=user),
                dbname=target_db,
            )
            if ok:
                _ok(f"Granted {user} on {target_db}")
            else:
                _warn(f"Grants for {user} on {target_db}: {err}")

    # Create tables
    schema_sql = DB_SCHEMA_SQL.format(
        dim=config.EMBEDDING_DIMENSION,
        model=config.EMBEDDING_MODEL_NAME,
    )
    for target_db in (db_name, db_name_test):
        ok, err = _run_psql(schema_sql, dbname=target_db)
        if ok:
            _ok(f"Schema ready in '{target_db}'")
        else:
            _fail(f"Schema in '{target_db}': {err}")
            return False

    return True


# ---------------------------------------------------------------------------
# Step 2: Project registration
# ---------------------------------------------------------------------------

def setup_project() -> dict | None:
    _header("Step 2: Register Your Project")

    project_path = _ask("Project root path", str(Path.cwd()))
    project_path = str(Path(project_path).expanduser().resolve())

    if not Path(project_path).is_dir():
        _fail(f"Directory not found: {project_path}")
        return None

    project_name = _ask("Project name", Path(project_path).name.lower().replace(" ", "_"))

    # Agent detection
    print(f"\n  {BOLD}Agent detection:{RESET}")
    detected = _detect_agents(project_path)
    if detected:
        for agent, source in detected:
            _ok(f"Detected: {agent} ({source})")
    else:
        print("    No agents auto-detected.")

    agents_str = _ask(
        "Agent identifiers (comma-separated)",
        ",".join(a for a, _ in detected) if detected else "agent1",
    )
    agents = [a.strip() for a in agents_str.split(",") if a.strip()]

    # Create outbox for file bridge
    outbox = Path(project_path) / "ob_outbox"
    if _ask_yn(f"Create outbox directory at {outbox}?"):
        outbox.mkdir(parents=True, exist_ok=True)
        _ok(f"Outbox: {outbox}")

    project_data = {
        "root": project_path,
        "outbox": str(outbox),
        "agents": agents,
    }

    # Save to projects.json
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    projects_file = config.PROJECTS_FILE
    existing = {}
    if projects_file.exists():
        try:
            existing = json.loads(projects_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    if "projects" not in existing:
        existing["projects"] = {}
    existing["projects"][project_name] = project_data
    projects_file.write_text(json.dumps(existing, indent=2) + "\n")
    _ok(f"Project '{project_name}' registered in {projects_file}")

    return project_data


def _detect_agents(project_path: str) -> list[tuple[str, str]]:
    """Auto-detect which AI agents are configured for this project."""
    found = []
    root = Path(project_path)

    # Claude Code: .claude/ directory or claude.json
    if (root / ".claude").is_dir() or (root / "claude.json").exists():
        found.append(("cc", "Claude Code (.claude/ dir)"))

    # Claude CoWork / CW handoff directory
    if (root / "cw_handoff").is_dir():
        found.append(("cw", "Claude CoWork (cw_handoff/)"))

    # OpenAI Codex: .codex/ or codex.json
    if (root / ".codex").is_dir() or (root / "codex.json").exists():
        found.append(("cx", "OpenAI Codex (.codex/)"))

    # GitHub Copilot: .github/copilot or copilot-related config
    if (root / ".github" / "copilot").is_dir():
        found.append(("copilot", "GitHub Copilot (.github/copilot/)"))

    # Cursor: .cursor or .cursorrc
    if (root / ".cursor").is_dir() or (root / ".cursorrc").exists():
        found.append(("cursor", "Cursor (.cursor/)"))

    # Windsurf: .windsurf
    if (root / ".windsurf").is_dir():
        found.append(("windsurf", "Windsurf (.windsurf/)"))

    # Aider: .aider.conf.yml
    if (root / ".aider.conf.yml").exists():
        found.append(("aider", "Aider (.aider.conf.yml)"))

    return found


# ---------------------------------------------------------------------------
# Step 3: Agent wiring
# ---------------------------------------------------------------------------

def setup_wiring(project_data: dict) -> None:
    _header("Step 3: Agent Wiring")

    agents = project_data.get("agents", [])
    project_root = project_data.get("root", "")

    # Find the open_brain package
    ob_root = _find_open_brain_root()

    print(f"  {BOLD}MCP wiring (for Claude Code and compatible agents):{RESET}")
    print(f"  Add this to your agent's MCP configuration:\n")
    print(f'  {{"mcpServers": {{"open_brain": {{')
    print(f'    "command": "python3",')
    print(f'    "args": ["-m", "open_brain.mcp_server"],')
    print(f'    "cwd": "{ob_root}"')
    print(f"  }}}}}}")
    print()

    print(f"  {BOLD}CLI wiring (for Codex, Copilot, and other agents):{RESET}")
    print(f"  Add these to agent system prompts or configuration:\n")
    for agent in agents:
        print(f"    # {agent} — startup context:")
        print(f"    python3 -m open_brain.cli session-context --agent {agent}")
        print(f"    # {agent} — capture a memory:")
        print(f"    python3 -m open_brain.cli capture \"text\" --agent {agent} --type insight")
        print()

    print(f"  {BOLD}Shell aliases (optional, add to ~/.zshrc or ~/.bashrc):{RESET}")
    print(f"    alias ob='python3 -m open_brain.cli'")
    print(f"    alias obs='python3 -m open_brain.cli search'")
    print(f"    alias obr='python3 -m open_brain.cli list-recent'")
    print()


def _find_open_brain_root() -> str:
    """Find the root directory containing the open_brain package."""
    # Check if we're running from within the package
    this_file = Path(__file__).resolve()
    candidate = this_file.parent.parent
    if (candidate / "open_brain" / "__init__.py").exists():
        return str(candidate)
    # Fallback: check common locations
    for p in [Path.cwd(), Path.home() / "OpenBrain"]:
        if (p / "open_brain" / "__init__.py").exists():
            return str(p)
    return str(Path.cwd())


# ---------------------------------------------------------------------------
# Step 4: Smoke test
# ---------------------------------------------------------------------------

def run_smoke_test() -> bool:
    _header("Step 4: Smoke Test")

    # Test DB connection
    print("  Testing database connection...")
    try:
        from open_brain import db
        ok = db.verify_connection()
        if ok:
            _ok("Database connection works")
        else:
            _fail("Database connection failed")
            return False
    except Exception as e:
        _fail(f"Database error: {e}")
        return False

    # Test capture + search round-trip
    print("  Testing capture + search round-trip...")
    try:
        from open_brain.capture import capture_memory, embed_text

        mem_id = capture_memory(
            text="Open Brain setup wizard smoke test",
            source_agent="ob_setup",
            memory_type="insight",
            area="general",
        )
        _ok(f"Captured test memory: {mem_id}")

        query_vec = embed_text("smoke test")
        results = db.semantic_search(query_embedding=query_vec, limit=1)
        if results:
            _ok("Semantic search returned results")
        else:
            _warn("Semantic search returned no results (may need more data)")

    except Exception as e:
        _fail(f"Capture/search error: {e}")
        return False

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"\n{BOLD}{CYAN}")
    print("  Open Brain — Setup Wizard")
    print(f"  Persistent cross-agent memory for AI development{RESET}\n")
    print("  This wizard will:")
    print("    1. Set up PostgreSQL (database, roles, schema)")
    print("    2. Register your project (path, agents)")
    print("    3. Show agent wiring instructions")
    print("    4. Run a smoke test\n")

    if not _ask_yn("Ready to begin?"):
        print("  Setup cancelled.")
        return

    # Step 1: Database
    if not setup_database():
        _fail("Database setup failed. Fix the issues above and re-run ob-setup.")
        sys.exit(1)

    # Step 2: Project
    project_data = setup_project()
    if not project_data:
        _fail("Project registration failed.")
        sys.exit(1)

    # Step 3: Wiring
    setup_wiring(project_data)

    # Step 4: Smoke test
    if _ask_yn("Run smoke test now?"):
        if run_smoke_test():
            print(f"\n  {GREEN}{BOLD}Setup complete.{RESET} Open Brain is ready.\n")
        else:
            _warn("Smoke test had issues. Run 'ob-doctor' to diagnose.")
    else:
        print(f"\n  {GREEN}{BOLD}Setup complete.{RESET} Run 'ob-doctor' to verify later.\n")


if __name__ == "__main__":
    main()
