# Open Brain

Persistent, verifiable memory for AI agents — from a single machine to a coordinated network. Model-agnostic, vendor-agnostic, chain-agnostic.

Open Brain gives AI agents a shared memory that survives across sessions, across agents, across machines, and across projects. Agents remember what was decided, what was tried, what worked, and what didn't. They coordinate instead of repeating each other's work. The memory is searchable by meaning, not just keywords, so an agent can ask "what did we decide about authentication?" and get the relevant decision even if the word "authentication" was never used.

The system is designed around a single architectural invariant: the memory format never changes, regardless of scale. A memory created by one agent on a laptop is structurally identical to a memory replicated across a network of cooperating nodes. What changes at each scale is only the transport layer (how memories move) and the governance layer (who is permitted to share what). This means the same tools, the same verification commands, and the same integrity guarantees apply whether you are a solo researcher or part of a distributed team. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full scale-by-scale design.

> **On methodology.** Open Brain does not claim to be correct. It claims to be falsifiable. Every architectural assertion and quality claim is treated as a hypothesis subject to deliberate refutation. The project includes a reproducible evaluation protocol for testing its own claims. See [METHODOLOGY.md](METHODOLOGY.md) for the epistemological framework, including the P-Pass process, the modular-vs-monolithic observation (N=1, honestly bounded), and the full experimental protocol.

## The Problem

AI agents are stateless. Every new session starts from zero — previous decisions, architectural choices, debugging insights, and task assignments are gone. This creates compounding failures at every level of scale:

1. **Context loss across sessions.** An agent spends the first portion of every session rediscovering what the previous session already established. On long-running projects, this cost grows with every session boundary.

2. **Uncritical compliance.** Without persistent context, agents have no basis to push back on instructions that contradict earlier decisions. They execute whatever they're told, even when the instruction conflicts with work already done. Agent directives (behavioural instructions loaded at session start) can counteract this, but only if the agent retains enough context to apply them meaningfully.

3. **Isolation between agents.** When multiple agents work on the same project — a common pattern as teams adopt different tools for different tasks — each agent operates in its own silo. Agent A's insights are invisible to Agent B. Work is duplicated, decisions diverge, and integration failures emerge late.

4. **Unverifiable reasoning.** No deployed system provides provable, timestamped, tamper-evident reasoning trails. When an agent makes a decision, there is no way to verify after the fact that the decision was made at a specific time, by a specific machine, based on specific context. GDPR Article 22 requires explanations of automated decisions; the EU AI Act demands transparency in AI reasoning. Without verifiable reasoning records, compliance is aspirational, not demonstrable.

These are not separate problems — they are the same problem (context loss and its consequences) repeating at increasing scale: within a session, across sessions, across machines, across projects, across team members, and ultimately across an entire network. Open Brain addresses the underlying problem once: agents write memories to a shared store with a format that is the same at every scale. Any agent can search them semantically or browse recent activity. The integrity layer ensures that memories are tamper-evident and attributable. The result: agents that remember, coordinate, and build on each other's work — and whose memory is independently verifiable.

## The Precision Insight

The field's trajectory for addressing context loss is bigger windows, better summarisation, smarter retrieval-augmented generation. All volume-based approaches. All hit the same selection problem: when an agent recovers from a session boundary, how does it know which memories to retrieve? Summarisation loses detail. RAG depends on the query — but the agent doesn't yet know what it needs, because it has just lost the context that would tell it.

Reasoning checkpoints invert this. A reasoning checkpoint is a memory that records what the agent was thinking, what it needed, what it was working toward, and what comes next. On recovery, the agent reloads exactly what the checkpoint identifies — not a summary, not a search result, but a precise record of the reasoning state at the moment of capture.

The checkpoint IS the retrieval query. It doesn't describe the context to be recovered — it specifies it. This is a category shift from volume (store everything, hope to find the right piece) to precision (store exactly what matters for recovery, and the storage format is the retrieval mechanism).

This is not a claim that checkpoints replace context windows or RAG. They are complementary. The claim is narrower: for the specific problem of reasoning recovery across session boundaries, precision beats volume. The falsification condition: demonstrate a volume-based approach that achieves equivalent reasoning fidelity on recovery without requiring the agent to already know what to search for.

## The Verification Chain

Open Brain does not merely store memories — it makes them evidentially trustworthy. Five cumulative layers, each adding a guarantee:

1. **Content hash** (SHA-256). Every memory is fingerprinted at creation. The hash covers both the raw text and all metadata, serialised deterministically. Any modification — even a single character — changes the hash. This is the same principle as Git commits.

2. **Hash chain**. Each memory records the content hash of the memory that preceded it. The chain makes reordering or deletion detectable: removing or rearranging a memory breaks the link. This is the same principle as blockchain block headers.

3. **Cryptographic signature** (Ed25519). If a keypair is available, the memory is signed at creation. The signature proves which machine created the memory — not by trusting the system, but by verifying the mathematics. Ed25519 is the same scheme used by SSH and Signal.

4. **Merkle epoch** (RFC 6962). Memories are sealed into time-windowed epochs using a binary Merkle tree. Any number of individual content hashes compress into a single root hash. A Merkle inclusion proof demonstrates that a specific memory was part of a specific epoch — in O(log N) space, not O(N).

5. **Blockchain anchor**. The epoch's Merkle root can be written to a public blockchain in one transaction. This provides temporal proof: the epoch (and every memory it contains) existed before the block timestamp. Verification requires only a block explorer — no Open Brain installation.

The designed end-state: any memory stored through Open Brain can be traced from its content hash, through a Merkle inclusion proof, to an on-chain anchor. The combination produces a memory that is not merely persistent but independently verifiable by anyone, anywhere, using standard cryptographic tools.

The `ob prove <UUID>` command assembles a self-contained proof package for any memory. The `ob verify-reasoning <agent>` command runs all five checks against a reasoning chain. Both produce output that a third party can verify with SHA-256, Ed25519, and a block explorer — no Open Brain required.

## The Approach

Open Brain is one component of a structured approach to human-AI collaboration, addressing the four weaknesses described above. The full approach combines three elements:

- **Persistent memory** (Open Brain) — a shared database where agents store and retrieve decisions, insights, tasks, session summaries, and coordination messages. Searchable by meaning using vector embeddings that run locally with zero API cost.

- **Agent directives** — a set of behavioural instructions loaded at session start that shape how the agent works. The directives used in developing Open Brain emphasise falsification (actively trying to disprove conclusions before presenting them), simplicity (default to the simplest sufficient solution), honesty (say "I don't know" when that's the truth), and resource discipline (flag wasteful work before executing it). This is Karl Popper's principle of falsification applied to software engineering: subject every claim, fix, and architectural choice to deliberate attempts to break it. What survives is robust; what doesn't is caught before it ships.

- **A coordination substrate** — four integrated subsystems that degrade gracefully depending on what infrastructure is available. The **IM service** provides SQLite WAL-mode messaging with full-text search, threading, delivery receipts, and retention policies — no server required. The **coordination bus** provides typed pub/sub messaging with circuit breaking, presence monitoring, and message sequencing. The **memory layer** provides semantic search via PostgreSQL and pgvector. The **crypto layer** provides Ed25519 signing and AES-256-GCM encryption. IM, bus, and crypto work with Python alone; only memory requires a database server.

Together, these compensate for the four weaknesses described above. The `templates/` directory contains example configurations for all three elements: `CLAUDE.md.example` (agent directives), `MEMORY.md.example` (project-level persistent context), `RECOVERY.md.example` (session recovery protocol), and `SHORTCUTS.md` (shell aliases). These are opt-in — Open Brain works without them, but no single component addresses all four weaknesses. Memory alone doesn't fix uncritical compliance; directives alone don't survive context loss; coordination alone doesn't fix either; and none of them provide verifiable reasoning trails without the integrity layer.

The system is built on a single foundational axiom: **all truth should be anchored and independently verifiable.** At the reasoning level, agent directives enforce Popperian falsification — claims must survive deliberate attempts to disprove them. At the data level, the verification chain (described above) enforces the same principle mechanically. None of the cryptographic primitives are novel — content hashing follows Git and Certificate Transparency; Ed25519 is the same scheme used by SSH and Signal; AES-256-GCM is the worldwide standard for authenticated encryption. The contribution is the combination and application: a shared AI memory that is not merely persistent but evidentially trustworthy. The cryptographic heritage runs through Haber and Stornetta (1991), Bitcoin's `OP_RETURN` (2014), and Certificate Transparency (RFC 6962) — the same lineage, applied to AI agent memory.

[Genesis](https://github.com/jebus197/Project_Genesis) has already proven that blockchain-as-witness works: eight constitutional anchors on Ethereum Sepolia (the [Trust Mint Log](https://github.com/jebus197/Project_Genesis/blob/main/docs/ANCHORS.md)), each a direct SHA-256 hash of the constitution embedded in an Ethereum transaction. Genesis also has a more sophisticated epoch-based commitment system that collects runtime events across four domains into per-domain Merkle trees. The `EpochAdapter` protocol bridges Open Brain's single-domain epoch infrastructure to Genesis's four-domain commitment system. The OB→Genesis bridge is not yet wired end-to-end.

The claim is falsifiable: adopt it, measure whether your outcomes change, discard what doesn't work.

## Methodology

Open Brain treats its own design claims as hypotheses. Every architectural assertion is accompanied by the conditions under which it would be false. The methodology document describes:

1. **The P-Pass process** — iterative falsification applied to engineering claims. State the claim precisely, classify constraints as HARD or SOFT, identify what would falsify the claim, actively attempt falsification, record whether the claim survives, survives with boundary conditions, or is falsified.

2. **A direct comparison** (N=1, honestly bounded) — modular vs monolithic code review during the unified architecture implementation. The modular approach produced structural process advantages (better-organised findings, systematic constraint tables). Whether it finds more bugs than monolithic review cannot be determined from one observation.

3. **A reproducible evaluation protocol** — seeded-fault methodology, 7-category bug taxonomy, 4-point scoring rubric, statistical analysis framework. Published so anyone can execute it, reproduce or refute the observation, and extend the methodology.

For the full treatment: [METHODOLOGY.md](METHODOLOGY.md). For the architectural falsification audit (7 claims tested): [ARCHITECTURE.md](ARCHITECTURE.md).

## Getting Started

### macOS / Linux

```bash
git clone https://github.com/jebus197/OpenBrain.git && cd OpenBrain && ./scripts/install.sh
```

### Windows (PowerShell)

```powershell
git clone https://github.com/jebus197/OpenBrain.git; cd OpenBrain; .\scripts\install.ps1
```

The install script checks prerequisites (Python 3.9+), creates a virtualenv, installs dependencies, and launches an interactive setup wizard. If PostgreSQL and pgvector are available, the wizard configures semantic memory search. If not, Open Brain still works — IM, bus, and crypto are fully functional with Python alone.

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

| Requirement | Version | Required for | macOS | Linux | Windows |
|---|---|---|---|---|---|
| Python | 3.9+ | Everything | `brew install python@3.12` | `apt install python3` | [python.org](https://python.org) |
| PostgreSQL | 14+ | Semantic memory only | `brew install postgresql@16` | `apt install postgresql` | [postgresql.org](https://www.postgresql.org/download/windows/) |
| pgvector | 0.5+ | Semantic memory only | `brew install pgvector` | `apt install postgresql-16-pgvector` | [pgvector](https://github.com/pgvector/pgvector#windows) |

**Python alone** gives you: IM service (SQLite WAL), coordination bus, crypto (signing/encryption), CLI, and MCP server. Adding PostgreSQL + pgvector enables semantic memory search (vector embeddings, searchable by meaning).

The embedding model (BAAI/bge-small-en-v1.5, ~130 MB) downloads automatically on first use. No API keys needed.

**Windows note:** `psycopg2-binary` may require [Microsoft Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) if a prebuilt wheel is not available for your Python version.

---

*Everything above covers what Open Brain is and how to install it. The sections below are detailed reference — consult them as needed.*

---

## Reference

### Unified API

The `OpenBrain` class provides a single entry point to four subsystems. Three work with Python alone; one requires PostgreSQL:

```python
from open_brain import OpenBrain

ob = OpenBrain(project="my_project", agent="cc")

# IM — always available (SQLite WAL-mode, no server needed)
ob.im.post("general", "Session starting")
messages = ob.im.read("general", limit=10)
results  = ob.im.search("authentication decision")

# Bus — always available (in-process asyncio, typed pub/sub)
await ob.bus.publish("memory.events", MessageType.MEMORY_CREATED, payload)
sub_id = await ob.bus.subscribe("memory.events", my_handler)

# Memory — requires PostgreSQL (graceful degradation: None when absent)
if ob.memory is not None:
    mem_id = ob.memory.capture("Refactored auth to JWT", memory_type="decision")
    results = ob.memory.search("authentication approach")

# Crypto — always available (Ed25519 key management)
if ob.crypto.has_keypair():
    signature = ob.crypto.sign(b"data to sign")
    valid = ob.crypto.verify(b"data to sign", signature)
```

**Graceful degradation:** When PostgreSQL is unavailable, `ob.memory` returns `None` instead of raising an error. All other subsystems continue working. This means Open Brain is useful even without a database — agents can still coordinate via IM and the bus, sign data, and manage keys. The `is_db_available` property reports the current state.

**Lifecycle:** For long-running processes using the coordination bus, call `await ob.start()` to begin heartbeat monitoring and `await ob.shutdown()` for graceful cleanup.

### Capabilities

- **Semantic search** — find memories by meaning, not keywords (pgvector + BAAI/bge-small-en-v1.5, 384-dimensional embeddings, runs locally, zero API cost)
- **Multi-agent coordination** — any number of agents share one brain, each identified by name
- **Structured memory types** — decisions, tasks, insights, session summaries, blockers, reviews, handoffs, reasoning checkpoints
- **Task lifecycle** — pending → in_progress → blocked → completed → cancelled, with assignments
- **Session context** — agents get pending tasks, blocked items, recent activity from other agents, and their last reasoning checkpoint on startup
- **Three access methods** — MCP server (for Claude Code and compatible agents), CLI (for everything), file bridge (for sandboxed agents)
- **IM service** — SQLite WAL-mode messaging with full-text search (FTS5), threading, delivery receipts, retention policies, and Ed25519 signing. Channels are typed, messages are content-hashed, and the schema supports TTL-based expiry
- **Coordination bus** — typed pub/sub messaging with circuit breaking, presence monitoring, and message sequencing. 15 message types across system, memory, intelligence, and task domains. Sub-millisecond dispatch (in-process asyncio, zero serialisation)
- **Graceful degradation** — IM, bus, and crypto work with Python alone. Memory requires PostgreSQL. The unified API reports availability and callers check before use — no crashes, no exceptions
- **Content integrity** — every memory is fingerprinted and chained to the one before it, so any tampering, deletion, or reordering is detectable. Uses the same content-addressing pattern as Git and Certificate Transparency (SHA-256 hash chain)
- **Cryptographic signing** — each machine can generate a keypair; when present, memories and messages are automatically signed, proving which machine created them — not just a claimed name, but a mathematically verifiable assertion (Ed25519, RFC 8032 — the same scheme used by SSH and Signal)
- **Blockchain-anchored epochs** — memories are sealed into Merkle-rooted epochs (RFC 6962 binary hash tree, odd-promotion — not Bitcoin's duplication). Each epoch compresses thousands of content hashes into a single root that can be stored in one blockchain transaction. Any individual memory can then be verified against the on-chain root in O(log N) hash computations. The blockchain-as-witness principle is already proven operationally: [Genesis](https://github.com/jebus197/Project_Genesis) has anchored its constitution eight times on Ethereum Sepolia using direct SHA-256 document hashes — each independently verifiable via [Etherscan](https://sepolia.etherscan.io/) with no software or trust required. The `EpochAdapter` protocol bridges OB's Merkle-epoch infrastructure to Genesis's four-domain commitment system, extending the same anchoring principle from single documents to entire memory epochs
- **Reasoning verification** — proof assembly (`ob prove <UUID>`) produces a self-contained proof package verifiable with SHA-256 + Ed25519 + a block explorer, no Open Brain installation required. Chain retrieval (`ob reasoning <agent>`) returns chronological reasoning checkpoints. Chain verification (`ob verify-reasoning <agent>`) runs five checks: content hash integrity, hash chain continuity, signature validity, epoch inclusion, and epoch chain. Standalone export produces JSON that a third party can independently verify
- **Blockchain anchor recording** — chain-agnostic anchor metadata storage for sealed epochs. Supports Ethereum (`tx_hash`, `block_number`, `chain_id`), OpenTimestamps (`bitcoin_block`, `ots_proof`), and RFC 3161 timestamps (`tsa_uri`, `timestamp_token`). The `proof_type` key determines the schema
- **Encrypted export** — memory exports can be passphrase-protected for secure transport between machines. The passphrase is converted to an encryption key using a deliberately slow process that resists automated guessing (AES-256-GCM encryption, NIST SP 800-38D; Scrypt key derivation, RFC 7914)
- **Portable export/import** — one memory per line, human-readable format (JSONL); fingerprints and signatures travel with the data; verify everything after import with a single command
- **Adapter protocols** — four `@runtime_checkable` Protocol classes for project integration (event, insight, threat, epoch). Projects implement them; OB never imports project code. Zero coupling by design
- **Node identity** — each machine gets a stable identifier derived from its hostname, embedded in every memory's metadata — so you can always tell where a memory originated
- **Input sanitisation** — prompt-injection pattern detection before storage
- **Role-separated database access** — reader/writer roles enforce least privilege
- **Cross-platform** — macOS, Linux, and Windows; all cryptographic primitives are platform-agnostic mathematical standards (no OS-specific dependencies)
- **Fully configurable** — agents, areas, embedding model, token budget — all adjustable per-project or globally

### Supported Agents

Open Brain is agent-agnostic. Any AI coding agent that can either:
- Use MCP tools (Claude Code, Claude Desktop, compatible editors)
- Run shell commands (OpenAI Codex, GitHub Copilot in terminal, Aider, Cursor, Windsurf)
- Write files to a directory (sandboxed environments)

can use Open Brain. The setup wizard auto-detects common agents and generates wiring instructions.

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

# Integrity and security
ob generate-keys              # Create Ed25519 keypair (enables auto-signing)
ob export out.jsonl            # Export all memories as portable JSONL
ob export out.jsonl --encrypt  # Export with AES-256-GCM encryption (prompts for passphrase)
ob import out.jsonl            # Import memories (verifies hash chain)
ob import out.jsonl --decrypt  # Import encrypted export (prompts for passphrase)
ob verify                      # Verify hash chain + signatures for all stored memories
ob migrate                     # Apply pending database migrations

# Epoch management (Merkle-sealed integrity checkpoints)
ob seal-epoch                  # Seal current state into a Merkle-rooted epoch
ob list-epochs --limit 5       # List recent epochs
ob verify-epochs               # Verify all epoch Merkle trees

# Reasoning verification
ob prove <UUID>                # Assemble self-contained proof package for a memory
ob reasoning cc                # Get chronological reasoning checkpoints for an agent
ob verify-reasoning cc         # Run 5-check verification on a reasoning chain

# IM service (inter-agent messaging — see IM section below)
ob im post general "Build complete, 47 tests passing"
ob im read general --limit 10
ob im search "authentication"
```

### IM Service (inter-agent messaging)

SQLite WAL-mode messaging with full-text search, threading, delivery receipts, and retention policies. No server needed — the database is a local file per project.

**Invocation:**

```bash
# Via the main CLI
python3 -m open_brain.cli im <command>

# Or directly
python3 -m open_brain.im <command>

# With project isolation
python3 -m open_brain.im --project my_project <command>

# With explicit database path
python3 -m open_brain.im --db-path /path/to/messages.sqlite3 <command>
```

Default database: `~/.openbrain/im/default.sqlite3`. Per-project: `~/.openbrain/im/{project}.sqlite3`.

**Commands:**

| Command | Description | Example |
|---|---|---|
| `post` | Post a message to a channel | `ob im post general "Tests passing"` |
| `action` | Post a message with type "action" | `ob im action ops "Deploy started"` |
| `read` | Read messages from a channel | `ob im read general --limit 20` |
| `recent` | Read most recent messages across all channels | `ob im recent 10` |
| `search` | Full-text search across all messages (FTS5) | `ob im search "authentication"` |
| `thread` | Read a message thread (by correlation ID) | `ob im thread <msg_id>` |
| `unread` | Show unread messages for an agent | `ob im unread --agent cc` |
| `channels` | List all channels | `ob im channels` |
| `init` | Create a new channel | `ob im init dev "Development"` |
| `clear` | Clear all messages from a channel | `ob im clear old-channel` |
| `purge` | Purge expired messages (TTL-based retention) | `ob im purge` |
| `migrate-json` | Migrate from old JSON format to SQLite | `ob im migrate-json /path/to/old/` |
| `r` | Shorthand for `read` (default channel) | `ob im r` |
| `rt` | Shorthand for `read` + `recent` together | `ob im rt` |

**Features:**
- **Content hashing** — every message is fingerprinted (`sha256:<hex>` of canonical `{sender, content, created_at}`)
- **Ed25519 signing** — messages are automatically signed when a keypair exists
- **Threading** — messages can be grouped by correlation ID for conversational threading
- **Delivery receipts** — mark messages as delivered or read, query unread counts
- **Retention policies** — per-channel TTL; `purge` removes expired messages
- **Full-text search** — FTS5 indexes on message content, searchable via `search` command
- **Channel validation** — channel IDs must match `^[a-zA-Z0-9_-]{1,64}$`

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

The MCP server exposes ten tools: `capture_memory`, `semantic_search`, `list_recent`, `get_pending_tasks`, `update_task_status`, `get_session_context`, `assemble_proof`, `get_reasoning_chain`, `verify_reasoning_chain`, `record_anchor`. These appear natively in the agent's tool palette and operate through the same facades as the CLI.

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

### Adapters (project integration)

Open Brain never imports project code. Instead, projects implement adapter protocols and register them at startup. This enforces zero coupling — OB can be used by any project without modifications.

Four `@runtime_checkable` Protocol classes are defined in `open_brain/adapters.py`:

| Adapter | Purpose | Key methods |
|---|---|---|
| `EventAdapter` | Convert project events to OB envelope payloads | `to_envelope_payload()`, `from_envelope_payload()` |
| `InsightAdapter` | Carry project insight signals on the coordination bus | `to_bus_payload()`, `validate()` |
| `ThreatAdapter` | Carry project threat signals on the coordination bus | `to_bus_payload()`, `severity_requires_human()` |
| `EpochAdapter` | Bridge project epoch/commitment events to OB epoch sealing. Genesis uses four-domain commitments (mission, trust, governance, review); OB uses single-domain Merkle. The adapter bridges them, so OB epochs can be anchored through Genesis's blockchain infrastructure | `domain_roots()`, `leaf_hashes()` |

**Registration pattern:**

```python
from open_brain import OpenBrain

ob = OpenBrain(project="project_genesis", agent="cc")
ob.register_adapter("event", GenesisEventAdapter())
ob.register_adapter("insight", GenesisInsightAdapter())
ob.register_adapter("threat", GenesisThreatAdapter())
ob.register_adapter("epoch", GenesisEpochAdapter(epoch_service))

# Retrieve later
adapter = ob.get_adapter("event")
```

The adapter protocols use `Any` for all signal/event parameters and `Dict[str, Any]` for payloads — OB never inspects project types. Each protocol documents the required payload fields in its docstring.

#### The anchoring pipeline

The `EpochAdapter` deserves specific attention because it connects OB's local integrity guarantees to externally verifiable proof. The pipeline:

1. Memories accumulate during an epoch (time window, default 1 hour)
2. `ob seal-epoch` computes a Merkle root from all memory content hashes in the window
3. The epoch links to the previous epoch's root (hash chain across epochs)
4. The `EpochAdapter` maps OB's single-domain root to the project's commitment structure
5. The project anchors the commitment to a public blockchain (one transaction per epoch)

The designed end-state: any individual memory can be traced from its content hash → epoch Merkle proof → on-chain anchor. Verification requires only SHA-256 and a block explorer — no OB installation, no project software, no trust in any party. The underlying principle is already proven: Genesis anchors its constitution to Ethereum Sepolia using direct SHA-256 document hashes (eight anchors to date, each independently verifiable via the [Trust Mint Log](https://github.com/jebus197/Project_Genesis/blob/main/docs/ANCHORS.md)). The Merkle-epoch pipeline above extends this from single documents to entire memory epochs — the infrastructure is built but the OB→Genesis bridge is not yet wired end-to-end.

### Configuration

Configuration lives in `~/.openbrain/` (all platforms — on Windows this is `C:\Users\<you>\.openbrain\`):

#### `~/.openbrain/keys/` — Ed25519 keypair (optional)

Generated by `ob generate-keys`. When present, all new memories and IM messages are automatically signed. The private key has restricted file permissions (0600 on POSIX systems). Never share the private key; the public key can be shared for signature verification on other machines.

#### `~/.openbrain/config.json` — Global settings

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

All fields are optional — defaults are shown above. Database fields are only used when PostgreSQL is available.

#### `~/.openbrain/im/` — IM databases

One SQLite database per project: `~/.openbrain/im/{project}.sqlite3`. Created automatically on first use. The database uses WAL mode for concurrent read/write access.

#### `~/.openbrain/projects.json` — Project registry

```json
{
  "projects": {
    "my_webapp": {
      "root": "/Users/me/projects/webapp",
      "outbox": "/Users/me/projects/webapp/ob_outbox",
      "agents": ["cc", "copilot", "cursor"]
    }
  }
}
```

#### Environment variables

Any setting can be overridden with `OPEN_BRAIN_` prefix:

| Variable | Default | Description |
|---|---|---|
| `OPEN_BRAIN_DB_HOST` | `localhost` | Database host |
| `OPEN_BRAIN_DB_PORT` | `5432` | Database port |
| `OPEN_BRAIN_DB_NAME` | `open_brain` | Database name |
| `OPEN_BRAIN_TOKEN_BUDGET` | `2000` | Max tokens per MCP search response |
| `OPEN_BRAIN_CONFIG_DIR` | `~/.openbrain` | Config directory location |

### Memory Types

| Type | Use for |
|---|---|
| `session_summary` | End-of-session state capture |
| `insight` | Technical or architectural discovery |
| `decision` | Design decision with rationale |
| `task` | Action item (supports status lifecycle) |
| `blocker` | Something preventing progress |
| `review` | Code review or assessment |
| `handoff` | Context transfer between agents |
| `reasoning_checkpoint` | Reasoning state at a point in time (verifiable) |

### Shell Aliases

#### Bash / Zsh (macOS / Linux)

Add to `~/.zshrc` or `~/.bashrc`:

```bash
# Core
alias ob="python3 -m open_brain.cli"
alias obst="ob status"
alias obc="ob capture"
alias obs="ob search"
alias obl="ob list-recent --limit 10"
alias obp="ob pending-tasks"
alias obctx="ob session-context"

# IM
alias obim="ob im"
alias obims="ob im search"
alias obimr="ob im read"
alias obimp="ob im post"
```

#### PowerShell (Windows)

Add to your `$PROFILE`:

```powershell
function ob { python -m open_brain.cli @args }
function obst { ob status }
function obc { ob capture @args }
function obs { ob search @args }
function obl { ob list-recent --limit 10 }
function obp { ob pending-tasks @args }
function obctx { ob session-context @args }
function obim { ob im @args }
```

Full alias reference with bridge shortcuts: `templates/SHORTCUTS.md`.

### Architecture

The diagram below shows the single-machine architecture (Scale 0–1) with all four subsystems. For the full scale-by-scale design — how this extends from one machine to a coordinated network without changing the memory format — see [ARCHITECTURE.md](ARCHITECTURE.md).

```
+---------------------------------------------------------+
|                    Your Agents                          |
|  Claude Code | Codex | Copilot | Cursor | Aider | ...  |
+--------------+-------+---------+--------+-------+------+
       |                |                 |
  MCP Server          CLI           File Bridge
  (JSON-RPC)    (open_brain.cli)   (JSON outbox)
       |                |                 |
+------v----------------v----------------v------+
|              OpenBrain Unified API             |
|  .im   .bus   .memory   .crypto   .adapters   |
+---+------+--------+---------+----------+------+
    |      |        |         |          |
+---v--+ +-v------+ |  +------v---+  +---v--------+
| IM   | | Bus    | |  | Crypto   |  | Adapters   |
| Store| | Coord. | |  | Ed25519  |  | (project   |
|------| |--------| |  | AES-GCM  |  |  protocols)|
|SQLite| |Channels| |  +----------+  +------------+
| WAL  | |Circuit |
| FTS5 | |Breaker | +---------v---------+
|Thread| |Presence| | Memory            |
|Recpt.| |Sequencr| | Capture pipeline  |
+------+ +--------+ | Embed → Store     |
                     | Hash chain → Sign |
                     +-------------------+
                     | PostgreSQL        |
                     | + pgvector        |
                     | (384-dim cosine)  |
                     +-------------------+

Degradation model:
  IM ........... always available (SQLite, no server)
  Bus .......... always available (in-process asyncio)
  Crypto ....... always available (Ed25519 key files)
  Memory ....... requires PostgreSQL (None when absent)
```

### Database Schema

**Memory store (PostgreSQL + pgvector):**

```sql
CREATE TABLE memories (
    id UUID PRIMARY KEY,
    raw_text TEXT NOT NULL,
    embedding vector(384),
    embedding_model TEXT NOT NULL DEFAULT 'BAAI/bge-small-en-v1.5',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_hash TEXT,       -- SHA-256 of canonical {raw_text, metadata}
    previous_hash TEXT,      -- Hash chain link to predecessor
    signature TEXT           -- Ed25519 signature (hex) over canonical content
);
```

Metadata is flexible JSONB: `source_agent`, `memory_type`, `area`, `action_status`, `assigned_to`, `priority`, `node_id`, plus anything else you need. Indexed with GIN for fast filtering.

**Integrity model:** `content_hash` is a fingerprint of the memory's content — if anything changes, the fingerprint won't match. `previous_hash` chains each memory to the one before it, so the entire sequence is tamper-evident (the first memory uses a fixed starting value). `signature` is the cryptographic proof that a specific machine's keypair produced this content. All three columns are optional — memories created before these features were added remain valid, they just lack verification data.

**IM store (SQLite WAL-mode):**

```sql
-- Channels
CREATE TABLE channels (
    channel_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    metadata TEXT DEFAULT '{}'
);

-- Messages (content-hashed, optionally signed)
CREATE TABLE messages (
    msg_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id),
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    msg_type TEXT NOT NULL DEFAULT 'post',
    correlation_id TEXT,           -- Threading support
    content_hash TEXT NOT NULL,    -- sha256:<hex>
    signature TEXT,                -- Ed25519 (hex)
    created_at TEXT NOT NULL,
    expires_at TEXT,               -- TTL-based retention
    metadata TEXT DEFAULT '{}'
);

-- Delivery receipts
CREATE TABLE delivery_receipts (
    receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id TEXT NOT NULL REFERENCES messages(msg_id),
    recipient TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'sent',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Retention policies (per-channel TTL)
CREATE TABLE retention_policy (
    channel_id TEXT PRIMARY KEY REFERENCES channels(channel_id),
    max_age_days INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

FTS5 full-text search index on `messages(content)` with automatic triggers for insert/delete/update.

### Testing

```bash
# Run all tests (uses open_brain_test database for memory tests)
OPEN_BRAIN_DB_NAME=open_brain_test python3 -m pytest open_brain/tests/ -v

# Run specific test file
python3 -m pytest open_brain/tests/test_im_store.py -v

# Run IM and coordination tests (no database required)
python3 -m pytest open_brain/tests/test_im_store.py open_brain/tests/test_coordination.py -v
```

On Windows (PowerShell):
```powershell
$env:OPEN_BRAIN_DB_NAME = "open_brain_test"
python -m pytest open_brain/tests/ -v
```

### Troubleshooting

Run the diagnostic tool:

```bash
ob-doctor
```

This checks: Python version, all dependencies, PostgreSQL connectivity, pgvector extension, database schema, role permissions, embedding model, config files, and registered projects. Each check reports PASS/FAIL with specific fix instructions.

#### Common issues

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

**Note:** If you don't need semantic memory search, this is not a problem — IM, bus, and crypto work without PostgreSQL.

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

### Project Structure

```
OpenBrain/
├── open_brain/                    # Core Python package
│   ├── __init__.py                # OpenBrain unified API class
│   ├── __main__.py                # python3 -m open_brain entry point
│   ├── config.py                  # Dynamic configuration + node identity
│   ├── db.py                      # PostgreSQL + pgvector operations
│   ├── capture.py                 # Validate -> sanitise -> embed -> store pipeline
│   ├── hashing.py                 # SHA-256 content hashing + hash chain verification
│   ├── crypto.py                  # Ed25519 signing + AES-256-GCM encryption
│   ├── epoch.py                   # Epoch sealing (Merkle-rooted integrity checkpoints)
│   ├── reasoning.py               # Reasoning verification (proof assembly, chain verification)
│   ├── merkle.py                  # Merkle tree implementation
│   ├── sanitise.py                # Input sanitisation (prompt-injection detection)
│   ├── mcp_server.py              # MCP server (JSON-RPC over stdio)
│   ├── cli.py                     # CLI interface (19 commands)
│   ├── adapters.py                # Adapter protocols (event, insight, threat, epoch)
│   ├── setup_wizard.py            # Interactive setup (ob-setup)
│   ├── troubleshoot.py            # Diagnostic tool (ob-doctor)
│   ├── api/                       # Facade layer
│   │   ├── im_facade.py           # IM facade (default sender injection)
│   │   ├── memory_facade.py       # Memory facade (default agent injection)
│   │   └── crypto_facade.py       # Crypto facade (OO key management)
│   ├── im/                        # IM subsystem
│   │   ├── __main__.py            # python3 -m open_brain.im entry point
│   │   ├── store.py               # SQLite WAL-mode message store
│   │   ├── service.py             # IM CLI service (14 subcommands)
│   │   └── migrate.py             # JSON-to-SQLite migration
│   ├── coordination/              # Coordination bus subsystem
│   │   ├── bus.py                 # CoordinationBus (central nervous system)
│   │   ├── channel.py             # Channel management + routing
│   │   ├── protocol.py            # Message envelope + 15 MessageType definitions
│   │   ├── sequencer.py           # Monotonic message sequencing
│   │   ├── circuit_breaker.py     # Circuit breaker for fault isolation
│   │   └── presence.py            # Node presence monitoring + heartbeat
│   └── tests/                     # Test suite (390+ tests)
├── tools/
│   ├── ob_bridge.py               # File bridge daemon
│   └── projects.json              # Example project registry
├── templates/
│   ├── CLAUDE.md.example           # Agent directive template
│   ├── MEMORY.md.example           # Project memory template
│   ├── RECOVERY.md.example         # Session recovery template
│   └── SHORTCUTS.md               # Shell alias reference
├── scripts/
│   ├── install.sh                 # Installer (macOS / Linux)
│   └── install.ps1                # Installer (Windows)
├── launchd/                       # macOS daemon config
├── systemd/                       # Linux daemon config
├── pyproject.toml                 # Package metadata
├── ARCHITECTURE.md                # Scale architecture (Scales 0–5) and design rationale
├── METHODOLOGY.md                 # Epistemological methodology and evaluation protocol
├── LICENSE                        # MIT
└── README.md                      # This file
```

## License

MIT — see [LICENSE](LICENSE).
