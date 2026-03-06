#!/usr/bin/env python3
"""Project-agnostic Instant Messaging Service for multi-agent coordination.

A self-culling, rolling-buffer coordination file for any set of agents working
on a shared project. Each project gets its own IM state file; agents post to
recipient streams and read from their own.

Design:
- JSON state file with fixed-size rolling buffers (max N entries per stream).
- Oldest entries auto-deleted on write — no manual culling needed.
- Tiny reads: entire state is ~50-100 lines of JSON, always.
- Read-only semantics: the script manages the file, never injects into chat.
- File-locked: safe for concurrent agent access.

Usage:
  # Read all streams for a project:
  python3 im_service.py --project my_project read

  # Post to an agent's stream:
  python3 im_service.py --project my_project post agent1 "agent2: API refactor complete."

  # Resync (Open Brain context + IM state):
  python3 im_service.py --project my_project r agent1

  # Set active action:
  python3 im_service.py --project my_project action "IN_PROGRESS" "Refactoring auth module"

  # Clear a stream:
  python3 im_service.py --project my_project clear agent1

  # Initialise fresh state:
  python3 im_service.py --project my_project init

  # Or specify state file directly:
  python3 im_service.py --state-file /path/to/im_state.json read

Config:
  Agent names and state file paths come from projects.json (same file the
  OB bridge uses). Each project entry needs:
    "im_state": "/absolute/path/to/im_state.json"
    "agents": ["agent1", "agent2"]
"""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from filelock import FileLock

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SELF_DIR = Path(__file__).resolve().parent
OB_DIR = SELF_DIR.parent  # OpenBrain/
DEFAULT_CONFIG = SELF_DIR / "projects.json"
MAX_ENTRIES = 20  # Rolling buffer size per stream


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    """Load the projects registry."""
    try:
        data = json.loads(path.read_text())
        return data.get("projects", {})
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Cannot load config {path}: {e}", file=sys.stderr)
        return {}


def resolve_state_file(
    project: str | None,
    state_file: str | None,
    config_path: Path,
) -> tuple[Path, list[str]]:
    """Resolve IM state file path and agent list from args or config.

    Returns (state_path, agent_names).
    """
    if state_file:
        return Path(state_file), []

    if not project:
        print("Error: specify --project <name> or --state-file <path>", file=sys.stderr)
        sys.exit(1)

    config = load_config(config_path)
    proj = config.get(project)
    if not proj:
        available = ", ".join(config.keys()) if config else "(none)"
        print(f"Error: project '{project}' not found. Available: {available}", file=sys.stderr)
        sys.exit(1)

    im_path = proj.get("im_state", "")
    if not im_path:
        print(f"Error: project '{project}' has no 'im_state' path configured", file=sys.stderr)
        sys.exit(1)

    agents = proj.get("agents", [])
    return Path(im_path), agents


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def _make_initial_state(agents: list[str]) -> dict:
    """Build a clean initial state for the given agent list."""
    state: dict = {
        "version": "1.0",
        "protocol": {
            "agents": {a: a for a in agents},
            "max_entries": MAX_ENTRIES,
        },
        "active_action": {
            "status": "IDLE",
            "summary": "No pending action.",
            "updated_utc": None,
        },
    }
    for agent in agents:
        state[agent] = []
    return state


def _ensure_streams(state: dict, agents: list[str]) -> None:
    """Ensure all agent streams exist in state."""
    for agent in agents:
        if agent not in state:
            state[agent] = []


@contextmanager
def _locked_state(
    state_path: Path,
    agents: list[str],
) -> Generator[dict, None, None]:
    """Load state under exclusive file lock, save on exit.

    Prevents write-races when multiple agents call post/action concurrently.
    The lock is held for the entire read-modify-write cycle.
    """
    lock_path = state_path.parent / f"{state_path.name}.lock"
    lock = FileLock(lock_path)

    with lock:
        if state_path.exists():
            with open(state_path) as f:
                state = json.load(f)
        else:
            state = _make_initial_state(agents)
        _ensure_streams(state, agents)
        yield state
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2, default=str)
            f.write("\n")


def _load_readonly(state_path: Path, agents: list[str]) -> dict:
    """Load state for read-only access."""
    lock_path = state_path.parent / f"{state_path.name}.lock"
    lock = FileLock(lock_path)

    with lock:
        if state_path.exists():
            with open(state_path) as f:
                state = json.load(f)
        else:
            state = _make_initial_state(agents)
        _ensure_streams(state, agents)
        return state


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_read(state_path: Path, agents: list[str]) -> None:
    """Read the full IM state (debugging/audit). Use 'recent' for lean reads."""
    state = _load_readonly(state_path, agents)
    print(json.dumps(state, indent=2, default=str))


def cmd_recent(state_path: Path, agents: list[str], n: int = 5) -> None:
    """Read only the last N entries per stream. No protocol metadata.

    This is what agents should use on startup — minimal tokens, maximum signal.
    """
    state = _load_readonly(state_path, agents)
    compact: dict = {
        "active_action": state.get("active_action", {}),
    }
    for agent in agents:
        entries = state.get(agent, [])
        compact[agent] = entries[:n]  # Already newest-first
    print(json.dumps(compact, indent=2, default=str))


def cmd_post(state_path: Path, agents: list[str], stream: str, message: str) -> None:
    """Post a message to an agent's stream. Auto-culls to MAX_ENTRIES."""
    # Validate stream name against known agents (if agents configured)
    if agents and stream not in agents:
        available = ", ".join(agents)
        print(f"Error: stream '{stream}' not in configured agents: {available}", file=sys.stderr)
        sys.exit(1)

    with _locked_state(state_path, agents) as state:
        entry = {
            "ts": _now(),
            "msg": message,
        }
        if stream not in state:
            state[stream] = []
        state[stream].insert(0, entry)  # Newest first

        # Auto-cull: keep only MAX_ENTRIES
        if len(state[stream]) > MAX_ENTRIES:
            state[stream] = state[stream][:MAX_ENTRIES]

        count = len(state[stream])

    print(f"Posted to {stream.upper()} stream ({count}/{MAX_ENTRIES} entries).")


def cmd_action(state_path: Path, agents: list[str], status: str, summary: str) -> None:
    """Set the active action status."""
    with _locked_state(state_path, agents) as state:
        state["active_action"] = {
            "status": status,
            "summary": summary,
            "updated_utc": _now(),
        }
    print(f"Active action set: {status}")


def cmd_clear(state_path: Path, agents: list[str], stream: str) -> None:
    """Clear all entries from a stream or all streams."""
    with _locked_state(state_path, agents) as state:
        if stream == "all":
            for agent in agents:
                if agent in state:
                    state[agent] = []
        elif stream in state:
            state[stream] = []
        else:
            print(f"Warning: stream '{stream}' not found in state", file=sys.stderr)

    print(f"Cleared {stream} stream(s).")


def cmd_init(state_path: Path, agents: list[str]) -> None:
    """Initialise the IM state file (first-time setup or reset)."""
    with _locked_state(state_path, agents) as state:
        fresh = _make_initial_state(agents)
        state.clear()
        state.update(fresh)
    print(f"Initialised IM state at {state_path}")


def cmd_resync(
    state_path: Path,
    agents: list[str],
    agent: str,
    *,
    continue_mode: bool,
    project_root: str = "",
) -> None:
    """Run startup resync: Open Brain status/context, then IM state read.

    Falls back cleanly to IM-only when Open Brain is unavailable.
    """
    print(f"Resync start (agent={agent})")

    cwd = project_root if project_root else str(OB_DIR)

    print("\n=== Open Brain: status ===")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "open_brain.cli", "status"],
            cwd=cwd, check=False, capture_output=True, text=True,
        )
        open_brain_ok = result.returncode == 0
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        if not open_brain_ok and not result.stdout.strip() and not result.stderr.strip():
            print("Open Brain unavailable.")
    except OSError:
        open_brain_ok = False
        print("Open Brain unavailable.")

    print("\n=== Open Brain: session-context ===")
    if open_brain_ok:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "open_brain.cli", "session-context", "--agent", agent],
                cwd=cwd, check=False, capture_output=True, text=True,
            )
            if result.stdout.strip():
                print(result.stdout.strip())
            if result.stderr.strip():
                print(result.stderr.strip(), file=sys.stderr)
            if result.returncode != 0 and not result.stdout.strip() and not result.stderr.strip():
                print("Session context unavailable.")
        except OSError:
            print("Session context unavailable.")
    else:
        print("Skipped (Open Brain status check failed).")

    print("\n=== IM recent (last 5 per stream) ===")
    cmd_recent(state_path, agents, 5)
    if continue_mode:
        print("\nResync complete. Continue.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Project-agnostic IM service for multi-agent coordination",
    )
    parser.add_argument("--project", "-p", type=str, default=None,
                        help="Project name from projects.json")
    parser.add_argument("--state-file", "-s", type=str, default=None,
                        help="Direct path to im_state.json (overrides --project)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help="Path to projects.json")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("read", help="Read full IM state (debug)")

    recent_parser = subparsers.add_parser("recent", help="Last N entries/stream (default 5)")
    recent_parser.add_argument("n", nargs="?", type=int, default=5, help="Entries per stream")

    post_parser = subparsers.add_parser("post", help="Post message to a stream")
    post_parser.add_argument("stream", help="Agent stream name (e.g. cc, cx)")
    post_parser.add_argument("message", help="Message text")

    action_parser = subparsers.add_parser("action", help="Set active action")
    action_parser.add_argument("status", help="Action status (e.g. IN_PROGRESS, IDLE)")
    action_parser.add_argument("summary", help="Action summary")

    clear_parser = subparsers.add_parser("clear", help="Clear a stream")
    clear_parser.add_argument("stream", help="Stream name or 'all'")

    subparsers.add_parser("init", help="Initialise fresh IM state")

    r_parser = subparsers.add_parser("r", help="Resync (OB + IM)")
    r_parser.add_argument("agent", nargs="?", default="cc", help="Agent name")

    rt_parser = subparsers.add_parser("rt", help="Resync + continue")
    rt_parser.add_argument("agent", nargs="?", default="cc", help="Agent name")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    state_path, agents = resolve_state_file(
        args.project, args.state_file, args.config,
    )

    # For projects, also get the root path for OB cwd
    project_root = ""
    if args.project:
        config = load_config(args.config)
        proj = config.get(args.project, {})
        project_root = proj.get("root", "")

    if args.command == "read":
        cmd_read(state_path, agents)
    elif args.command == "recent":
        cmd_recent(state_path, agents, args.n)
    elif args.command == "post":
        cmd_post(state_path, agents, args.stream, args.message)
    elif args.command == "action":
        cmd_action(state_path, agents, args.status, args.summary)
    elif args.command == "clear":
        cmd_clear(state_path, agents, args.stream)
    elif args.command == "init":
        cmd_init(state_path, agents)
    elif args.command in ("r", "rt"):
        cmd_resync(
            state_path, agents, args.agent,
            continue_mode=(args.command == "rt"),
            project_root=project_root,
        )
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
