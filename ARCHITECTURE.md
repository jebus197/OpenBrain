# Open Brain — Architecture

## Why This Document Exists

The [README](README.md) covers what Open Brain does and how to use it. This document covers the architectural design — specifically, how a memory system designed for a single researcher on a single machine extends, without structural change, to a network of cooperating humans and machines.

The core question: can the same memory format serve one agent on a laptop and a thousand agents across a global network? This document argues yes, describes how, and identifies what is built, what is designed but not yet implemented, and what remains speculative.

---

## The Foundational Axiom

**All truth should be anchored and independently verifiable.**

This axiom drives every design decision. At the reasoning level, it produces Popperian falsification — claims must survive deliberate attempts to disprove them. At the data level, it produces the integrity layer — every memory is fingerprinted, chained, and optionally signed, so that tampering is detectable by anyone with access, without trusting the system that produced the data.

The architectural question is: how far does this axiom scale? The answer is: it scales to any number of participants, because the verification mechanism operates on individual memory records. A single record can be verified in isolation. The chain can be verified by walking it. No central authority is required.

---

## The Scale Problem

The same fundamental problem — context loss — repeats at every level of scale:

| Scale | Problem |
|---|---|
| **0 — Single session** | The context window compacts. Decisions made earlier in the session are lost. |
| **1 — Multiple sessions** | A new session starts blank. Everything from the previous session must be recovered manually. |
| **2 — Multiple machines** | Work done on Machine A is invisible to Machine B. |
| **3 — Multiple projects** | An insight from Project A cannot inform Project B. Knowledge is siloed by project boundary. |
| **4 — Multiple users** | Team member B cannot access what team member A learned. Knowledge is siloed by person. |
| **5 — Network scale** | Collective intelligence is siloed in individual nodes. The network as a whole cannot learn from its parts. |

Each scale introduces a new boundary across which context is lost. The conventional approach is to build a separate solution for each boundary — a session cache, a database, a sync service, a team platform, a federated network. Each solution has its own data format, its own trust model, its own failure modes.

Open Brain takes a different approach: one memory format that is the same at every scale. What changes between scales is only two things:

1. **The transport layer** — how memories move between locations.
2. **The governance layer** — who is permitted to share what, and under what conditions.

The memory itself — its structure, its content hash, its chain linkage, its queryability — never changes.

---

## The Memory Unit — The Invariant

Every Open Brain memory, at every scale, is a self-describing record:

| Field | Purpose |
|---|---|
| `id` (UUID v4) | Globally unique. No collision across any number of nodes. |
| `raw_text` | The content itself. Human-readable. |
| `embedding` (384-dim vector) | Semantic position for meaning-based search. |
| `embedding_model` | Which model produced the vector (self-describing — the record carries its own provenance). |
| `content_hash` (SHA-256) | Fingerprint of the canonical content. Any change is detectable by recomputing the hash. |
| `previous_hash` (SHA-256) | Chain link to the preceding memory. Deletion or insertion is detectable. |
| `signature` (Ed25519) | Cryptographic proof of which machine's keypair produced this content. Optional — memories created before signing was enabled remain valid. |
| `metadata` (JSON) | Structured context: `memory_type`, `area`, `source_agent`, `priority`, `project`, `node_id`, `anchor_ref`, and anything else the application requires. |
| `created_at` (ISO 8601) | When the memory was created. |

**Key properties:** A memory created by a solo researcher on a single laptop is structurally identical to a memory anchored on-chain and replicated across a thousand network nodes. The format does not change. The verification depth does.

---

## Verification at Every Scale

The foundational axiom — all truth should be anchored and independently verifiable — is satisfied at every scale, with increasing verification depth:

| Layer | What it adds | When it applies |
|---|---|---|
| **Content hash** | Tampering detectable locally. Any change to content is caught by recomputing the hash. | All scales (Scale 0+) |
| **Hash chain** | Deletion and reordering detectable. Each memory links to its predecessor. Breaking the chain requires forging a hash. | All scales (Scale 0+) |
| **Cryptographic signature** | Origin provenance. The machine that created the memory can be verified mathematically, not just by a claimed name. | Scale 1+ (requires keypair) |
| **Epoch Merkle tree** | Batch verification. Thousands of memory hashes are combined into a single root hash per time period (epoch). | Scale 1+ (BUILT — `open_brain/merkle.py`, `open_brain/epoch.py`) |
| **On-chain anchor** | Externally verifiable proof. The Merkle root is stored in a blockchain transaction. Anyone can verify, without data access. | Scale 4+ (designed, not yet implemented) |
| **Trust-weighted provenance** | Source credibility assessment. Who created this memory? What is their earned trust score? | Scale 4+ (requires trust engine) |
| **Constitutional governance** | Sharing and privacy rules. What can be shared, with whom, under what conditions — enforced structurally, not by policy. | Scale 4+ (requires governance framework) |

A solo researcher uses the first three layers — free, no external dependencies. A team uses four. A blockchain-enabled network uses all seven. The memory format is the same throughout; only the verification depth changes.

### The Merkle Tree — Making the Axiom Practical

The axiom does NOT mean every memory gets its own blockchain transaction. That would be prohibitively expensive at scale. The Merkle tree is the mechanism that makes it practical.

During a time period (epoch), every memory's `content_hash` is collected as a leaf in a binary hash tree. Each pair of leaves is hashed together. Each pair of pairs is hashed together. This continues until a single root hash remains. That root — which cryptographically represents every individual memory — is stored in one blockchain transaction.

To verify any individual memory: recompute its `content_hash`, then walk the Merkle proof path (log₂(N) hash computations) to the root, and verify the root matches what is on-chain. Verifying one memory out of a million requires about 20 hash computations, not a million. The cost is logarithmic.

One transaction per epoch might anchor ten memories or ten thousand. The axiom is fully satisfied for each; the cost is bounded.

---

## Scale-Level Implementations

### Scale 0 — Single Session

**Status: BUILT (core package)**

The base case. An agent stores memories during a session. Semantic search retrieves them. Content hashing and hash chains provide local integrity verification.

This is what most AI memory tools provide. It is necessary but not sufficient — it solves context loss within a session but not across sessions, machines, projects, or people.

### Scale 1 — Multiple Sessions, Single Machine

**Status: BUILT**

The `export` command writes a JSONL snapshot (one memory per line, human-readable). The `import` command upserts into the local database. Between sessions, the memory persists in PostgreSQL. Across sessions, JSONL export via git provides version-controlled memory history.

Security provisions at this scale: Ed25519 signing (proves which machine created each memory), AES-256-GCM encrypted export (passphrase-protected for secure transport), Scrypt key derivation (resists automated guessing of passphrases). These are the building blocks for Scale 2.

### Scale 2 — Multiple Machines

**Status: DESIGNED — security primitives BUILT, transport mechanism DESIGNED**

A user has two machines. Work on one must be visible on the other.

The implementation: export on Machine A, commit and push to a shared repository, pull and import on Machine B. The `node_id` field (derived from hostname, embedded in every memory's metadata) tracks which machine originated each memory. Ed25519 signatures prove that a memory actually came from the machine it claims — not a claimed name, but a cryptographic assertion verifiable by anyone with the public key.

Encrypted export enables secure transport through untrusted channels (cloud storage, email, USB drives). The passphrase never leaves the machine; only the encrypted file travels.

This is sequential use only — one machine at a time, with explicit export/import steps. Concurrent multi-machine use requires Scale 3+ infrastructure.

### Scale 3 — Multiple Projects

**Status: BUILT**

Insights from one project should be discoverable from another.

The `project` field in metadata enables filtering. `semantic_search()` and `list_recent()` accept a `project` parameter. The CLI exposes `--project` for scoped queries. Cross-project search queries all projects simultaneously when no filter is applied. Provenance tracking records `replicated_from` and `replicated_at` on import. No architectural change was required — the memory format already supports this. The governance question (which projects should be searchable together) is configuration, not code.

### Scale 4 — Multiple Users / Team

**Status: DESIGNED**

A team shares a project. Each member has their own Open Brain instance.

Each instance has a unique `node_id`. A shared repository contains JSONL snapshots from all members. Provenance tracking records creation and replication. Conflict resolution is by UUID — the same UUID means the same memory, so concurrent imports from multiple team members produce no conflicts.

At this scale, the trust question becomes non-trivial: should memories from a new team member be weighted the same as memories from the project lead? The memory format supports this (trust metadata can be attached), but the trust evaluation engine is not yet built within Open Brain itself.

### Scale 5 — Network

**Status: SPECULATIVE (infrastructure is specifiable; emergence requires adoption)**

Nodes across a network need collective memory with trust guarantees.

JSONL becomes a replication protocol over HTTP or peer-to-peer connections. A trust engine evaluates source nodes. Governance provisions (constitutional or otherwise) determine sharing rules. Epoch Merkle trees and blockchain anchoring provide external verification — every claim is independently verifiable by anyone, without trusting the source.

This is the full satisfaction of the foundational axiom. Below Scale 5, verification requires access to the data. At Scale 5, on-chain anchoring makes verification fully public. The axiom is satisfied within the access boundary at each scale; at Scale 5, the access boundary is removed entirely.

---

## The Coordination Layer

The coordination bus (`open_brain/coordination/`) provides machine-to-machine messaging infrastructure modelled on financial market systems. The architectural parallel: an exchange matching engine + market data distribution + session management, unified behind a single gateway.

### Design Principles

| Financial Market Concept | Coordination Bus Implementation |
|---|---|
| FIX protocol | Typed envelopes with mandatory header fields (`protocol.py`) |
| Session-level sequence numbers | Monotonic per (sender, channel) pair (`sequencer.py`) |
| Exchange circuit breakers | Rate limiting + anomaly detection, three-state model (`circuit_breaker.py`) |
| Market data feeds | Broadcast channels — all subscribers receive every message (`channel.py`) |
| Order flow | Queue channels — round-robin to one subscriber per message (`channel.py`) |
| FIX sessions | Direct channels — point-to-point delivery (`channel.py`) |
| Heartbeat/session protocol | Presence protocol with join/depart lifecycle (`presence.py`) |
| End-of-day settlement | Epoch sealing with Merkle roots (`epoch.py`) |

### Performance Targets (Scale 0–1, In-Process)

- Message dispatch: < 100 microseconds (async, zero-copy, no DB on hot path)
- Throughput: > 100,000 messages/second sustained
- Sequencing: O(1) per message
- Channel routing: O(subscribers) per message

Scale 2+ adds network transport beneath the same API. The bus is transport-agnostic — it does not know or care whether messages originate locally or remotely.

### Modules

- **`protocol.py`** — `Envelope` dataclass (frozen, slots), 20 message types, `make_envelope()`, `sign_envelope()`, `verify_envelope_signature()`.
- **`sequencer.py`** — Thread-safe monotonic sequencing with gap detection.
- **`circuit_breaker.py`** — Per-node and per-channel rate limiting. Token-bucket with three-state circuit breaker (CLOSED → OPEN → HALF_OPEN). Maps to Genesis ThreatSeverity levels.
- **`channel.py`** — Three routing modes: broadcast, queue (round-robin), direct. Trust-gated dispatch (messages from nodes below trust threshold are dropped). Type filtering on subscriptions.
- **`presence.py`** — Node lifecycle management: announce, heartbeat, depart, timeout. Configurable heartbeat interval and node timeout.
- **`bus.py`** — Top-level API. Coordinates channels, sequencing, circuit breaking, and presence into a single coherent gateway. Request/reply pattern with correlated responses. Bounded audit trail.

---

## Connection to Distributed Intelligence

Open Brain is designed as standalone infrastructure — useful in isolation, at any scale, for any project. But its architecture is shaped by a specific intended deployment: as the memory and coordination substrate for [Genesis](https://github.com/jebus197/Project_Genesis), a trust-mediated network for mixed human-AI populations.

In that context, Open Brain's scale architecture directly enables two Genesis systems:

### Distributed Intelligence

Genesis is designed as a network that becomes collectively more capable through the work it coordinates. The labour market is the mechanism; distributed intelligence is the outcome. Work-derived insights propagate across the network so that each completed task enriches the context available to future tasks.

Open Brain provides the substrate: the memory format carries insights across node boundaries, semantic search makes them discoverable, and the integrity layer ensures they cannot be falsified in transit. The `InsightSignal` protocol (defined in Genesis, not in Open Brain) governs propagation; Open Brain provides the storage, indexing, and verification that the protocol depends on.

The structural principle: no entity may capture, restrict, or monopolise work-derived insights. Open Brain's open format (JSONL, standard cryptographic primitives, no proprietary dependencies) is a necessary condition for this — if the memory format were locked to a single vendor, insight propagation would be structurally capturable.

### Distributed Auto-Immune

Genesis applies distributed intelligence to self-defence: a collective immune response drawn from all network mechanisms (screening, trust gates, penalties, quality review, quarantine). The `ThreatSignal` protocol governs detection and response.

Open Brain's integrity layer is the foundation: content hashing ensures that threat reports cannot be silently altered, the hash chain ensures they cannot be deleted or reordered, and cryptographic signatures ensure they can be attributed to the node that filed them. Without verifiable memory, the auto-immune system would be susceptible to the very attacks it is designed to detect — an attacker could modify the threat database itself.

### Peer-to-Peer Architecture

Genesis is ultimately envisaged as a fully decentralised application where each user runs their own node. Open Brain's scale-invariant memory format is what makes this viable: every node stores memories in the same format, exports and imports the same JSONL, and verifies integrity using the same mathematical primitives. The transport layer at Scale 5 is peer-to-peer replication; the memory layer is unchanged from Scale 0.

This is stated intent and long-term architectural direction, not a current implementation claim.

---

## What Is Built, What Is Designed, What Is Speculative

| Component | Status | Evidence |
|---|---|---|
| Memory format (the invariant) | **BUILT** | `open_brain/capture.py`, `open_brain/db.py`, `open_brain/setup_db.sql` |
| Semantic search (pgvector, bge-small) | **BUILT** | `open_brain/db.py` — 384-dim cosine similarity, zero API cost |
| Content hashing (SHA-256) | **BUILT** | `open_brain/hashing.py` — canonical JSON, hash chain, genesis hash |
| Hash chain verification | **BUILT** | `open_brain/hashing.py`, `open_brain/cli.py verify` |
| Ed25519 signing | **BUILT** | `open_brain/crypto.py` — per-node keypair, auto-sign on storage |
| AES-256-GCM encrypted export | **BUILT** | `open_brain/crypto.py` — Scrypt KDF, authenticated encryption |
| Node identity | **BUILT** | `open_brain/config.py` — hostname-derived, embedded in metadata |
| JSONL export/import | **BUILT** | `open_brain/cli.py export/import`, `open_brain/db.py` |
| MCP server | **BUILT** | `open_brain/mcp_server.py` — six tools, JSON-RPC over stdio |
| CLI | **BUILT** | `open_brain/cli.py` — full command set |
| File bridge | **BUILT** | `tools/ob_bridge.py` — JSON drop for sandboxed agents |
| IM service | **BUILT** | `tools/im_service.py` — rolling buffer, file-locked |
| Coordination bus | **BUILT** | `open_brain/coordination/` — typed envelopes, monotonic sequencing, circuit breakers, channel routing (broadcast/queue/direct), presence protocol, request/reply. 54 tests |
| Provenance tracking (Scale 2+) | **BUILT** | `open_brain/db.py` — `import_memory()` records `replicated_from`, `replicated_at` |
| Cross-machine transport (Scale 2) | **DESIGNED** | Security primitives built; git-based transport is manual workflow |
| Cross-project search (Scale 3) | **BUILT** | `open_brain/db.py` — `project` filter on `semantic_search()` and `list_recent()`, `open_brain/cli.py --project` flag |
| Team replication (Scale 4) | **DESIGNED** | Node identity + JSONL replication protocol specified |
| Epoch Merkle tree | **BUILT** | `open_brain/merkle.py` (RFC 6962), `open_brain/epoch.py` (seal/verify/prove), `open_brain/migrations/003_epochs.sql`, 20 tests |
| On-chain anchoring | **DESIGNED** | Architecture specified; Genesis has anchoring infrastructure |
| Trust-weighted provenance | **DESIGNED** | Memory format supports trust metadata; trust engine is in Genesis |
| Constitutional governance | **DESIGNED** | Governance framework exists in Genesis; OB integration not yet built |
| P2P replication (Scale 5) | **SPECULATIVE** | Requires network adoption; infrastructure is specifiable |
| Collective intelligence emergence | **SPECULATIVE** | Infrastructure is specifiable; emergence requires adoption and cannot be guaranteed by design |

---

## P-Pass on the Architecture

The architecture itself is subjected to the same falsification methodology that governs the project (see [METHODOLOGY.md](METHODOLOGY.md) for the general protocol, a reproducible evaluation framework, and the epistemological commitments underpinning these tests). Each claim below is stated precisely, a falsification path is identified, and the outcome is recorded with boundary conditions. The following falsification attempts have been assessed:

**1. Embedding model changes break compatibility.**
The format includes the `embedding_model` field. Import detects mismatches between source and destination models. Re-embedding is lazy and preserves the original vector. The format is self-describing — it carries its own model identifier. **Survives.**

**2. UUID collision across millions of nodes.**
UUID v4 collision probability is approximately 10⁻¹⁸ at 10¹² entries. Not a practical concern at any foreseeable scale. **Survives.**

**3. JSONL does not scale for billion-memory exports.**
Valid at Scale 5. Mitigated by incremental export (only new memories since last export). Full snapshot is bootstrap only. **Survives with mitigation.**

**4. PostgreSQL is heavy for solo researchers.**
Valid. SQLite with sqlite-vss is a lighter alternative for Scales 0–2. The JSONL format is database-agnostic — it does not depend on PostgreSQL. **Survives with design note.**

**5. "Global Mind" is unfalsifiable marketing.**
Partially valid. The infrastructure — memory format, transport, verification, governance — is fully specifiable and testable. Whether a network built on this infrastructure exhibits emergent collective intelligence is a claim about adoption and behaviour, not architecture. The term should be understood as an aspirational label describing the intended direction, not as an engineering claim about guaranteed outcomes. The architecture is falsifiable (build it, measure whether collective capability increases with scale); the emergence is [SPECULATIVE]. **Survives with boundary noted.**

**6. Content hashes at Scale 0–2 are "anchoring theatre."**
Valid observation about scope — at low scales, the only verifier is the data owner. But hashes give reproducibility: "this is the exact claim I made on this date, unchanged since." This is useful for academic provenance, personal audit trails, and replication studies. The cost is negligible (one SHA-256 computation per memory). The value is deferred but real. **Survives.**

**7. Scale-invariance claimed, but the axiom is only fully satisfied at Scale 4+.**
Partially valid. Below Scale 4, verification requires data access — you must have the JSONL or the database to verify the chain. Above Scale 4, on-chain anchoring makes verification fully public. The axiom is satisfied within the access boundary at each scale. This is a narrowing of scope, not a violation. **Survives with boundary noted.**

---

## Terminology Note

The phrase "Global Mind" appears in early design documents as an aspirational label for what Scale 5 might eventually produce: a network where the collective capability exceeds any individual node's capability, and where that collective capability is grounded in verifiable memory rather than opaque model weights.

This document avoids the term in favour of precise descriptions of what each scale provides. The infrastructure is specifiable and falsifiable. Whether it produces something that deserves the label "collective intelligence" depends on adoption, participation quality, and governance effectiveness — none of which can be determined by architecture alone.

The honest framing: Open Brain provides the memory substrate. Genesis provides the coordination framework. Whether the combination produces emergent collective capability at network scale is a hypothesis, not a claim. The architecture is designed to make the hypothesis testable.

---

## Further Reading

- [README](README.md) — what Open Brain does and how to install it
- [METHODOLOGY.md](METHODOLOGY.md) — epistemological methodology and evaluation protocol
- [open_brain/README.md](open_brain/README.md) — package-level reference
- [templates/SHORTCUTS.md](templates/SHORTCUTS.md) — shell aliases and common workflows
