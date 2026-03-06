# Open Brain

Persistent cross-agent memory for AI-assisted software development.

Open Brain gives your AI coding agents (Claude Code, Codex, Copilot, Cursor, Aider, Windsurf — any of them) a **shared, persistent memory** backed by PostgreSQL and semantic vector search. Every insight, decision, task, and session summary survives across sessions, across agents, and across projects.

## Why?

AI coding agents are stateless by default. Every new session starts from zero. If you use multiple agents — or even the same agent across sessions — context is lost, decisions are forgotten, and work is repeated.

Open Brain fixes this. Agents write memories to a shared database. Any agent can search them semantically ("what did we decide about authentication?") or browse recent activity. The result: agents that remember, coordinate, and build on each other's work.

## What It Does

- **Semantic search** — find memories by meaning, not keywords (powered by pgvector + BAAI/bge-small-en-v1.5, 384 dimensions, runs locally, zero API cost)
- **Multi-agent coordination** — any number of agents share one brain, each identified by name
- **Structured memory types** — decisions, tasks, insights, session summaries, blockers, reviews, handoffs
- **Task lifecycle** — pending → in_progress → blocked → completed → cancelled, with assignments
- **Session context** — agents get pending tasks, blocked items, and recent activity from other agents on startup
- **Three access methods** — MCP server (for Claude Code and compatible agents), CLI (for everything), file bridge (for sandboxed agents)
- **IM service** — lightweight inter-agent messaging with rolling buffer (20 messages per stream, file-locked)
- **Input sanitisation** — prompt-injection pattern detection before storage
- **Role-separated database access** — reader/writer roles enforce least privilege
- **Cross-platform** — works on macOS, Linux, and Windows
- **Fully configurable** — agents, areas, embedding model, token budget — all adjustable per-project or globally

## Quick Start

### macOS / Linux

```bash
git clone https://github.com/jebus197/OpenBrain.git && cd OpenBrain && ./scripts/install.sh
```

### Windows (PowerShell)

```powershell
git clone https://github.com/jebus197/OpenBrain.git; cd OpenBrain; .\scripts\install.ps1
```

The install script checks prerequisites (Python 3.9+, PostgreSQL, pgvector), creates a virtualenv, installs dependencies, and launches an interactive setup wizard that configures the database, registers your project, detects your agents, and runs a smoke test.

If Python is installed but not in your PATH, the installer will find it and show the exact command to fix your PATH — it never modifies your shell config automatically.

### Manual install

```bash
# Clone
git clone https://github.com/jebus197/OpenBrain.git
cd OpenBrain

# Install
python3 -m venv .venv

# Activate (macOS/Linux)
source .venv/bin/activate

# Activate (Windows PowerShell)
# .venv\Scripts\Activate.ps1

pip install -e .

# Setup (interactive wizard — creates DB, roles, schema, registers your project)
ob-setup

# Verify
ob-doctor
```

### Prerequisites

| Requirement | Version | macOS | Linux | Windows |
|---|---|---|---|---|
| Python | 3.9+ | `brew install python@3.12` | `apt install python3` | [python.org](https://python.org) or `winget install Python.Python.3.12` |
| PostgreSQL | 14+ | `brew install postgresql@16` | `apt install postgresql` | [postgresql.org/download/windows](https://www.postgresql.org/download/windows/) |
| pgvector | 0.5+ | `brew install pgvector` | `apt install postgresql-16-pgvector` | [pgvector#windows](https://github.com/pgvector/pgvector#windows) |

The embedding model (BAAI/bge-small-en-v1.5, ~130 MB) downloads automatically on first use. No API keys needed.

**Windows note:** `psycopg2-binary` may require [Microsoft Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) if a prebuilt wheel is not available for your Python version.

## Usage

### CLI

```bash
# Check status
ob status

# Store a memory
ob capture "Refactored auth to use JWT tokens" --agent cc --type decision --area backend

# Semantic search
ob search "authentication approach"

# List recent memories
ob list-recent --limit 10 --agent cc

# Get pending tasks
ob pending-tasks --agent cc

# Update a task
ob update-task <UUID> --status completed --agent cc --note "Merged in PR #42"

# Agent startup context (pending tasks + blocked items + recent from other agents)
ob session-context --agent cc
```

### MCP Server (Claude Code, etc.)

Add to your agent's MCP configuration (e.g. `.claude/settings.json`):

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

**Windows note:** Use `"python"` instead of `"python3"` — standard Windows Python installs don't create a `python3` executable.

The MCP server exposes six tools: `capture_memory`, `semantic_search`, `list_recent`, `get_pending_tasks`, `update_task_status`, `get_session_context`. These appear natively in the agent's tool palette.

### File Bridge (for sandboxed agents)

Agents that can't run commands directly (sandboxed environments) can drop JSON files into an outbox directory:

```json
{
  "agent": "copilot",
  "type": "insight",
  "area": "frontend",
  "text": "Migrated state management from Redux to Zustand — 40% less boilerplate."
}
```

The bridge daemon picks up files every 60 seconds and ingests them into Open Brain.

```bash
# Run bridge once
python3 tools/ob_bridge.py

# Run as watcher (daemon)
python3 tools/ob_bridge.py --watch --interval 60
```

**Daemon setup:**
- macOS: launchd plist provided in `launchd/` directory
- Linux: systemd unit provided in `systemd/` directory (user-level, `~/.config/systemd/user/`)
- Windows: use Task Scheduler to run `python tools/ob_bridge.py --watch --interval 60`

### IM Service (inter-agent messaging)

Lightweight messaging between agents, separate from persistent memory:

```bash
# Post a message
python3 tools/im_service.py --project my_project post agent1 "Build complete, 47 tests passing"

# Read messages
python3 tools/im_service.py --project my_project read

# Read recent N messages
python3 tools/im_service.py --project my_project recent 5
```

## Configuration

Configuration lives in `~/.openbrain/` (all platforms — on Windows this is `C:\Users\<you>\.openbrain\`):

### `~/.openbrain/config.json` — Global settings

```json
{
  "db_host": "localhost",
  "db_port": 5432,
  "db_name": "open_brain",
  "embedding_model": "BAAI/bge-small-en-v1.5",
  "embedding_dimension": 384,
  "token_budget": 2000,
  "areas": ["general", "backend", "frontend", "api", "database", "infra",
            "testing", "security", "devops", "ux", "docs", "ops"]
}
```

All fields are optional — defaults are shown above.

### `~/.openbrain/projects.json` — Project registry

```json
{
  "projects": {
    "my_webapp": {
      "root": "/Users/me/projects/webapp",
      "outbox": "/Users/me/projects/webapp/ob_outbox",
      "agents": ["cc", "copilot", "cursor"]
    },
    "ml_pipeline": {
      "root": "/Users/me/projects/ml",
      "outbox": "/Users/me/projects/ml/ob_outbox",
      "agents": ["cx", "aider"]
    }
  }
}
```

### Environment variables

Any setting can be overridden with `OPEN_BRAIN_` prefix:

| Variable | Default | Description |
|---|---|---|
| `OPEN_BRAIN_DB_HOST` | `localhost` | Database host |
| `OPEN_BRAIN_DB_PORT` | `5432` | Database port |
| `OPEN_BRAIN_DB_NAME` | `open_brain` | Database name |
| `OPEN_BRAIN_TOKEN_BUDGET` | `2000` | Max tokens per MCP search response |
| `OPEN_BRAIN_CONFIG_DIR` | `~/.openbrain` | Config directory location |

## Memory Types

| Type | Use for |
|---|---|
| `session_summary` | End-of-session state capture |
| `insight` | Technical or architectural discovery |
| `decision` | Design decision with rationale |
| `task` | Action item (supports status lifecycle) |
| `blocker` | Something preventing progress |
| `review` | Code review or assessment |
| `handoff` | Context transfer between agents |

## Shell Aliases

### Bash / Zsh (macOS / Linux)

Add to `~/.zshrc` or `~/.bashrc`:

```bash
alias ob="python3 -m open_brain.cli"
alias obst="ob status"
alias obc="ob capture"
alias obs="ob search"
alias obl="ob list-recent --limit 10"
alias obp="ob pending-tasks"
alias obctx="ob session-context"
```

### PowerShell (Windows)

Add to your `$PROFILE`:

```powershell
function ob { python -m open_brain.cli @args }
function obst { ob status }
function obc { ob capture @args }
function obs { ob search @args }
function obl { ob list-recent --limit 10 }
function obp { ob pending-tasks @args }
function obctx { ob session-context @args }
```

Full alias reference with IM and bridge shortcuts: `templates/SHORTCUTS.md`.

## Architecture

```
+---------------------------------------------------------+
|                    Your Agents                          |
|  Claude Code | Codex | Copilot | Cursor | Aider | ...  |
+--------------+-------+---------+--------+-------+------+
|  MCP Server  |         CLI         |   File Bridge     |
| (JSON-RPC    | (python3 -m         | (JSON -> outbox   |
|  over stdio) |  open_brain.cli)    |  -> bridge)       |
+--------------+---------------------+-------------------+
|               Capture Pipeline                          |
|  validate -> sanitise -> embed (bge-small) -> store     |
+---------------------------------------------------------+
|        PostgreSQL + pgvector (384-dim cosine)           |
|  ob_reader (SELECT only) | ob_writer (INSERT/UPDATE)    |
+---------------------------------------------------------+
```

## Dual-System Protocol

Open Brain and the IM service are complementary:

- **Open Brain**: Persistent memory. Survives session boundaries, agent restarts, context loss. Searchable by meaning. Used for: session summaries, decisions, insights, tasks, blockers.
- **IM Service**: Real-time coordination. Rolling buffer (20 entries per stream). Used for: immediate notifications, work-in-progress updates, cross-agent requests. Not permanent — old entries auto-cull.

Both should be consulted on agent startup. Neither replaces the other.

## Database Schema

Single table, deliberately simple:

```sql
CREATE TABLE memories (
    id UUID PRIMARY KEY,
    raw_text TEXT NOT NULL,
    embedding vector(384),
    embedding_model TEXT NOT NULL DEFAULT 'BAAI/bge-small-en-v1.5',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Metadata is flexible JSONB: `source_agent`, `memory_type`, `area`, `action_status`, `assigned_to`, `priority`, plus anything else you need. Indexed with GIN for fast filtering.

## Troubleshooting

Run the diagnostic tool:

```bash
ob-doctor
```

This checks: Python version, all dependencies, PostgreSQL connectivity, pgvector extension, database schema, role permissions, embedding model, config files, and registered projects. Each check reports PASS/FAIL with specific fix instructions.

### Common issues

**"psycopg2 not found"** — Install the database driver:
```bash
pip install psycopg2-binary
```
On Windows, if this fails, install [Microsoft Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) first.

**"Database connection failed"** — PostgreSQL not running:
```bash
# macOS
brew services start postgresql@16
# Ubuntu
sudo systemctl start postgresql
# Windows
net start postgresql-x64-16
```

**"pgvector not found"** — Install the vector extension:
```bash
# macOS
brew install pgvector
# Ubuntu
sudo apt install postgresql-16-pgvector
```
Windows: see [pgvector Windows instructions](https://github.com/pgvector/pgvector#windows).

**"Role ob_reader does not exist"** — Run the setup wizard:
```bash
ob-setup
```

**Embedding model slow on first run** — The model (~130 MB) downloads on first use. Subsequent runs use the cached version (~2-3 seconds to load).

**MCP server not appearing in Claude Code** — Verify the path in your MCP config points to the correct OpenBrain directory. Restart Claude Code after changing MCP settings.

## Testing

```bash
# Run all tests (uses open_brain_test database)
OPEN_BRAIN_DB_NAME=open_brain_test python3 -m pytest open_brain/tests/ -v

# Run specific test file
OPEN_BRAIN_DB_NAME=open_brain_test python3 -m pytest open_brain/tests/test_cli.py -v
```

On Windows (PowerShell):
```powershell
$env:OPEN_BRAIN_DB_NAME = "open_brain_test"
python -m pytest open_brain/tests/ -v
```

## Supported Agents

Open Brain is agent-agnostic. Any AI coding agent that can either:
- Use MCP tools (Claude Code, Claude Desktop, compatible editors)
- Run shell commands (OpenAI Codex, GitHub Copilot in terminal, Aider, Cursor, Windsurf)
- Write files to a directory (sandboxed environments)

can use Open Brain. The setup wizard auto-detects common agents and generates wiring instructions.

## Project Structure

```
OpenBrain/
├── open_brain/            # Core Python package
│   ├── __init__.py
│   ├── config.py          # Dynamic configuration
│   ├── db.py              # PostgreSQL + pgvector operations
│   ├── capture.py         # Validate -> sanitise -> embed -> store pipeline
│   ├── sanitise.py        # Input sanitisation (prompt-injection detection)
│   ├── mcp_server.py      # MCP server (JSON-RPC over stdio)
│   ├── cli.py             # CLI interface
│   ├── im_bridge.py       # IM bridge module
│   ├── setup_wizard.py    # Interactive setup (ob-setup)
│   ├── troubleshoot.py    # Diagnostic tool (ob-doctor)
│   └── tests/             # Test suite
├── tools/
│   ├── ob_bridge.py       # File bridge daemon
│   ├── im_service.py      # Inter-agent messaging
│   └── projects.json      # Example project registry
├── templates/
│   └── SHORTCUTS.md       # Shell alias reference
├── scripts/
│   ├── install.sh         # Installer (macOS / Linux)
│   └── install.ps1        # Installer (Windows)
├── launchd/               # macOS daemon config
├── systemd/               # Linux daemon config
├── pyproject.toml         # Package metadata
├── LICENSE                # MIT
└── README.md              # This file
```

## License

MIT — see [LICENSE](LICENSE).
