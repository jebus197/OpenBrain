# Agent Recovery Guide

You are an AI agent starting a session on a project that uses Open Brain for
persistent memory and cross-agent coordination. This document tells you how
to bootstrap yourself from zero context.

---

## Step 1: Locate Open Brain

Find the Open Brain install location:
```bash
python3 -c "import open_brain; print(open_brain.__file__)"
# Or check: which ob
```

## Step 2: Check System Health

Run these commands in order:

```bash
# Is PostgreSQL running?
pg_isready

# Is Open Brain functional?
cd /path/to/OpenBrain
python3 -m open_brain.cli status

# Is the bridge daemon running?
launchctl list | grep openbrain
```

**If PostgreSQL is down:**
```bash
brew services restart postgresql@15
```

**If Open Brain errors:**
```bash
# Re-apply schema (safe — idempotent)
psql open_brain < /path/to/OpenBrain/open_brain/setup_db.sql
```

**If the bridge daemon is not running:**
```bash
launchctl load ~/Library/LaunchAgents/com.openbrain.bridge.plist
```

## Step 3: Get Your Context

```bash
# Get your agent session context (replace 'cc' with your agent ID)
python3 -m open_brain.cli session-context --agent cc
```

This returns:
- Pending tasks assigned to you
- Blocked tasks
- Recent activity from other agents
- Your last session summary

## Step 4: Read the IM

```bash
# Find which project you're working on
cat /path/to/OpenBrain/tools/projects.json

# Read IM for that project
python3 /path/to/OpenBrain/tools/im_service.py \
    --project <project_name> read
```

## Step 5: Check the Action Queue

If your project uses an ACTION_QUEUE.md file, read it:
```bash
# The location varies by project — check the project's agent_handoff/ or
# cw_handoff/ directory.
```

## Step 6: Read Project-Specific Memory

```bash
# Check if the project has a MEMORY.md or CLAUDE.md
# These are typically in the project root or .claude/ directory
```

## Step 7: Post Your Session Start

Let other agents know you're online:

```bash
python3 /path/to/OpenBrain/tools/im_service.py \
    --project <project_name> post <your_agent_id> \
    "<YOUR_ID>: Session started. Context recovered via OB + IM."
```

And capture a memory:

```bash
python3 -m open_brain.cli capture \
    "Session started. Recovered context from OB session-context + IM read." \
    --agent <your_agent_id> --type session_summary --area general
```

---

## Quick Reference

| What | Command |
|------|---------|
| OB status | `python3 -m open_brain.cli status` |
| Session context | `python3 -m open_brain.cli session-context --agent cc` |
| Search memories | `python3 -m open_brain.cli search "query"` |
| Recent memories | `python3 -m open_brain.cli list-recent --limit 10` |
| Capture memory | `python3 -m open_brain.cli capture "text" --agent cc --type insight` |
| Pending tasks | `python3 -m open_brain.cli pending-tasks --agent cc` |
| Read IM | `python3 tools/im_service.py --project <name> read` |
| Post to IM | `python3 tools/im_service.py --project <name> post <stream> "msg"` |
| Resync (all) | `python3 tools/im_service.py --project <name> r <agent>` |
| Bridge status | `launchctl list \| grep openbrain` |
| Bridge logs | `tail -20 OpenBrain/logs/ob_bridge.log` |

## MCP Tools (if wired)

If Open Brain is configured as an MCP server, you can use these tools
directly without CLI commands:

- `capture_memory` — store a memory
- `semantic_search` — search by meaning
- `list_recent` — recent memories
- `get_pending_tasks` — your pending work
- `update_task_status` — mark tasks done
- `get_session_context` — full startup context

---

## If Everything Is Broken

Worst case: PostgreSQL is down, Open Brain is unreachable, no MCP, no IM.

1. Check the project's local files: `MEMORY.md`, `ACTION_QUEUE.md`,
   `QWERTY_CHECKPOINT.md`, `im_state.json` — these are plain JSON/Markdown
   and readable without any service.

2. Restart PostgreSQL: `brew services restart postgresql@15`

3. Re-apply the schema: `psql open_brain < OpenBrain/open_brain/setup_db.sql`

4. Restart the bridge: `launchctl load ~/Library/LaunchAgents/com.openbrain.bridge.plist`

5. If the database is completely gone, Open Brain will start fresh with an
   empty memory store. Previous memories are lost, but local project files
   (MEMORY.md, ACTION_QUEUE.md) serve as fallback context.

The system is designed to degrade gracefully. Each component works
independently. If OB is down, IM still works. If IM is down, OB still works.
If both are down, local files are the last resort.
