"""Open Brain CLI — clean text output for CX and CW agents.

Run: python3 -m open_brain.cli <command> [options]
"""

import argparse
import json
import sys
from datetime import datetime

from open_brain import config
from open_brain import db
from open_brain.capture import capture_memory, embed_text


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="open_brain",
        description="Open Brain — persistent cross-agent memory",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # status
    sub.add_parser("status", help="Check database connection")

    # capture
    p_cap = sub.add_parser("capture", help="Store a memory")
    p_cap.add_argument("text", help="Memory content")
    _agent_choices = config.get_valid_agents() or None  # None = accept any
    p_cap.add_argument("--agent", required=True, choices=_agent_choices)
    p_cap.add_argument("--type", required=True, dest="memory_type",
                       choices=sorted(config.VALID_MEMORY_TYPES))
    p_cap.add_argument("--area", default="general", choices=sorted(config.VALID_AREAS))
    p_cap.add_argument("--status", dest="action_status",
                       choices=sorted(config.VALID_ACTION_STATUSES))
    _assignee_choices = (config.get_valid_agents() + ["all"]) if config.get_valid_agents() else None
    p_cap.add_argument("--assigned-to", choices=_assignee_choices)
    p_cap.add_argument("--priority", choices=["low", "medium", "high", "critical"])

    # search
    p_search = sub.add_parser("search", help="Semantic search")
    p_search.add_argument("query", help="Natural language query")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--agent", dest="source_agent")
    p_search.add_argument("--type", dest="memory_type")
    p_search.add_argument("--area")

    # list-recent
    p_recent = sub.add_parser("list-recent", help="List recent memories")
    p_recent.add_argument("--limit", type=int, default=20)
    p_recent.add_argument("--agent", dest="source_agent")
    p_recent.add_argument("--type", dest="memory_type")
    p_recent.add_argument("--area")

    # pending-tasks
    p_pending = sub.add_parser("pending-tasks", help="Get pending/blocked tasks")
    p_pending.add_argument("--agent", dest="assigned_to")

    # update-task
    p_update = sub.add_parser("update-task", help="Update task status")
    p_update.add_argument("memory_id", help="UUID of the task")
    p_update.add_argument("--status", required=True, dest="new_status",
                          choices=sorted(config.VALID_ACTION_STATUSES))
    p_update.add_argument("--agent", required=True, choices=config.get_valid_agents() or None)
    p_update.add_argument("--note")

    # session-context
    p_ctx = sub.add_parser("session-context", help="Get startup context for an agent")
    p_ctx.add_argument("--agent", required=True, choices=config.get_valid_agents() or None)

    args = parser.parse_args(argv)

    try:
        if args.command == "status":
            _cmd_status()
        elif args.command == "capture":
            _cmd_capture(args)
        elif args.command == "search":
            _cmd_search(args)
        elif args.command == "list-recent":
            _cmd_list_recent(args)
        elif args.command == "pending-tasks":
            _cmd_pending_tasks(args)
        elif args.command == "update-task":
            _cmd_update_task(args)
        elif args.command == "session-context":
            _cmd_session_context(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _cmd_status():
    ok = db.verify_connection()
    if ok:
        print("Database connection: OK")
        print(f"  Host: {config.DB_HOST}:{config.DB_PORT}")
        print(f"  Database: {config.DB_NAME}")
        print(f"  Embedding model: {config.EMBEDDING_MODEL_NAME}")
        print(f"  Dimension: {config.EMBEDDING_DIMENSION}")
    else:
        print("Database connection: FAILED", file=sys.stderr)
        sys.exit(1)


def _cmd_capture(args):
    mem_id = capture_memory(
        text=args.text,
        source_agent=args.agent,
        memory_type=args.memory_type,
        area=args.area,
        action_status=args.action_status,
        assigned_to=args.assigned_to,
        priority=args.priority,
    )
    print(f"Stored: {mem_id}")


def _cmd_search(args):
    query_vec = embed_text(args.query)
    results = db.semantic_search(
        query_embedding=query_vec,
        limit=args.limit,
        source_agent=args.source_agent,
        memory_type=args.memory_type,
        area=args.area,
    )
    if not results:
        print("No results.")
        return
    _print_results(results, show_distance=True)


def _cmd_list_recent(args):
    results = db.list_recent(
        limit=args.limit,
        source_agent=args.source_agent,
        memory_type=args.memory_type,
        area=args.area,
    )
    if not results:
        print("No memories found.")
        return
    _print_results(results)


def _cmd_pending_tasks(args):
    results = db.get_pending_tasks(assigned_to=args.assigned_to)
    if not results:
        print("No pending or blocked tasks.")
        return
    for r in results:
        meta = r.get("metadata", {})
        status = meta.get("action_status", "?")
        assigned = meta.get("assigned_to", "?")
        area = meta.get("area", "?")
        priority = meta.get("priority", "-")
        print(f"[{status.upper()}] [{area}] (assigned: {assigned}, priority: {priority})")
        print(f"  ID: {r['id']}")
        print(f"  {_truncate(r['raw_text'], 200)}")
        print()


def _cmd_update_task(args):
    updated = db.update_task_status(
        memory_id=args.memory_id,
        new_status=args.new_status,
        agent=args.agent,
        note=args.note,
    )
    if updated:
        print(f"Task {args.memory_id} → {args.new_status}")
    else:
        print(f"Task {args.memory_id} not found (or not a task)", file=sys.stderr)
        sys.exit(1)


def _cmd_session_context(args):
    ctx = db.get_session_context(agent=args.agent)

    print(f"=== Session Context for {args.agent.upper()} ===\n")

    print(f"Pending tasks ({len(ctx['pending_tasks'])}):")
    if ctx["pending_tasks"]:
        for t in ctx["pending_tasks"]:
            meta = t.get("metadata", {})
            print(f"  - [{meta.get('area', '?')}] {_truncate(t['raw_text'], 120)}")
            print(f"    ID: {t['id']}")
    else:
        print("  (none)")

    print(f"\nBlocked tasks ({len(ctx['blocked_tasks'])}):")
    if ctx["blocked_tasks"]:
        for t in ctx["blocked_tasks"]:
            meta = t.get("metadata", {})
            print(f"  - [{meta.get('area', '?')}] {_truncate(t['raw_text'], 120)}")
            print(f"    ID: {t['id']}")
    else:
        print("  (none)")

    print(f"\nRecent from other agents ({len(ctx['other_agents_recent'])}):")
    if ctx["other_agents_recent"]:
        for r in ctx["other_agents_recent"]:
            meta = r.get("metadata", {})
            agent = meta.get("source_agent", "?")
            mtype = meta.get("memory_type", "?")
            print(f"  [{agent}] [{mtype}] {_truncate(r['raw_text'], 100)}")
    else:
        print("  (none)")

    print(f"\nLast session summary:")
    if ctx["last_session_summary"]:
        print(f"  {ctx['last_session_summary']['raw_text'][:300]}")
    else:
        print("  (none)")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _print_results(results, show_distance=False):
    for i, r in enumerate(results, 1):
        meta = r.get("metadata", {})
        tags = []
        for key in ("source_agent", "memory_type", "area", "action_status"):
            if key in meta:
                tags.append(meta[key])
        tag_str = " | ".join(tags) if tags else "-"

        created = r.get("created_at", "?")
        if isinstance(created, str) and "T" in created:
            created = created[:19].replace("T", " ")

        line = f"{i}. [{tag_str}] {created}"
        if show_distance and "distance" in r:
            line += f"  (dist: {r['distance']:.4f})"
        print(line)
        print(f"   {_truncate(r['raw_text'], 200)}")
        print(f"   ID: {r['id']}")
        print()


def _truncate(text, max_len):
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


if __name__ == "__main__":
    main()
