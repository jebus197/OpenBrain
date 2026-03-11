# Open Brain — Project-Level Instructions

These instructions override or supplement the global `~/.claude/CLAUDE.md`
when the working directory is within this repository.

## Identity

Persistent, verifiable memory for AI agents. Model-agnostic,
chain-agnostic. PostgreSQL + pgvector + sentence-transformers.

## Recovery (project-specific)

After compaction, in addition to the universal checks (git state + OB
session-context), no additional project-specific recovery is needed.
OB session-context IS the recovery mechanism for this project:
  python3 -m open_brain.cli session-context --agent cc

## Test Protocol

Full suite: python3 -m pytest open_brain/tests/ -v
Quick check: python3 -m pytest open_brain/tests/ -q
Current count: 440+ (verify on each session start)

## Key Paths

- MCP server: open_brain/mcp_server.py
- DB layer: open_brain/db.py
- Capture pipeline: open_brain/capture.py
- Reasoning verification: open_brain/reasoning.py
- Epoch system: open_brain/epoch.py
- CLI: open_brain/cli.py
- Facade: open_brain/api/memory_facade.py
- Migrations: open_brain/migrations/
- Schema: open_brain/setup_db.sql
- Tests: open_brain/tests/

## Project Scoping

OB now supports `project` parameter across all surfaces (MCP tools,
CLI, capture, db queries, facade). Use `--project <name>` in CLI
or `project` key in MCP tool calls to scope operations.

## Doc Lock-step

When changing user-facing behaviour, update:
- open_brain/README.md
- METHODOLOGY.md (if verification-related)
- WHITE_PAPER.md (if architecture-related)
