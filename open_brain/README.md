# open_brain — Python Package

Core package for Open Brain. PostgreSQL + pgvector semantic search, accessible via MCP server or CLI.

## Quick Start

```bash
# Check status
python3 -m open_brain.cli status

# Store a memory
python3 -m open_brain.cli capture "Your memory text" --agent myagent --type decision --area backend

# Search
python3 -m open_brain.cli search "authentication pipeline"

# List recent
python3 -m open_brain.cli list-recent --limit 10 --agent myagent

# Pending tasks
python3 -m open_brain.cli pending-tasks --agent myagent

# Update task
python3 -m open_brain.cli update-task <UUID> --status completed --agent myagent --note "Done"

# Session startup context
python3 -m open_brain.cli session-context --agent myagent
```

## Agent Wiring

**MCP-compatible agents** (Claude Code, etc.): MCP server — tools appear natively.
```json
{
  "mcpServers": {
    "open_brain": {
      "command": "python3",
      "args": ["-m", "open_brain.mcp_server"],
      "cwd": "/path/to/OpenBrain"
    }
  }
}
```

**CLI-based agents** (Codex, Copilot, etc.): Use CLI commands directly.
```bash
python3 -m open_brain.cli session-context --agent myagent
python3 -m open_brain.cli capture "text" --agent myagent --type insight --area backend
```

**IM Bridge** (dual-write to JSON + DB):
```bash
python3 -m open_brain.im_bridge post myagent "message"
python3 -m open_brain.im_bridge action "IN_PROGRESS" "summary"
```

## Database

- **Host**: localhost:5432
- **Database**: open_brain (test: open_brain_test)
- **Roles**: ob_reader (SELECT), ob_writer (INSERT/UPDATE)
- **Embedding**: BAAI/bge-small-en-v1.5 (384 dims, local, zero API cost)

## Memory Types

decision, task, session_summary, insight, blocker, review, handoff

## Default Areas

general, backend, frontend, api, database, infra, testing, security, devops, ux, docs, ops

Areas are configurable in `~/.openbrain/config.json`.

## Tests

```bash
OPEN_BRAIN_DB_NAME=open_brain_test python3 -m pytest open_brain/tests/ -v
```
