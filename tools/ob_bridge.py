#!/usr/bin/env python3
"""Open Brain file-based bridge — project-agnostic.

Polls outbox directories for ALL registered projects and ingests
pending JSON files into Open Brain via the CLI.

This is the canonical version. Project-specific copies (e.g. inside
a repo's cw_handoff/) are convenience aliases — this one runs as the
permanent launchd daemon.

JSON file format (one per file, dropped into any project's outbox):
{
  "agent": "cc",
  "type": "session_summary",
  "area": "general",
  "text": "The memory content"
}

Valid memory types: session_summary, insight, decision, task, blocker, review, handoff
Valid agents: any registered in projects.json (e.g. cc, cx, copilot)
Valid areas: general, backend, frontend, api, database, infra, testing,
            security, devops, ux, docs, ops (configurable)

Usage:
  # Run once (process all pending files across all projects):
  python3 ob_bridge.py

  # Run as watcher (poll every N seconds):
  python3 ob_bridge.py --watch --interval 60

  # Use a custom projects config:
  python3 ob_bridge.py --config /path/to/projects.json
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SELF_DIR = Path(__file__).resolve().parent
OB_DIR = SELF_DIR.parent  # OpenBrain/
DEFAULT_CONFIG = SELF_DIR / "projects.json"
DEFAULT_INTERVAL = 60  # seconds

LOG_DIR = OB_DIR / "logs"
LOG_FILE = LOG_DIR / "ob_bridge.log"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE)),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("ob_bridge")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    """Load the projects registry."""
    try:
        data = json.loads(path.read_text())
        return data.get("projects", {})
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.error("Cannot load config %s: %s", path, e)
        return {}


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process_file(filepath: Path, project_root: Path) -> bool:
    """Process one outbox JSON file via open_brain CLI. Returns True on success."""
    try:
        data = json.loads(filepath.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.warning("SKIP %s: %s", filepath.name, e)
        return False

    agent = data.get("agent", "cc")
    mem_type = data.get("type", "session_summary")
    area = data.get("area", "general")
    text = data.get("text", "")

    if not text.strip():
        log.warning("SKIP %s: empty text", filepath.name)
        return False

    cmd = [
        sys.executable, "-m", "open_brain.cli", "capture",
        text,
        "--agent", agent,
        "--type", mem_type,
        "--area", area,
    ]

    # Run from the project root so open_brain package is importable.
    # Falls back to OpenBrain/ if the project root doesn't have open_brain.
    cwd = str(project_root) if (project_root / "open_brain").is_dir() else str(OB_DIR)
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

    if result.returncode == 0:
        log.info("OK   %s -> OB (%s/%s/%s)", filepath.name, agent, mem_type, area)
        return True
    else:
        log.error("FAIL %s: %s", filepath.name, result.stderr.strip()[:300])
        return False


def process_outbox(outbox: Path, project_root: Path) -> int:
    """Process all pending JSON files in one outbox. Returns count processed."""
    if not outbox.is_dir():
        return 0

    processed_dir = outbox / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(outbox.glob("*.json"))
    if not files:
        return 0

    count = 0
    for p in files:
        if process_file(p, project_root):
            shutil.move(str(p), str(processed_dir / p.name))
            count += 1
        else:
            shutil.move(str(p), str(processed_dir / f"FAILED_{p.name}"))
    return count


def run_once(config: dict) -> int:
    """Process all outboxes across all registered projects."""
    total = 0
    for name, proj in config.items():
        outbox = Path(proj.get("outbox", ""))
        root = Path(proj.get("root", ""))
        if not outbox.is_dir():
            continue
        n = process_outbox(outbox, root)
        if n:
            log.info("[%s] Processed %d file(s)", name, n)
        total += n
    return total


def watch(config: dict, interval: float = DEFAULT_INTERVAL) -> None:
    """Poll all outboxes every `interval` seconds."""
    project_names = ", ".join(config.keys()) or "(none)"
    log.info("OB bridge watching projects: %s (every %ds)", project_names, int(interval))
    while True:
        try:
            run_once(config)
        except Exception as e:
            log.error("Bridge error: %s", e)
        time.sleep(interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Open Brain file bridge")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help="Path to projects.json")
    parser.add_argument("--watch", action="store_true",
                        help="Run continuously, polling on interval")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                        help=f"Poll interval in seconds (default: {DEFAULT_INTERVAL})")
    args = parser.parse_args()

    config = load_config(args.config)
    if not config:
        log.warning("No projects configured in %s", args.config)

    if args.watch:
        watch(config, args.interval)
    else:
        n = run_once(config)
        if n:
            log.info("Total: %d file(s) processed", n)
        else:
            log.info("No pending files")


if __name__ == "__main__":
    main()
