"""IM bridge — dual-write wrapper around the canonical im_service.py.

Writes to both the JSON rolling buffer (original) AND the Open Brain
database (additive). DB failure is non-fatal: stderr warning, IM still
works.

Usage (drop-in replacement for im_service.py):
    python3 -m open_brain.im_bridge post cc "message"
    python3 -m open_brain.im_bridge action "status" "summary"
    python3 -m open_brain.im_bridge read
    python3 -m open_brain.im_bridge <any other command>

All commands pass through to the original im_service.py. Only 'post'
and 'action' also write to the database.
"""

import importlib.util
import sys
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Dynamic import of canonical im_service.py (don't modify the original)
# ---------------------------------------------------------------------------

_IM_SERVICE_PATH = (
    Path(__file__).resolve().parent.parent / "tools" / "im_service.py"
)


def _load_im_service():
    """Import im_service.py from its canonical location."""
    spec = importlib.util.spec_from_file_location("im_service", _IM_SERVICE_PATH)
    if spec is None or spec.loader is None:
        print(f"Error: cannot load im_service from {_IM_SERVICE_PATH}", file=sys.stderr)
        sys.exit(1)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Database dual-write (non-fatal)
# ---------------------------------------------------------------------------


def _db_capture_post(stream: str, message: str):
    """Attempt to also store the IM post in Open Brain."""
    try:
        from open_brain.capture import capture_memory

        # Map stream name to agent
        agent = stream if stream in ("cc", "cx", "cw") else "cc"
        capture_memory(
            text=message,
            source_agent=agent,
            memory_type="handoff",
            area="general",
        )
    except Exception:
        print(
            f"[open_brain] DB write failed (IM post still succeeded): "
            f"{traceback.format_exc()}",
            file=sys.stderr,
        )


def _db_capture_action(status: str, summary: str):
    """Attempt to store the action update in Open Brain."""
    try:
        from open_brain.capture import capture_memory

        capture_memory(
            text=f"Action: {status} — {summary}",
            source_agent="cc",  # Actions are system-level
            memory_type="task",
            area="general",
            action_status="pending" if status.upper() not in ("IDLE", "DONE") else "completed",
        )
    except Exception:
        print(
            f"[open_brain] DB write failed (IM action still succeeded): "
            f"{traceback.format_exc()}",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------


def main():
    im = _load_im_service()

    if len(sys.argv) < 2:
        print("Usage: python3 -m open_brain.im_bridge <command> [args...]")
        print("Commands: read, post, action, archive, clear, init")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "post":
        if len(sys.argv) < 4:
            print("Usage: post <cc|cx|cw> \"message\"", file=sys.stderr)
            sys.exit(1)
        stream = sys.argv[2].lower()
        message = sys.argv[3]
        # Original IM write
        im.cmd_post(stream, message)
        # Database dual-write (non-fatal)
        _db_capture_post(stream, message)

    elif command == "action":
        if len(sys.argv) < 4:
            print("Usage: action \"status\" \"summary\"", file=sys.stderr)
            sys.exit(1)
        status = sys.argv[2]
        summary = sys.argv[3]
        # Original IM write
        im.cmd_action(status, summary)
        # Database dual-write (non-fatal)
        _db_capture_action(status, summary)

    elif command == "read":
        im.cmd_read()

    elif command == "archive":
        if len(sys.argv) < 3:
            print("Usage: archive \"summary\"", file=sys.stderr)
            sys.exit(1)
        im.cmd_archive(sys.argv[2])

    elif command == "clear":
        if len(sys.argv) < 3:
            print("Usage: clear <cc|cx|all>", file=sys.stderr)
            sys.exit(1)
        im.cmd_clear(sys.argv[2])

    elif command == "init":
        # Pass through — some IM versions have init
        if hasattr(im, "cmd_init"):
            im.cmd_init()
        else:
            print("Init not needed — state file created on first write.")

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
