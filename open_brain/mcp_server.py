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
            "blocked tasks, recent activity from other agents, the "
            "agent's last session summary, and last reasoning checkpoint."
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
    Tool(
        name="assemble_proof",
        description=(
            "Assemble a self-contained proof package for a memory. "
            "Verifiable with SHA-256 + Ed25519 + a block explorer — "
            "no Open Brain installation required."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "UUID of the memory to prove",
                },
            },
            "required": ["memory_id"],
        },
    ),
    Tool(
        name="get_reasoning_chain",
        description=(
            "Retrieve chronological reasoning checkpoints for an agent. "
            "Optionally filtered by session."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "Source agent identifier",
                },
                "session_id": {
                    "type": "string",
                    "description": "Filter to a specific session",
                },
                "limit": {"type": "integer", "default": 20, "maximum": 1000},
            },
            "required": ["agent"],
        },
    ),
    Tool(
        name="verify_reasoning_chain",
        description=(
            "Verify a reasoning checkpoint chain with five checks: "
            "content hash integrity, hash chain continuity, signature "
            "validity, epoch inclusion, and epoch chain."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "Source agent identifier",
                },
                "session_id": {
                    "type": "string",
                    "description": "Filter to a specific session",
                },
            },
            "required": ["agent"],
        },
    ),
    Tool(
        name="record_anchor",
        description=(
            "Record blockchain anchor metadata for a sealed epoch. "
            "Chain-agnostic: proof_type determines schema "
            "(ethereum, ots, rfc3161)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "epoch_id": {
                    "type": "string",
                    "description": "UUID of the sealed epoch",
                },
                "anchored_at": {
                    "type": "string",
                    "description": "ISO 8601 timestamp of anchoring",
                },
                "anchor_metadata": {
                    "type": "object",
                    "description": (
                        "Chain-specific metadata. Must include proof_type "
                        "(ethereum, ots, rfc3161)"
                    ),
                },
            },
            "required": ["epoch_id", "anchored_at", "anchor_metadata"],
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

    elif name == "assemble_proof":
        from open_brain.reasoning import assemble_proof as _assemble_proof
        proof = _assemble_proof(args["memory_id"])
        if proof is None:
            return {"error": "Memory not found"}
        return proof.to_dict()

    elif name == "get_reasoning_chain":
        from open_brain.reasoning import get_reasoning_chain as _get_chain
        return _get_chain(
            args["agent"],
            session_id=args.get("session_id"),
            limit=args.get("limit", 20),
        )

    elif name == "verify_reasoning_chain":
        from open_brain.reasoning import verify_reasoning_chain as _verify_chain
        result = _verify_chain(
            args["agent"],
            session_id=args.get("session_id"),
        )
        return result.to_dict()

    elif name == "record_anchor":
        from open_brain.epoch import record_anchor as _record_anchor
        updated = _record_anchor(
            epoch_id=args["epoch_id"],
            anchored_at=args["anchored_at"],
            anchor_metadata=args["anchor_metadata"],
        )
        return {"updated": updated}

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
