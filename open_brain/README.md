# open_brain — Python Package

Core package for Open Brain. Persistent, verifiable memory for AI agents — searchable by meaning, with built-in integrity verification and encrypted transport. Designed around a scale-invariant memory format: the same record structure serves a single agent on a laptop and a network of cooperating nodes. Accessible via MCP server or CLI. See [ARCHITECTURE.md](../ARCHITECTURE.md) for the full scale design.

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

## Integrity and Security

```bash
python3 -m open_brain.cli generate-keys       # Create Ed25519 keypair (one-time)
python3 -m open_brain.cli export out.jsonl     # Portable JSONL export
python3 -m open_brain.cli export e.jsonl --encrypt  # AES-256-GCM encrypted export
python3 -m open_brain.cli import e.jsonl --decrypt  # Decrypt and import
python3 -m open_brain.cli verify               # Verify hash chain + signatures
python3 -m open_brain.cli migrate              # Apply pending schema migrations
```

- **Content fingerprint**: every memory is hashed — if anything changes, the fingerprint won't match (SHA-256)
- **Hash chain**: each memory links to the one before it — tampering, deletion, or reordering is detectable
- **Cryptographic signing**: each machine can generate a keypair; when present, memories are signed automatically, proving which machine created them (Ed25519, RFC 8032 — same scheme as SSH and Signal)
- **Encrypted export**: passphrase-protected exports for secure transport between machines (AES-256-GCM; Scrypt key derivation)
- **Node identity**: stable per-machine identifier in every memory's metadata

All primitives are mathematical standards — platform-agnostic (macOS, Linux, Windows), non-proprietary.

## Database

- **Host**: localhost:5432
- **Database**: open_brain (test: open_brain_test)
- **Roles**: ob_reader (SELECT), ob_writer (INSERT/UPDATE)
- **Embedding**: BAAI/bge-small-en-v1.5 (384 dims, local, zero API cost)

## Memory Types

decision, task, session_summary, insight, blocker, review, handoff, reasoning_checkpoint

## Default Areas

general, backend, frontend, api, database, infra, testing, security, devops, ux, docs, ops

Areas are configurable in `~/.openbrain/config.json`.

## Tests

```bash
OPEN_BRAIN_DB_NAME=open_brain_test python3 -m pytest open_brain/tests/ -v
```
