"""Programmatic troubleshooter for Open Brain.

Run: ob-doctor (after pip install) or python3 -m open_brain.troubleshoot

Checks:
  1. Python version and dependencies
  2. PostgreSQL connection
  3. pgvector extension
  4. Database schema (tables, indexes)
  5. Role permissions (reader/writer)
  6. Embedding model availability
  7. Config files
  8. Project registration
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

from open_brain import config

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

BOLD = "\033[1m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
DIM = "\033[2m"
RESET = "\033[0m"

PASS = f"{GREEN}PASS{RESET}"
FAIL = f"{RED}FAIL{RESET}"
WARN = f"{YELLOW}WARN{RESET}"

issues: list[str] = []


def _check(name: str, ok: bool, detail: str = "", fix: str = "") -> bool:
    if ok:
        print(f"  [{PASS}] {name}" + (f" {DIM}({detail}){RESET}" if detail else ""))
    else:
        print(f"  [{FAIL}] {name}" + (f" — {detail}" if detail else ""))
        if fix:
            print(f"         {YELLOW}Fix:{RESET} {fix}")
            issues.append(f"{name}: {fix}")
    return ok


def _warn_check(name: str, detail: str = "", fix: str = "") -> None:
    print(f"  [{WARN}] {name}" + (f" — {detail}" if detail else ""))
    if fix:
        print(f"         {YELLOW}Suggestion:{RESET} {fix}")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_python() -> bool:
    v = sys.version_info
    ok = v >= (3, 9)
    return _check(
        "Python version",
        ok,
        f"{v.major}.{v.minor}.{v.micro}",
        "Python 3.9+ required. Install from python.org or pyenv.",
    )


def check_dependencies() -> bool:
    deps = {
        "psycopg2": "psycopg2-binary",
        "numpy": "numpy",
        "sentence_transformers": "sentence-transformers",
        "mcp": "mcp",
        "pgvector": "pgvector",
    }
    all_ok = True
    for module, package in deps.items():
        try:
            importlib.import_module(module)
            _check(f"Dependency: {package}", True)
        except ImportError:
            _check(
                f"Dependency: {package}",
                False,
                "not installed",
                f"pip install {package}",
            )
            all_ok = False
    return all_ok


def check_postgres() -> bool:
    try:
        result = subprocess.run(
            ["psql", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        version = result.stdout.strip().split()[-1] if result.returncode == 0 else "?"
        ok = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        ok = False
        version = "not found"

    if not _check(
        "PostgreSQL client",
        ok,
        version,
        "Install PostgreSQL. macOS: brew install postgresql@16",
    ):
        return False

    # Check server is running
    try:
        result = subprocess.run(
            ["psql", "-d", "postgres", "-c", "SELECT 1;", "--no-psqlrc", "-q"],
            capture_output=True, text=True, timeout=5,
        )
        return _check(
            "PostgreSQL server",
            result.returncode == 0,
            "running",
            "Start PostgreSQL. macOS: brew services start postgresql@16",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return _check("PostgreSQL server", False, fix="Start PostgreSQL")


def check_pgvector() -> bool:
    try:
        result = subprocess.run(
            ["psql", "-d", "postgres", "-c",
             "SELECT 1 FROM pg_available_extensions WHERE name = 'vector';",
             "--no-psqlrc", "-t", "-q"],
            capture_output=True, text=True, timeout=5,
        )
        ok = result.returncode == 0 and "1" in result.stdout
        return _check(
            "pgvector extension",
            ok,
            fix="Install pgvector. macOS: brew install pgvector. Ubuntu: apt install postgresql-16-pgvector",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return _check("pgvector extension", False, fix="Install pgvector")


def check_database() -> bool:
    try:
        from open_brain import db
        ok = db.verify_connection()
        return _check(
            f"Database '{config.DB_NAME}'",
            ok,
            f"{config.DB_HOST}:{config.DB_PORT}",
            f"Create database: createdb {config.DB_NAME}",
        )
    except Exception as e:
        return _check(f"Database '{config.DB_NAME}'", False, str(e))


def check_schema() -> bool:
    try:
        from open_brain import db
        with db.read_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'memories'
                    ORDER BY ordinal_position
                """)
                cols = [r[0] for r in cur.fetchall()]

        expected = {"id", "raw_text", "embedding", "embedding_model", "metadata", "created_at"}
        ok = expected.issubset(set(cols))
        return _check(
            "Schema: memories table",
            ok,
            f"columns: {', '.join(cols)}" if cols else "table not found",
            "Run ob-setup to create schema",
        )
    except Exception as e:
        return _check("Schema: memories table", False, str(e))


def check_roles() -> bool:
    all_ok = True
    for role, user, password in [
        ("reader", config.DB_READER_USER, config.DB_READER_PASS),
        ("writer", config.DB_WRITER_USER, config.DB_WRITER_PASS),
    ]:
        try:
            import psycopg2
            conn = psycopg2.connect(config.dsn(role))
            conn.close()
            _check(f"Role: {user}", True)
        except Exception as e:
            err = str(e).split("\n")[0]
            _check(
                f"Role: {user}",
                False,
                err,
                f"Run ob-setup to create roles",
            )
            all_ok = False
    return all_ok


def check_embedding_model() -> bool:
    print(f"  [....] Embedding model: {config.EMBEDDING_MODEL_NAME} (loading...)", end="\r")
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
        dim = model.get_sentence_embedding_dimension()
        ok = dim == config.EMBEDDING_DIMENSION
        return _check(
            f"Embedding model",
            ok,
            f"{config.EMBEDDING_MODEL_NAME} ({dim}d)",
            f"Expected {config.EMBEDDING_DIMENSION}d, got {dim}d. Check config.",
        )
    except Exception as e:
        return _check(
            "Embedding model",
            False,
            str(e),
            "pip install sentence-transformers. First run downloads ~130MB model.",
        )


def check_config_files() -> bool:
    all_ok = True

    config_dir = config.CONFIG_DIR
    _check("Config directory", config_dir.is_dir(), str(config_dir),
           f"Run ob-setup or mkdir -p {config_dir}")
    if not config_dir.is_dir():
        all_ok = False

    for name, path in [
        ("config.json", config.CONFIG_FILE),
        ("projects.json", config.PROJECTS_FILE),
    ]:
        if path.exists():
            try:
                data = json.loads(path.read_text())
                _check(f"Config: {name}", True, str(path))
            except json.JSONDecodeError as e:
                _check(f"Config: {name}", False, f"Invalid JSON: {e}")
                all_ok = False
        else:
            _warn_check(f"Config: {name}", "not found (optional)", f"Run ob-setup")

    return all_ok


def check_projects() -> bool:
    agents = config.get_valid_agents()
    if agents:
        _check("Registered agents", True, ", ".join(agents))
        return True
    else:
        _warn_check(
            "Registered agents",
            "none (open mode — any agent name accepted)",
            "Run ob-setup to register a project with agents",
        )
        return True  # Not a failure — open mode is valid


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"\n{BOLD}{CYAN}  Open Brain — Diagnostic Report{RESET}\n")

    sections = [
        ("Environment", [check_python, check_dependencies]),
        ("PostgreSQL", [check_postgres, check_pgvector]),
        ("Database", [check_database, check_schema, check_roles]),
        ("AI Model", [check_embedding_model]),
        ("Configuration", [check_config_files, check_projects]),
    ]

    total_pass = 0
    total_fail = 0

    for section_name, checks in sections:
        print(f"\n  {BOLD}{section_name}{RESET}")
        for check_fn in checks:
            if check_fn():
                total_pass += 1
            else:
                total_fail += 1

    # Summary
    print(f"\n{BOLD}  Summary: {GREEN}{total_pass} passed{RESET}, ", end="")
    if total_fail:
        print(f"{RED}{total_fail} failed{RESET}")
    else:
        print(f"{GREEN}0 failed{RESET}")

    if issues:
        print(f"\n  {BOLD}Fixes needed:{RESET}")
        for i, issue in enumerate(issues, 1):
            print(f"    {i}. {issue}")

    print()

    sys.exit(1 if total_fail else 0)


if __name__ == "__main__":
    main()
