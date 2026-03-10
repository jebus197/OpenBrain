"""IM CLI service — backward-compatible entry point.

Replaces tools/im_service.py with SQLite-backed commands. All existing
commands continue to work:

    python3 -m open_brain.im read [--channel cc] [--limit 20]
    python3 -m open_brain.im recent [--limit 5]
    python3 -m open_brain.im post <channel> "message"
    python3 -m open_brain.im action "status" "summary"
    python3 -m open_brain.im search "query"
    python3 -m open_brain.im clear <channel|all>
    python3 -m open_brain.im init [--project project_name]
    python3 -m open_brain.im thread <msg_id>
    python3 -m open_brain.im unread <recipient>
    python3 -m open_brain.im channels
    python3 -m open_brain.im purge [--channel cc] [--older-than 90]
    python3 -m open_brain.im migrate-json <json_path>

    # Resync (backward compat):
    python3 -m open_brain.im r [agent]
    python3 -m open_brain.im rt [agent]

Database path resolution:
    --db-path /explicit/path.sqlite3
    --project name  → ~/.openbrain/im/{name}.sqlite3
    (default)       → ~/.openbrain/im/default.sqlite3
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from open_brain import config
from open_brain.im.store import IMStore


def _resolve_db_path(args: argparse.Namespace) -> Path:
    """Resolve the SQLite database path from CLI args."""
    if getattr(args, "db_path", None):
        return Path(args.db_path)

    project = getattr(args, "project", None) or "default"
    return config.CONFIG_DIR / "im" / f"{project}.sqlite3"


def _get_store(args: argparse.Namespace) -> IMStore:
    """Create an IMStore from CLI args."""
    return IMStore(_resolve_db_path(args))


def _print_messages(messages: list, *, compact: bool = False) -> None:
    """Print messages in a human-readable format."""
    if not messages:
        print("(no messages)")
        return

    for msg in messages:
        ts = msg.created_at[:19].replace("T", " ") if "T" in msg.created_at else msg.created_at
        sig_marker = " [signed]" if msg.signature else ""
        channel = msg.channel_id

        if compact:
            print(f"  [{ts}] [{channel}] {msg.sender}: {msg.content}")
        else:
            print(f"[{ts}] #{channel} {msg.sender}{sig_marker}")
            print(f"  {msg.content}")
            if msg.correlation_id:
                print(f"  thread: {msg.correlation_id}")
            print(f"  id: {msg.msg_id}")
            print()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_read(args: argparse.Namespace) -> None:
    """Read messages from a channel or all channels."""
    store = _get_store(args)
    channel = getattr(args, "channel", None)
    limit = getattr(args, "limit", 50)
    sender = getattr(args, "sender", None)

    if channel:
        messages = store.read_channel(channel, limit=limit, sender=sender)
    else:
        messages = store.read_recent(limit=limit)

    _print_messages(messages)


def cmd_recent(args: argparse.Namespace) -> None:
    """Read most recent messages (lean output for startup)."""
    store = _get_store(args)
    limit = getattr(args, "limit", 5)

    messages = store.read_recent(limit=limit)
    _print_messages(messages, compact=True)


def cmd_post(args: argparse.Namespace) -> None:
    """Post a message to a channel."""
    store = _get_store(args)
    channel = args.channel
    message = args.message
    sender = getattr(args, "sender", None) or "system"

    # Try to load signing function if keypair exists.
    sign_fn = _load_sign_fn()

    msg = store.post(
        channel_id=channel,
        sender=sender,
        content=message,
        sign_fn=sign_fn,
    )

    count = store.message_count(channel)
    print(f"Posted to #{channel} ({count} messages). id: {msg.msg_id}")


def cmd_action(args: argparse.Namespace) -> None:
    """Post an action status message to the system channel."""
    store = _get_store(args)
    status = args.status
    summary = args.summary
    sender = getattr(args, "sender", None) or "system"

    content = f"[ACTION] {status}: {summary}"
    sign_fn = _load_sign_fn()

    store.post(
        channel_id="system",
        sender=sender,
        content=content,
        msg_type="action",
        sign_fn=sign_fn,
    )
    print(f"Active action set: {status}")


def cmd_search(args: argparse.Namespace) -> None:
    """Search messages via FTS5."""
    store = _get_store(args)
    results = store.search(args.query, limit=getattr(args, "limit", 20))
    _print_messages(results)


def cmd_thread(args: argparse.Namespace) -> None:
    """Read a message thread."""
    store = _get_store(args)
    messages = store.read_thread(args.msg_id)
    _print_messages(messages)


def cmd_clear(args: argparse.Namespace) -> None:
    """Clear a channel or all channels."""
    store = _get_store(args)
    target = args.target

    if target == "all":
        count = store.clear_all()
        print(f"Cleared all channels ({count} messages deleted).")
    else:
        count = store.clear_channel(target)
        print(f"Cleared #{target} ({count} messages deleted).")


def cmd_init(args: argparse.Namespace) -> None:
    """Initialise IM database (creates schema + default channels)."""
    db_path = _resolve_db_path(args)
    store = IMStore(db_path)

    # Create standard channels.
    for ch_id, name in [("cc", "CC"), ("cx", "CX"), ("system", "System")]:
        store.create_channel(ch_id, name)

    print(f"IM initialised at {db_path}")
    channels = store.list_channels()
    for ch in channels:
        print(f"  #{ch['channel_id']}: {ch['display_name']}")


def cmd_unread(args: argparse.Namespace) -> None:
    """Show unread messages for a recipient."""
    store = _get_store(args)
    recipient = args.recipient
    channel = getattr(args, "channel", None)

    messages = store.get_unread(recipient, channel_id=channel)
    if not messages:
        print(f"No unread messages for {recipient}.")
        return

    print(f"Unread messages for {recipient} ({len(messages)}):")
    _print_messages(messages, compact=True)


def cmd_channels(args: argparse.Namespace) -> None:
    """List all channels."""
    store = _get_store(args)
    channels = store.list_channels()

    if not channels:
        print("No channels.")
        return

    for ch in channels:
        count = store.message_count(ch["channel_id"])
        print(f"  #{ch['channel_id']}: {ch['display_name']} ({count} messages)")


def cmd_purge(args: argparse.Namespace) -> None:
    """Purge expired messages and/or apply retention policies."""
    store = _get_store(args)
    channel = getattr(args, "channel", None)
    older_than = getattr(args, "older_than", None)

    # Purge TTL-expired messages first.
    expired_count = store.purge_expired()
    if expired_count:
        print(f"Purged {expired_count} TTL-expired messages.")

    # Set ad-hoc retention if --older-than specified.
    if older_than and channel:
        store.set_retention_policy(channel, max_age_days=older_than)

    # Apply retention policies.
    retained = store.apply_retention(channel_id=channel)
    if retained:
        print(f"Retention applied: {retained} messages removed.")

    if not expired_count and not retained:
        print("Nothing to purge.")


def cmd_migrate_json(args: argparse.Namespace) -> None:
    """Migrate flat-file JSON IM state to SQLite."""
    from open_brain.im.migrate import migrate_json_to_sqlite

    json_path = Path(args.json_path)
    sqlite_path = _resolve_db_path(args)
    project = getattr(args, "project", None) or "default"

    result = migrate_json_to_sqlite(
        json_path, sqlite_path, project_name=project
    )

    print(f"Migration complete:")
    print(f"  Channels created: {result['channels']}")
    print(f"  Messages migrated: {result['migrated']}")
    print(f"  Duplicates skipped: {result['skipped']}")
    print(f"  Database: {sqlite_path}")


def cmd_resync(args: argparse.Namespace, *, continue_mode: bool) -> None:
    """Resync: OB session-context + IM recent messages.

    Backward-compatible with the r/rt commands from tools/im_service.py.
    """
    agent = getattr(args, "agent", "cc")
    store = _get_store(args)

    print(f"Resync start (agent={agent})")

    # Open Brain session context.
    print("\n=== Open Brain: session-context ===")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "open_brain.cli", "session-context", "--agent", agent],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        if result.returncode != 0 and not result.stdout.strip():
            print("Session context unavailable.")
    except OSError:
        print("Session context unavailable.")

    # IM recent messages.
    print("\n=== IM recent (last 5 per channel) ===")
    messages = store.read_recent(limit=15)
    _print_messages(messages, compact=True)

    if continue_mode:
        print("\nResync complete. Continue.")


# ---------------------------------------------------------------------------
# Signing helper
# ---------------------------------------------------------------------------


def _load_sign_fn():
    """Try to load an Ed25519 signing function from the node keypair.

    Returns None if no keypair exists (messages will be unsigned).
    """
    try:
        from open_brain.crypto import has_keypair, sign_memory
        if not has_keypair():
            return None

        from open_brain.crypto import load_private_key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        private_key_bytes = load_private_key()
        key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)

        def _sign(content_hash: str) -> str:
            sig = key.sign(content_hash.encode("utf-8"))
            return sig.hex()

        return _sign
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="open_brain.im",
        description="Open Brain IM — SQLite WAL-mode inter-agent messaging",
    )
    parser.add_argument("--project", "-p", type=str, default=None,
                        help="Project name (resolves to ~/.openbrain/im/{name}.sqlite3)")
    parser.add_argument("--db-path", type=str, default=None,
                        help="Direct path to SQLite database")

    sub = parser.add_subparsers(dest="command", help="Command to run")

    # read
    p_read = sub.add_parser("read", help="Read messages from a channel or all")
    p_read.add_argument("--channel", "-c", help="Channel to read (default: all)")
    p_read.add_argument("--limit", "-n", type=int, default=50)
    p_read.add_argument("--sender", help="Filter by sender")

    # recent
    p_recent = sub.add_parser("recent", help="Last N messages (lean startup read)")
    p_recent.add_argument("--limit", "-n", type=int, default=5)

    # post
    p_post = sub.add_parser("post", help="Post a message to a channel")
    p_post.add_argument("channel", help="Target channel (e.g. cc, cx)")
    p_post.add_argument("message", help="Message text")
    p_post.add_argument("--sender", "-s", default="system", help="Sender ID")

    # action
    p_action = sub.add_parser("action", help="Set active action status")
    p_action.add_argument("status", help="Status (e.g. IN_PROGRESS, IDLE)")
    p_action.add_argument("summary", help="Action summary")
    p_action.add_argument("--sender", "-s", default="system")

    # search
    p_search = sub.add_parser("search", help="Full-text search")
    p_search.add_argument("query", help="Search query (FTS5 syntax)")
    p_search.add_argument("--limit", "-n", type=int, default=20)

    # thread
    p_thread = sub.add_parser("thread", help="Read a message thread")
    p_thread.add_argument("msg_id", help="Root message ID")

    # clear
    p_clear = sub.add_parser("clear", help="Clear a channel or all channels")
    p_clear.add_argument("target", help="Channel name or 'all'")

    # init
    sub.add_parser("init", help="Initialise IM database with default channels")

    # unread
    p_unread = sub.add_parser("unread", help="Show unread messages for a recipient")
    p_unread.add_argument("recipient", help="Recipient agent ID")
    p_unread.add_argument("--channel", "-c", help="Filter to channel")

    # channels
    sub.add_parser("channels", help="List all channels")

    # purge
    p_purge = sub.add_parser("purge", help="Purge expired/old messages")
    p_purge.add_argument("--channel", "-c", help="Limit purge to channel")
    p_purge.add_argument("--older-than", type=int, help="Max age in days")

    # migrate-json
    p_mig = sub.add_parser("migrate-json", help="Migrate flat-file JSON to SQLite")
    p_mig.add_argument("json_path", help="Path to im_state.json")

    # r / rt (resync backward compat)
    p_r = sub.add_parser("r", help="Resync (OB context + IM recent)")
    p_r.add_argument("agent", nargs="?", default="cc")
    p_rt = sub.add_parser("rt", help="Resync + continue")
    p_rt.add_argument("agent", nargs="?", default="cc")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    try:
        if args.command == "read":
            cmd_read(args)
        elif args.command == "recent":
            cmd_recent(args)
        elif args.command == "post":
            cmd_post(args)
        elif args.command == "action":
            cmd_action(args)
        elif args.command == "search":
            cmd_search(args)
        elif args.command == "thread":
            cmd_thread(args)
        elif args.command == "clear":
            cmd_clear(args)
        elif args.command == "init":
            cmd_init(args)
        elif args.command == "unread":
            cmd_unread(args)
        elif args.command == "channels":
            cmd_channels(args)
        elif args.command == "purge":
            cmd_purge(args)
        elif args.command == "migrate-json":
            cmd_migrate_json(args)
        elif args.command == "r":
            cmd_resync(args, continue_mode=False)
        elif args.command == "rt":
            cmd_resync(args, continue_mode=True)
        else:
            print(f"Unknown command: {args.command}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
