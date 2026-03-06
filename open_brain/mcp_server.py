"""Open Brain MCP server — JSON-RPC over stdio.

Run: python3 -m open_brain.mcp_server
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from open_brain import config
from open_brain import db
from open_brain.capture import capture_memory, embed_text

server = Server("open_brain")

# ---------------------------------------------------------------------------
# Tool catalogue
# ---------------------------------------------------------------------------

TOOLS = [
    Tool(
        name="capture_memory",
        description=(
            "Store a memory (decision, task, insight, session_summary, etc.) "
            "in the shared brain. Returns the UUID of the stored memory."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The memory content"},
                "source_agent": {
                    "type": "string",
                    "description": "Agent identifier (e.g. 'cc', 'cx', 'copilot')",
                },
                "memory_type": {
                    "type": "string",
                    "enum": sorted(config.VALID_MEMORY_TYPES),
                },
                "area": {
                    "type": "string",
                    "enum": sorted(config.VALID_AREAS),
                    "default": "general",
                },
                "action_status": {
                    "type": "string",
                    "enum": sorted(config.VALID_ACTION_STATUSES),
                    "description": "Required for tasks",
                },
                "assigned_to": {
                    "type": "string",
                    "description": "Agent to assign to, or 'all'",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                },
            },
            "required": ["text", "source_agent", "memory_type"],
        },
    ),
    Tool(
        name="semantic_search",
        description=(
            "Search memories by meaning. Returns up to 10 results ranked by "
            "relevance, throttled to the token budget."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language query"},
                "limit": {"type": "integer", "default": 10, "maximum": 20},
                "source_agent": {"type": "string"},
                "memory_type": {"type": "string"},
                "area": {"type": "string"},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="list_recent",
        description="List recent memories, newest first, with optional filters.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "maximum": 50},
                "source_agent": {"type": "string"},
                "memory_type": {"type": "string"},
                "area": {"type": "string"},
            },
        },
    ),
    Tool(
        name="get_pending_tasks",
        description=(
            "Get pending and blocked tasks. If assigned_to is given, returns "
            "tasks for that agent plus tasks assigned to 'all'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "assigned_to": {"type": "string"},
            },
        },
    ),
    Tool(
        name="update_task_status",
        description=(
            "Update the status of a task memory (e.g. pending -> completed)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "UUID of the task memory",
                },
                "new_status": {
                    "type": "string",
                    "enum": sorted(config.VALID_ACTION_STATUSES),
                },
                "agent": {
                    "type": "string",
                    "description": "Agent performing the update",
                },
                "note": {"type": "string"},
            },
            "required": ["memory_id", "new_status", "agent"],
        },
    ),
    Tool(
        name="get_session_context",
        description=(
            "Get composite startup context for an agent: pending tasks, "
            "blocked tasks, recent activity from other agents, and the "
            "agent's last session summary."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "Agent identifier to get context for",
                },
            },
            "required": ["agent"],
        },
    ),
]


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return TOOLS


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
    args = arguments or {}
    try:
        result = _dispatch(name, args)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


def _dispatch(name: str, args: dict) -> Any:
    if name == "capture_memory":
        mem_id = capture_memory(
            text=args["text"],
            source_agent=args["source_agent"],
            memory_type=args["memory_type"],
            area=args.get("area", "general"),
            action_status=args.get("action_status"),
            assigned_to=args.get("assigned_to"),
            priority=args.get("priority"),
        )
        return {"id": mem_id, "status": "stored"}

    elif name == "semantic_search":
        query_vec = embed_text(args["query"])
        results = db.semantic_search(
            query_embedding=query_vec,
            limit=args.get("limit", 10),
            source_agent=args.get("source_agent"),
            memory_type=args.get("memory_type"),
            area=args.get("area"),
        )
        return _throttle(results)

    elif name == "list_recent":
        return db.list_recent(
            limit=args.get("limit", 20),
            source_agent=args.get("source_agent"),
            memory_type=args.get("memory_type"),
            area=args.get("area"),
        )

    elif name == "get_pending_tasks":
        return db.get_pending_tasks(
            assigned_to=args.get("assigned_to"),
        )

    elif name == "update_task_status":
        updated = db.update_task_status(
            memory_id=args["memory_id"],
            new_status=args["new_status"],
            agent=args["agent"],
            note=args.get("note"),
        )
        return {"updated": updated}

    elif name == "get_session_context":
        return db.get_session_context(agent=args["agent"])

    else:
        raise ValueError(f"Unknown tool: {name}")


def _throttle(results: list) -> list:
    """Trim results to fit within the token budget."""
    kept = []
    tokens_used = 0
    for r in results:
        t = config.estimate_tokens(r.get("raw_text", ""))
        if tokens_used + t > config.TOKEN_BUDGET:
            break
        kept.append(r)
        tokens_used += t
    return kept


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main():
    async with stdio_server() as streams:
        await server.run(
            streams[0],
            streams[1],
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
