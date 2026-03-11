# Open Brain — White Paper

**Persistent, Verifiable Memory for AI Agents**

Version 1.0 — March 2026

---

## Abstract

AI agents lose context. Every session starts blank; every compaction discards reasoning; every machine boundary severs continuity. The field's response — bigger windows, better summarisation, smarter retrieval — addresses the volume of context recovery but not its precision. Open Brain (OB) inverts this: rather than recovering more context, it recovers the right context, through reasoning checkpoints that serve as both the record of what was thought and the query for what must be retrieved. Each checkpoint is anchored by a five-layer verification chain — content hash (SHA-256), hash chain (tamper detection), Ed25519 signature (machine attribution), Merkle epoch (batch proof), and blockchain anchor (temporal proof) — producing memories that are not merely persistent but evidentially trustworthy. Any individual memory is independently verifiable with SHA-256, Ed25519, and a block explorer. No Open Brain installation is required for verification. The system is model-agnostic (any LLM), chain-agnostic (any blockchain), and scale-invariant (the same memory format serves a single researcher and a thousand-node network). This paper specifies every schema element, formalises the verification chain, and accompanies each claim with the conditions under which it would be false.

---

## 1. Introduction

### 1.1 The Context Loss Problem

Large language models operate within a finite context window. When that window fills, prior content is compressed or discarded. This produces a specific failure mode: the agent's earlier reasoning — its decisions, its constraints, its working state — becomes inaccessible. The agent does not merely forget facts; it loses the thread of its own thought.

This failure repeats at every level of scale:

| Scale | Boundary | Context lost |
|---|---|---|
| Single session | Context window compaction | Decisions made earlier in the session |
| Multiple sessions | Session boundary | Everything from the previous session |
| Multiple machines | Machine boundary | Work done on another machine |
| Multiple projects | Project boundary | Insights from other projects |
| Multiple users | Person boundary | Knowledge held by other team members |
| Network scale | Node boundary | Collective intelligence of the network |

Each boundary introduces a discontinuity. The conventional response is to build a separate solution for each: a session cache, a database, a sync service, a team platform, a federated network. Each solution has its own data format, its own trust model, its own failure modes.

### 1.2 Existing Approaches and Their Limits

The field has pursued three strategies for context persistence:

**Bigger context windows.** Models with 100K, 200K, or 1M token windows defer the compaction problem but do not eliminate it. Every window has a boundary. The approach is an engineering race against a mathematical certainty: sufficiently long tasks will always exceed any fixed window.

**Retrieval-augmented generation (RAG).** External documents are chunked, embedded, and retrieved by semantic similarity. This solves the storage problem — there is no upper bound on the corpus — but introduces the selection problem. Semantic similarity is a weak proxy for relevance. The system retrieves what is textually similar, not what is logically necessary. A reasoning step about a specific architectural constraint may share no vocabulary with the prior step that established that constraint.

**Summarisation and compression.** The context window is periodically summarised. Summaries are compact but lossy: the specific detail that will be needed later is often exactly the detail that was compressed away. Summarisation optimises for generality; reasoning recovery requires specificity.

All three approaches operate on the volume dimension — they attempt to provide more context, or to compress context more efficiently. None addresses the precision dimension: which specific prior reasoning is needed to continue the current task?

### 1.3 The Precision Insight

Reasoning checkpoints invert the retrieval problem. Instead of recovering everything the agent said and selecting what matters, a checkpoint records what the agent was thinking — what problem it was solving, what constraints it was working under, what it had decided and why. On recovery, the checkpoint serves as the retrieval query. It identifies exactly what must be loaded because it was written at the moment the agent understood what mattered.

This is a category shift from volume to precision. RAG asks: "What in the corpus is textually similar to the current query?" A reasoning checkpoint asks: "What was I thinking when I last worked on this, and what did I need?" The checkpoint IS the retrieval query — not a passive record to be searched, but an active specification of what to recover.

The practical consequence: an agent recovering from a reasoning checkpoint does not need a large context window full of potentially relevant material. It needs the checkpoint itself (which specifies the working state) and the specific memories the checkpoint identifies. The context is minimal and precisely targeted.

**Falsification condition:** The precision insight fails if checkpoint-based recovery produces worse task continuation quality than full-context retrieval for a representative sample of multi-session tasks. The checkpoint approach claims precision superiority, not volume superiority — the test must measure continuation coherence, not total information recovered.

### 1.4 Unverifiable Reasoning

Beyond the precision problem lies a trust problem. No deployed system provides provable, timestamped, tamper-evident reasoning trails. An agent claims it made a decision for a particular reason. The claim is stored as text. Nothing prevents the text from being altered after the fact. Nothing proves the text existed at the time claimed. Nothing ties the text to the specific machine or agent that produced it.

This is not a theoretical concern. GDPR Article 22 requires explanation of automated decisions affecting individuals. The EU AI Act (2024) mandates transparency in AI reasoning for high-risk applications. Both requirements presuppose that AI reasoning can be retrieved, inspected, and trusted — that the explanation provided is the explanation that was actually produced, not a post-hoc reconstruction. No deployed system satisfies this requirement with cryptographic guarantees.

Open Brain's verification chain addresses this directly: each memory is content-hashed (proves immutability), chain-linked (proves ordering), signed (proves origin), epoch-grouped (proves batch inclusion), and optionally blockchain-anchored (proves temporal existence). The combination produces a reasoning trail that is not merely persistent but evidentially trustworthy.

---

## 2. Architecture

### 2.1 The Memory Unit — The Invariant

Every Open Brain memory, at every scale, is a self-describing record with nine fields:

| Field | Type | Purpose |
|---|---|---|
| `id` | UUID v4 | Globally unique identifier. No collision risk at any foreseeable scale (collision probability ~10^-18 at 10^12 entries). |
| `raw_text` | Text | The memory content itself. Human-readable. |
| `embedding` | 384-dim float vector | Semantic position for meaning-based search. Model: `BAAI/bge-small-en-v1.5`. |
| `embedding_model` | Text | Which model produced the vector. Self-describing — the record carries its own provenance. |
| `content_hash` | `sha256:<hex>` | SHA-256 fingerprint of canonical content. Any change is detectable by recomputing the hash. |
| `previous_hash` | `sha256:<hex>` | Chain link to the preceding memory. Deletion or insertion is detectable. |
| `signature` | Hex string (128 chars) | Ed25519 signature proving which machine's keypair produced this content. |
| `metadata` | JSON | Structured context: `memory_type`, `area`, `source_agent`, `priority`, `project`, `node_id`, and application-specific fields. |
| `created_at` | ISO 8601 | When the memory was created. |

**The invariance property:** A memory created by a solo researcher on a single laptop is structurally identical to a memory anchored on-chain and replicated across a thousand network nodes. The format does not change. Only the verification depth changes.

**Falsification condition:** The invariant fails if a use case at any scale requires a structural change to the memory format (adding mandatory fields, changing the hash domain, or altering the chain linkage). Optional metadata extensions do not falsify the invariant — they are carried within the existing `metadata` JSON field.

### 2.2 Four Subsystems

Open Brain comprises four subsystems with distinct dependency profiles:

| Subsystem | Purpose | Dependencies |
|---|---|---|
| **Instant Messaging (IM)** | Rolling-buffer inter-agent messaging | Python standard library only (SQLite WAL) |
| **Coordination Bus** | Typed envelope routing, sequencing, circuit breaking | Python standard library only |
| **Memory** | Storage, search, hash chain, export/import | PostgreSQL + pgvector |
| **Crypto** | Ed25519 signing, AES-256-GCM encryption, Merkle trees | `cryptography` library (wraps OpenSSL) |

### 2.3 Graceful Degradation

The subsystems degrade independently. If PostgreSQL is unavailable, the IM service and coordination bus continue operating. If the `cryptography` library is not installed, memories are stored without signatures — content hashing still works (Python's `hashlib` is standard library). If no blockchain is available, Merkle epochs still provide batch verification locally.

The degradation hierarchy:

| Available | Verification capability |
|---|---|
| Python only | IM messaging, coordination bus, content hashing, hash chain |
| + `cryptography` | Ed25519 signing, AES-256-GCM encrypted export |
| + PostgreSQL + pgvector | Persistent memory, semantic search, full CLI |
| + blockchain | On-chain anchoring, public verifiability |

**Falsification condition:** Graceful degradation fails if removing any single dependency causes a subsystem outside its dependency chain to fail.

### 2.4 Three Access Interfaces

Open Brain exposes three access interfaces, all backed by the same storage and verification layer:

1. **CLI** (`open_brain/cli.py`) — Command-line interface for human operators. Full command set including `capture`, `search`, `export`, `import`, `verify`, `prove`, `reasoning`, `verify-reasoning`.

2. **MCP Server** (`open_brain/mcp_server.py`) — Model Context Protocol server for AI agents. JSON-RPC over stdio. Ten tools: `capture_memory`, `semantic_search`, `list_recent`, `get_pending_tasks`, `update_task_status`, `get_session_context`, `assemble_proof`, `get_reasoning_chain`, `verify_reasoning_chain`, `record_anchor`.

3. **File Bridge** (`tools/ob_bridge.py`) — JSON file drop for sandboxed agents that cannot make network connections. Agent writes a JSON file; the bridge reads, validates, and stores it.

All three interfaces enforce the same constraints: memory type validation, area validation, token budget throttling, content hashing, and chain linking. The verification chain is applied identically regardless of how the memory enters the system.

---

## 3. Reasoning Checkpoints

### 3.1 What They Are

A reasoning checkpoint is an Open Brain memory with `memory_type` set to `reasoning_checkpoint`. It has the same structure as any other memory — the same nine fields, the same content hash, the same chain linkage. What distinguishes it is not format but intent: it captures what the agent was thinking at a specific moment, not just what it produced.

The valid memory types in Open Brain (structural, not project-specific):

| Type | Purpose |
|---|---|
| `decision` | A decision made, with rationale |
| `task` | A work item with action status |
| `session_summary` | End-of-session state capture |
| `insight` | A discovered pattern or principle |
| `blocker` | An obstacle preventing progress |
| `review` | A review finding or assessment |
| `handoff` | Context transfer between agents |
| `reasoning_checkpoint` | What the agent was thinking, working on, and why |

### 3.2 The Checkpoint-as-Retrieval-Query Mechanism

When an agent stores a reasoning checkpoint, the `raw_text` field contains the agent's current working state: what problem it was solving, what approach it was taking, what constraints it had identified, what remained to be done. The `metadata` field contains structured context: `source_agent`, `session_id`, `project`, `area`, `priority`.

On recovery, the agent retrieves its most recent reasoning checkpoints for the current context (agent + project + area). Each checkpoint's `raw_text` is a natural language description of a working state — which is precisely what semantic search needs as a query. The checkpoint does not just describe what was stored; it specifies what must be retrieved.

The recovery workflow:

1. Agent starts a new session.
2. `get_session_context(agent)` returns pending tasks, blocked tasks, recent activity from other agents, and the agent's last session summary.
3. `get_reasoning_chain(agent, session_id)` returns chronological reasoning checkpoints from the previous session.
4. Each checkpoint's `raw_text` serves as a semantic search query, retrieving the specific memories the agent needed when it wrote the checkpoint.
5. The agent reconstructs its working state from the checkpoints and retrieved memories, not from a full context dump.

### 3.3 Checkpoint Frequency

How many reasoning checkpoints should an agent store per session? Too few, and the working state is not adequately captured. Too many, and the checkpoints become noise — a transcript, not a summary.

The practical range is N in [2, 10] per session, with a sweet spot at [3, 7]:

- **N = 1:** Equivalent to a session summary. Captures the final state but not the reasoning trajectory.
- **N = 2-3:** Captures start state, key decision point(s), and end state. Minimal but often sufficient for short sessions.
- **N = 3-7:** Captures the reasoning trajectory: problem identification, approach selection, intermediate findings, decision points, conclusion. This range balances precision against storage cost.
- **N = 8-10:** Appropriate for long, complex sessions with multiple decision points.
- **N > 10:** Approaches transcript density. The checkpoints lose their function as summaries and become raw logs.

The cost is negligible: each checkpoint is one memory record (~1-2 KB including embedding). Ten checkpoints per session at 100 sessions is 1000 records — well within any storage budget.

**Falsification condition:** The frequency model fails if empirical testing shows that checkpoint-based recovery quality is not monotonically improving in the range [1, 7] and plateaus or degrades thereafter. The prediction is diminishing returns, not strict monotonicity — but zero improvement from N=1 to N=5 would falsify the model.

---

## 4. The Verification Chain

Open Brain's verification chain consists of five cumulative layers. Each layer adds a specific guarantee. The combination produces a memory that is not merely persistent but evidentially trustworthy.

Plain-language summary before the formal specifications: a content hash proves the memory has not been changed. The hash chain proves no memories have been deleted or reordered. The signature proves which machine created the memory. The Merkle epoch proves the memory belongs to a specific batch. The blockchain anchor proves the batch existed at a specific time. Together, these five proofs make a memory independently verifiable by anyone — with standard cryptographic tools, no Open Brain installation required.

### 4.1 Layer 1: Content Hashing (SHA-256)

**What it proves:** The memory content has not been altered since it was created.

**Plain language:** A fingerprint of the memory. If anyone changes even one character, the fingerprint will not match. Recalculating the fingerprint requires only the memory content and SHA-256 — no secret keys, no special software.

**Formal specification:**

The content hash is computed over a canonical JSON representation of the memory's content fields:

```
canonical = json.dumps(
    {"raw_text": raw_text, "metadata": metadata},
    sort_keys=True,
    separators=(",", ":"),
)
content_hash = "sha256:" + SHA-256(canonical.encode("utf-8")).hexdigest()
```

**Canonical form properties:**
- Keys are sorted alphabetically (`sort_keys=True`).
- No whitespace in separators (`separators=(",", ":")`).
- Encoding is UTF-8.
- Output is prefixed with `sha256:` followed by 64 hexadecimal characters.
- Deterministic: the same `raw_text` and `metadata` always produce the same hash.

**What is hashed and what is excluded:**

| Included | Reason |
|---|---|
| `raw_text` | The memory content itself |
| `metadata` | Structured context (memory_type, area, source_agent, etc.) |

| Excluded | Reason |
|---|---|
| `embedding` | Derived data — computed from raw_text, not independent content |
| `created_at` | Temporal metadata — when it was stored, not what was stored |
| `id` | Address — where it lives, not what it is |

The exclusions are deliberate: a memory re-embedded with a different model, imported at a different time, or stored at a different UUID retains the same content hash. The hash anchors the content, not its container.

**Genesis sentinel:** The first memory in a chain has `previous_hash` set to the genesis sentinel:

```
GENESIS_HASH = "sha256:genesis"
```

This is a conventional value (not a hash of anything). It marks the chain origin and is checked by chain verification.

**Verification:** Recompute the hash from `raw_text` and `metadata` using the canonical form above. Compare with the stored `content_hash`. Match means the content is unaltered. Mismatch means tampering, corruption, or a serialisation error.

**Falsification condition:** Content hashing fails if SHA-256 produces collisions for distinct canonical JSON inputs at any rate above the theoretical bound (~2^-128 for random collisions). This is a property of SHA-256 itself, not of OB's implementation.

### 4.2 Layer 2: Hash Chain

**What it proves:** No memories have been deleted or reordered. Every memory links to its predecessor by content hash.

**Plain language:** Each memory points to the fingerprint of the memory before it. If someone deletes a memory, the chain breaks — the next memory points to a fingerprint that no longer exists. If someone inserts a memory, the chain breaks — the inserted memory's predecessor link does not match the actual preceding memory's fingerprint.

**Formal specification:**

Each memory stores a `previous_hash` field containing the `content_hash` of the immediately preceding memory (ordered by `created_at ASC`). The first memory in the chain stores `GENESIS_HASH` ("sha256:genesis").

Chain verification walks the ordered memory list and checks two properties for each memory:

1. **Content integrity:** `content_hash` matches the recomputed hash of `raw_text` + `metadata`.
2. **Chain continuity:** `previous_hash` matches the `content_hash` of the preceding memory.

The verification function returns:

```
{
    "total": int,              # Total memories examined
    "valid": int,              # Memories with correct content hash
    "broken_content": [...],   # Memories where content hash does not match
    "broken_chain": [...],     # Memories where previous_hash does not match predecessor
    "unhashed": int            # Pre-migration memories without content_hash
}
```

**Properties:**
- Verification is O(N) — one pass over the ordered memory list.
- Single deletion is detectable (the successor's `previous_hash` will not match).
- Single insertion is detectable (the inserted memory's `previous_hash` will not match the actual predecessor).
- Reordering is detectable (chain links will not match after the reordered segment).

**Boundary condition:** Hash chain verification detects tampering but does not prevent it. An adversary with database write access can recompute all hashes from the point of modification forward, producing a valid but altered chain. Layer 3 (signatures) and Layer 5 (blockchain anchoring) close this gap.

**Falsification condition:** The hash chain fails to detect tampering if a single deletion or insertion in a chain of N memories produces no broken link in the verification output.

### 4.3 Layer 3: Cryptographic Signature (Ed25519)

**What it proves:** The memory was created by the holder of a specific Ed25519 private key.

**Plain language:** Each machine has a unique cryptographic key pair (like a wax seal). The machine stamps each memory with its private key. Anyone with the corresponding public key can verify the stamp. Forging the stamp requires the private key, which never leaves the machine.

**Formal specification:**

**Algorithm:** Ed25519 (RFC 8032). The same algorithm used by SSH, Signal, and WireGuard. Deterministic signatures (no random nonce), 64-byte output.

**Key management:**
- Keys are stored at `~/.openbrain/keys/` with restricted permissions:
  - Directory: `0o700` (owner only)
  - Private key: `0o600` (owner read/write only)
- Private key format: PEM (PKCS8), unencrypted (protected by filesystem permissions and OS-level disk encryption).
- Public key format: PEM (SubjectPublicKeyInfo), shareable.
- Key generation: `Ed25519PrivateKey.generate()` via Python's `cryptography` library (wraps OpenSSL).
- Accidental rotation prevention: `generate_keypair()` raises `FileExistsError` if keys already exist. Explicit `force=True` required to regenerate (which invalidates all existing signatures from this node).
- One keypair per node. The `node_id` (derived from hostname: `node-<12-char-SHA256-hex>`) identifies the node; the keypair proves it.

**Signing:**
- Signs the same canonical JSON used for content hashing: `json.dumps({"raw_text": ..., "metadata": ...}, sort_keys=True, separators=(",", ":")).encode("utf-8")`.
- Output: 128 hexadecimal characters (= 64 bytes, the standard Ed25519 signature size).
- Signing is automatic on memory storage (when a keypair exists).

**Verification:**
- Reconstruct the canonical JSON from `raw_text` and `metadata`.
- Decode the hex signature to 64 bytes.
- Verify against the signer's public key using Ed25519 verification.
- Returns `True` (valid) or `False` (signature does not match content or key).

**What the signature covers:** The signature covers exactly the same data as the content hash — `raw_text` and `metadata` in canonical JSON form. This means the signature and the content hash are cryptographically bound: if the content changes, both the hash and the signature become invalid independently.

**Falsification condition:** Ed25519 signing fails to provide origin proof if an adversary can forge a valid signature without the private key. This requires breaking Ed25519's discrete logarithm hardness on the Edwards curve — a problem believed to be computationally infeasible on classical hardware.

### 4.4 Layer 4: Merkle Epoch

**What it proves:** A memory belongs to a specific batch of memories created during a specific time period, and its inclusion in the batch is verifiable with O(log N) hash computations.

**Plain language:** Every hour, all memory fingerprints from that hour are combined into a tree structure that produces a single root value. That root represents every memory in the batch. To prove any one memory is in the batch, you need only a short path through the tree (about 20 steps for a million memories) — not the entire batch.

**Formal specification:**

**Tree construction (RFC 6962 — Certificate Transparency):**

The Merkle tree is a binary hash tree over the `content_hash` values of memories within an epoch window.

- **Leaf nodes:** The `content_hash` values, in `created_at ASC` order.
- **Internal nodes:** `SHA-256(left_child_bytes || right_child_bytes)`. Raw bytes are concatenated (not hex strings), then hashed.
- **Odd leaf count:** The last leaf is promoted to the next level without hashing. This follows RFC 6962 and avoids the second-preimage vulnerability present in Bitcoin's Merkle tree construction (which duplicates the last leaf).
- **Hash format:** All hashes use the OB canonical format: `sha256:<hex>`.
- **Hash pair computation:**
  ```
  _hash_pair(left, right):
      combined = parse_hex(left) + parse_hex(right)
      return "sha256:" + SHA-256(combined).hexdigest()
  ```
- **Root computation:** Iterative level-by-level reduction until one hash remains. A single leaf returns itself. An empty list returns `None`.

**Epoch windowing:**

- **Window size:** Configurable. Default: 3600 seconds (1 hour). Environment variable: `OPEN_BRAIN_EPOCH_WINDOW_S`.
- **Alignment:** Windows align to UTC midnight and tile forward in `window_s` increments.
  ```
  midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
  elapsed = (dt - midnight).total_seconds()
  window_index = int(elapsed // window_s)
  start = midnight + timedelta(seconds=window_index * window_s)
  end = start + timedelta(seconds=window_s)
  ```
- **Non-overlapping:** A memory belongs to exactly one epoch, determined by its `created_at` timestamp.
- **Sealing:** Sealing an epoch computes the Merkle root from all memories in the window. Sealing is idempotent — re-sealing the same window produces the same root (enforced by `ON CONFLICT DO NOTHING`).

**Epoch record:**

| Field | Type | Description |
|---|---|---|
| `epoch_id` | UUID | Unique identifier for this sealed epoch |
| `window_start` | ISO 8601 | Start of the epoch window |
| `window_end` | ISO 8601 | End of the epoch window |
| `merkle_root` | `sha256:<hex>` | Root hash of the Merkle tree |
| `memory_count` | Integer | Number of memories in this epoch |
| `leaf_hashes` | JSON array | Ordered list of `content_hash` values |
| `previous_epoch_root` | `sha256:<hex>` | Chain link to the preceding epoch's root |
| `sealed_at` | ISO 8601 | When this epoch was sealed |
| `sealed_by` | Text | `node_id` of the sealing node |
| `anchored_at` | ISO 8601 (nullable) | When this epoch was blockchain-anchored |
| `anchor_metadata` | JSONB (nullable) | Chain-agnostic anchor details |

**Epoch chain:** Each epoch's `previous_epoch_root` contains the `merkle_root` of the preceding epoch. The first epoch uses the genesis sentinel:

```
GENESIS_EPOCH_ROOT = "sha256:epoch_genesis"
```

This creates a hash-linked chain of epochs, analogous to the hash chain of individual memories. Epoch chain verification walks the sequence and checks that each `previous_epoch_root` matches the preceding epoch's `merkle_root`.

**Inclusion proofs:**

An inclusion proof for a memory at leaf index `i` in an epoch of `N` leaves consists of O(log N) `(sibling_hash, direction)` tuples:

- `direction = LEFT (0)`: sibling is to the left — compute `hash(sibling || current)`.
- `direction = RIGHT (1)`: sibling is to the right — compute `hash(current || sibling)`.

Verification walks the proof from leaf to root:

```
current = leaf_hash
for sibling, direction in proof:
    if direction == LEFT:
        current = hash_pair(sibling, current)
    else:
        current = hash_pair(current, sibling)
return current == expected_root
```

This is a pure function — no database access, no OB installation required. A third party can verify inclusion with only the proof, the leaf hash, and the expected root.

**Auto-boundary detection:** `prove_memory(content_hash, created_at)` parses the `created_at` timestamp, computes the epoch window boundaries using `_align_window()`, and delegates to `prove_inclusion()`. This eliminates manual window boundary computation for callers.

**Falsification condition:** The Merkle tree fails to provide batch verification if a valid inclusion proof can be constructed for a leaf that is not in the original leaf set. This would require a collision or second-preimage attack on SHA-256 — infeasible on classical hardware.

### 4.5 Layer 5: Blockchain Anchor

**What it proves:** The Merkle root (and therefore every memory in the epoch) existed at the time the blockchain transaction was confirmed.

**Plain language:** The batch fingerprint is written into a blockchain transaction. Anyone can look up the transaction and see the fingerprint. The blockchain's own consensus mechanism proves when the transaction was confirmed. This gives every memory in the batch a timestamp that no single party can forge.

**Formal specification:**

**Chain-agnostic design:** Anchor metadata is stored as JSONB with a `proof_type` key that determines the schema. Known proof types:

| `proof_type` | Fields | Chain |
|---|---|---|
| `ethereum` | `tx_hash`, `block_number`, `chain_id`, `verifier_uri` | Ethereum / EVM-compatible |
| `ots` | `bitcoin_block`, `ots_proof` | Bitcoin (via OpenTimestamps) |
| `rfc3161` | `tsa_uri`, `timestamp_token` | RFC 3161 TSA (any compliant authority) |

**Recording an anchor:** `record_anchor(epoch_id, anchored_at, anchor_metadata)` updates a sealed epoch with anchor information. The update is conditional: `WHERE anchored_at IS NULL` prevents double-anchoring.

**Unanchored epoch retrieval:** `get_unanchored_epochs()` returns sealed epochs that have not yet been anchored, ordered by `window_end ASC` (oldest first). This provides the queue for an anchoring service.

**The designed end-state:**

```
Memory → content_hash → Merkle leaf → inclusion proof → epoch root → on-chain tx
```

A verifier traces this path in reverse: look up the transaction on-chain, extract the Merkle root, verify the inclusion proof, verify the content hash. Each step uses a standard algorithm (SHA-256, Ed25519, Merkle tree traversal, block explorer lookup). No trust in the Open Brain system is required.

**Current implementation status:** The epoch infrastructure is fully built within Open Brain (`merkle.py`, `epoch.py`, `EpochAdapter`). On-chain anchoring is operational in the Genesis project (8 constitutional anchors on Ethereum Sepolia). The OB-to-Genesis bridge (`EpochAdapter`) is designed but not yet wired end-to-end.

**Falsification condition:** Blockchain anchoring fails to provide temporal proof if the blockchain's consensus mechanism can be subverted to backdate transactions. For proof-of-stake Ethereum, this requires controlling >1/3 of staked ETH — economically prohibitive at current valuations. [VERIFY:current — staking thresholds and validator economics may change.]

---

## 5. Proof Package Specification

### 5.1 What a Proof Package Is

A Proof Package is a self-contained, portable proof for a single memory. It bundles everything a third party needs to verify the memory's integrity, origin, batch inclusion, and temporal existence — without installing Open Brain or accessing any Open Brain database.

**Plain language:** Think of it as a notarised document. The document itself is included (not a reference to it). The notary's seal is included. The proof that the document was filed in a specific batch is included. The receipt showing when the batch was registered with the authorities is included. A verifier needs only the package and standard tools — they do not need to visit the notary's office.

### 5.2 ProofPackage Schema

```
ProofPackage:
    memory_id:      str                # UUID of the memory
    raw_text:       str                # The memory content
    metadata:       Dict[str, Any]     # Structured context
    content_hash:   str                # sha256:<hex>
    signature:      Optional[str]      # Ed25519 hex signature (128 chars)
    public_key_pem: Optional[str]      # Signer's public key (PEM format)
    merkle_proof:   Optional[Dict]     # Inclusion proof (see below)
    anchor:         Optional[Dict]     # Blockchain anchor details
    created_at:     str                # ISO 8601
    generated_at:   str                # ISO 8601 (when the package was assembled)
```

**Merkle proof structure (when present):**

```
merkle_proof:
    content_hash:      str              # The leaf hash
    epoch_merkle_root: str              # The epoch's Merkle root
    proof:             [(str, int), ...]  # (sibling_hash, direction) tuples
    leaf_index:        int              # Position in the epoch's leaf list
    epoch_window:
        start:         str              # ISO 8601
        end:           str              # ISO 8601
```

**Anchor structure (when present):**

```
anchor:
    anchored_at:      str               # ISO 8601
    anchor_metadata:  Dict[str, Any]    # Chain-specific (keyed by proof_type)
    epoch_merkle_root: str              # The anchored root
```

### 5.3 Assembly Process

`assemble_proof(memory_id)` composes the proof package through four steps:

1. **Retrieve:** `db.get_memory(memory_id)` fetches the full memory record.
2. **Hash check:** Recompute the content hash from `raw_text` + `metadata`. Log a warning if it does not match (the package is still assembled — the mismatch is the evidence).
3. **Epoch proof:** `prove_memory(content_hash, created_at)` auto-detects the epoch window and generates the Merkle inclusion proof.
4. **Anchor lookup:** If the epoch is anchored, include the anchor metadata.

Each step degrades gracefully: if the memory has no signature, `signature` is `None`. If the epoch is not yet sealed, `merkle_proof` is `None`. If the epoch is not anchored, `anchor` is `None`. The package always contains at minimum the memory content and its content hash.

### 5.4 Third-Party Verification

A third party verifies a Proof Package with four independent checks. Each check requires only standard algorithms — no Open Brain code.

**Check 1 — Content hash (SHA-256):**
```
canonical = json.dumps({"raw_text": ..., "metadata": ...}, sort_keys=True, separators=(",", ":"))
expected = "sha256:" + sha256(canonical.encode("utf-8")).hexdigest()
assert expected == proof_package.content_hash
```

**Check 2 — Signature (Ed25519, RFC 8032):**
```
canonical_bytes = canonical.encode("utf-8")
sig_bytes = bytes.fromhex(proof_package.signature)
public_key = load_ed25519_public_key(proof_package.public_key_pem)
public_key.verify(sig_bytes, canonical_bytes)  # raises on failure
```

**Check 3 — Merkle inclusion (SHA-256):**
```
current = proof_package.content_hash
for sibling, direction in proof_package.merkle_proof["proof"]:
    if direction == 0:  # LEFT
        current = sha256(parse_hex(sibling) + parse_hex(current))
    else:               # RIGHT
        current = sha256(parse_hex(current) + parse_hex(sibling))
assert current == proof_package.merkle_proof["epoch_merkle_root"]
```

**Check 4 — Blockchain anchor (block explorer):**
```
Look up proof_package.anchor["anchor_metadata"]["tx_hash"]
on the chain specified by proof_package.anchor["anchor_metadata"]["chain_id"].
Verify the transaction data contains the epoch_merkle_root.
```

**Key property:** Checks 1-3 are fully automated (pure computation). Check 4 requires a block explorer lookup — this is the point where verification exits the cryptographic domain and enters the public record. The block explorer itself is independently auditable (multiple block explorers exist for each chain).

**Falsification condition:** The Proof Package fails as a standalone verification mechanism if any of the four checks requires information not present in the package itself (other than the block explorer for Check 4, which is a public service).

---

## 6. Reasoning Chain Verification

### 6.1 The Problem

A single ProofPackage proves that one memory existed, was signed, and was included in a Merkle epoch. But reasoning is sequential. An agent's decision at step N depends on its state at step N-1. Verifying individual memories is necessary but insufficient — the chain between them must also be intact.

Three adversarial scenarios motivate chain verification:

1. **Selective omission.** An agent stores checkpoints 1, 2, 3, 5, 6 — omitting checkpoint 4, which recorded an inconvenient intermediate conclusion. Without chain verification, the gap is invisible.
2. **Retroactive insertion.** An agent adds a checkpoint between 3 and 4 after the fact, claiming it always considered some factor. Without chain linking, the insertion is undetectable.
3. **Content tampering.** An agent modifies the raw_text of a stored checkpoint to alter the recorded reasoning. Without hash verification, the modification is invisible.

The hash chain addresses all three: omission breaks the `previous_hash` link, insertion requires forging a hash that matches both the predecessor and successor, and tampering invalidates the content hash.

### 6.2 ChainVerification Specification

The `ChainVerification` dataclass captures the result of verifying a reasoning chain:

```
@dataclass
class ChainVerification:
    total: int = 0                    # Total checkpoints examined
    valid: int = 0                    # Checkpoints passing all applicable checks
    hash_chain_intact: bool = True    # Whether previous_hash links are unbroken
    signatures_valid: int = 0         # Checkpoints with valid Ed25519 signatures
    signatures_invalid: int = 0      # Checkpoints with invalid signatures
    signatures_missing: int = 0      # Checkpoints without signatures
    epoch_proofs: int = 0            # Checkpoints with Merkle inclusion proofs
    epoch_proofs_missing: int = 0    # Checkpoints not yet in sealed epochs
    anchored: int = 0               # Checkpoints in blockchain-anchored epochs
    breaks: List[Dict[str, Any]]    # Detailed break reports
```

Each entry in `breaks` contains: `check` (which of the five checks failed), `memory_id`, `index` (position in chain), and `detail` (human-readable description of the failure).

### 6.3 The Five Checks

`verify_reasoning_chain(agent, session_id=None)` performs five checks on the ordered chain of reasoning checkpoints for an agent:

**Check 1 — Content hash integrity.** For each checkpoint, recompute the content hash from `raw_text` and `metadata` using the canonical JSON serialisation defined in Section 4.1. Compare against the stored `content_hash`. A mismatch indicates tampering.

**Check 2 — Hash chain continuity.** For each checkpoint at index i > 0, verify that `previous_hash` equals the `content_hash` of checkpoint i-1. A mismatch indicates either omission (a checkpoint was deleted from the chain) or insertion (a checkpoint was added after the fact). The first checkpoint in a chain has no previous_hash constraint (it is the genesis of that chain).

**Check 3 — Signature validity.** For each checkpoint with a signature, verify the Ed25519 signature using the canonical JSON bytes and the public key. An invalid signature indicates either tampering (content was modified after signing) or key compromise (a different key was used).

**Check 4 — Epoch inclusion.** For each checkpoint with a content hash, attempt to generate a Merkle inclusion proof by auto-detecting the epoch window from `created_at`. Success confirms the checkpoint was included in a sealed epoch batch. Failure may simply mean the epoch has not yet been sealed (not necessarily an error).

**Check 5 — Epoch chain verification.** Independently of per-checkpoint checks, verify the epoch chain itself: each epoch's `previous_epoch_root` must match the `merkle_root` of the preceding epoch, starting from the genesis sentinel. This is a structural check — if the epoch chain is broken, all epoch-dependent proofs are weakened.

**Key property:** Checks 1-3 are per-checkpoint and fully deterministic. Check 4 depends on epoch sealing (an operational process). Check 5 is structural and independent of individual checkpoints. A fully verified chain has: all content hashes matching (Check 1), all chain links intact (Check 2), all signatures valid (Check 3), all checkpoints in sealed epochs (Check 4), and an unbroken epoch chain (Check 5).

### 6.4 Adversarial Verification Between Agents

The verification functions are public. Any agent can verify any other agent's reasoning chain:

```python
result = verify_reasoning_chain("agent_alpha")
if not result.hash_chain_intact:
    print(f"Chain broken at {result.breaks}")
```

This enables adversarial verification: Agent B can audit Agent A's reasoning before trusting its conclusions. In a multi-agent system, this creates a web of mutual accountability — each agent's reasoning is subject to verification by every other agent, with no trusted authority required.

**Falsification condition:** Chain verification fails as a tamper-detection mechanism if an adversary can modify a checkpoint's content without triggering at least one of the five checks. Under the cryptographic assumptions (SHA-256 collision resistance, Ed25519 unforgeability), this requires breaking the hash function or the signature scheme.

---

## 7. Regulatory Alignment

### 7.1 The Regulatory Problem

Two regulatory instruments impose requirements on AI decision-making that no deployed system currently satisfies with cryptographic evidence:

**GDPR Article 22** (Right to explanation of automated decisions): Data subjects have the right to obtain meaningful information about the logic involved in automated decision-making. Current practice: natural language explanations generated after the fact, with no guarantee that the explanation reflects the actual reasoning process. The explanation is unfalsifiable — there is no mechanism to verify that the described logic was the logic actually used.

**EU AI Act** (Transparency in AI reasoning): High-risk AI systems must maintain logs that enable traceability of the system's operation. Current practice: system logs capture inputs and outputs but not intermediate reasoning. The reasoning process is a black box between input and output.

### 7.2 What OB Provides

OB's reasoning checkpoints with cryptographic verification address both requirements:

**For GDPR Article 22:** Each reasoning checkpoint records the agent's intermediate state — what it was considering, what factors it weighed, what conclusion it reached at each step. The hash chain proves that the checkpoints were recorded contemporaneously (not generated after the fact). The Ed25519 signature proves machine attribution. The blockchain anchor proves temporal ordering. A regulator can verify that the explanation matches the actual recorded reasoning by independently checking the cryptographic proofs.

**For the EU AI Act:** The reasoning chain IS the traceability log. It captures not just inputs and outputs but the intermediate reasoning steps. The Merkle epoch provides batch verification (an auditor can verify thousands of reasoning steps against a single on-chain root). The export function produces a self-contained proof that requires no OB installation to verify.

### 7.3 What OB Does Not Provide

OB does not prove that the reasoning checkpoints are *complete* — an agent may reason between checkpoints without recording the intermediate steps. OB does not prove that the reasoning is *correct* — a checkpoint faithfully records what an agent claims it was thinking, but cannot verify the claim against the agent's actual internal state (which is not externally observable). OB does not prove *honesty* — an agent could deliberately record misleading checkpoints.

What OB does prove: that the recorded checkpoints existed at the claimed time, were produced by the claimed machine, have not been modified since recording, and form an unbroken sequential chain. This is a necessary (though not sufficient) condition for regulatory compliance.

**Falsification condition:** OB's regulatory alignment claim fails if a regulator requires proof of reasoning *completeness* or *correctness* (as opposed to existence and integrity). The current regulatory language (GDPR "meaningful information about the logic," EU AI Act "traceability") is satisfied by existence and integrity proofs, but future regulation could raise the bar.

[VERIFY:current] The specific GDPR Article 22 and EU AI Act provisions referenced here reflect the regulatory state as of early 2025. These instruments may have been amended, reinterpreted, or supplemented by implementing regulations.

---

## 8. Comparison to Existing Approaches

### 8.1 Overview

Four categories of existing approaches address parts of the problem OB solves. None addresses the full problem.

| Approach | Persistent Memory | Reasoning Recovery | Cryptographic Verification | Blockchain Anchoring |
|---|---|---|---|---|
| **Bigger context windows** | No | No (volume, not precision) | No | No |
| **RAG systems** | Yes (vector store) | Partial (retrieval, not reasoning) | No | No |
| **MemGPT / Letta** | Yes (managed memory) | No (stores facts, not reasoning) | No | No |
| **Blockchain timestamping** | No (timestamp only) | No | Partial (temporal proof only) | Yes |
| **OB** | Yes | Yes (checkpoint IS retrieval query) | Yes (five layers) | Yes (chain-agnostic) |

### 8.2 Bigger Context Windows

The industry trajectory is toward larger context windows: 4K → 32K → 128K → 1M+ tokens. The implicit assumption is that if the context window is large enough, the agent can simply retain everything.

This approach fails on two axes. First, attention degrades with context length — information in the middle of a long context is less likely to be attended to than information at the beginning or end ("lost in the middle" effect). Second, larger windows do not solve session boundaries — when a session ends, the context is discarded regardless of window size. The fundamental problem is not window size but session discontinuity.

### 8.3 RAG Systems

Retrieval-Augmented Generation stores information externally (typically in a vector database) and retrieves relevant chunks at query time. This provides persistent memory across sessions — information stored in the vector database survives session boundaries.

RAG does not preserve reasoning. A vector store holds facts, documents, and prior outputs, but not the reasoning process that connected them. When an agent recovers from a RAG store, it retrieves relevant information but not the reasoning context that made that information relevant. The agent must reconstruct its reasoning from scratch — the same reconstruction problem that reasoning checkpoints solve.

### 8.4 MemGPT / Letta

MemGPT (now Letta) introduces managed memory for LLMs: a system that automatically moves information between a working context and an external store, mimicking human memory hierarchies (working memory, long-term memory, archival storage).

This is a significant advance in persistent memory but does not address verification or reasoning recovery. MemGPT stores what the agent knows but not how it reasons. The stored memories are not hash-chained, not signed, not included in Merkle epochs, and not anchored on-chain. A MemGPT memory is mutable and unverifiable — there is no mechanism to prove that a memory has not been modified after storage.

### 8.5 Blockchain Timestamping

Services like OpenTimestamps and Chainpoint provide blockchain-anchored timestamps for arbitrary data. Given a document hash, they produce a proof that the hash existed at a specific time.

Blockchain timestamping provides temporal proof but not persistence, not reasoning recovery, and not the full verification chain. A timestamp proves when a hash existed but does not store the content, does not link hashes into a chain, does not sign them, and does not batch them into efficient Merkle epochs. OB uses blockchain anchoring as one layer of a five-layer verification chain — timestamping services provide only this one layer.

### 8.6 The Compositional Advantage

OB's contribution is not any single layer but their composition. Content hashing alone is trivial. Hash chains alone are well-understood. Ed25519 signing alone is standard. Merkle trees alone are textbook. Blockchain anchoring alone is a commodity service. The five layers composed into a single verification chain, applied to reasoning checkpoints that double as retrieval queries, operating on a memory format that is invariant across scales — this is the contribution.

**Falsification condition:** OB's comparative advantage disappears if an existing system adds all five verification layers to its memory system while preserving its other advantages (e.g., MemGPT's memory management + full verification chain). At that point, the comparison becomes one of implementation quality rather than capability difference.

---

## 9. Evaluation Protocol

### 9.1 Epistemological Commitment

OB follows a strict Popperian epistemology: every claim is accompanied by the conditions under which it would be falsified. No claim is treated as established unless it has survived a deliberate attempt to disprove it. This is not merely a testing methodology — it is the project's epistemological foundation.

The full methodology is specified in `METHODOLOGY.md`. This section summarises the evaluation protocol as it applies to the claims in this paper.

### 9.2 P-Pass Methodology

The P-Pass (Popperian falsification pass) is the iterative verification process applied to every claim:

1. **Identify the claim.** State what is being asserted, precisely.
2. **Identify the falsification condition.** State what evidence would disprove the claim.
3. **Attempt to falsify.** Actively try to produce that evidence.
4. **If falsified:** Revise the claim and restart.
5. **If survived:** The claim stands (provisionally — all claims are revisable).
6. **Document the attempt.** Record what was tried and what survived.

Every technical claim in this paper has been subjected to at least one P-Pass. The falsification conditions stated throughout are the residue of this process.

### 9.3 Seeded-Fault Evaluation

For verification functions (`verify_content_hash`, `verify_chain`, `verify_signature`, `verify_proof`, `verify_reasoning_chain`, `verify_epoch_chain`), the test suite includes seeded-fault tests:

- **Tampered content:** Modify `raw_text` after hashing → content hash check must fail.
- **Broken chain link:** Alter `previous_hash` to a wrong value → chain continuity check must fail.
- **Invalid signature:** Modify content after signing → signature check must fail.
- **Merkle proof corruption:** Alter a sibling hash in the proof → Merkle verification must fail.
- **Epoch chain break:** Insert an epoch with wrong `previous_epoch_root` → epoch chain check must fail.

These are not edge cases — they are the primary verification targets. A verification function that does not detect seeded faults is broken.

### 9.4 What the Test Suite Covers

The OB test suite (438+ tests at time of writing) covers:

- **Unit tests:** Individual functions in isolation (hashing, signing, Merkle operations, epoch alignment, database operations).
- **Integration tests:** Composition of multiple subsystems (proof assembly requires db + hashing + crypto + epoch + merkle).
- **Adversarial tests:** Deliberate fault injection to verify detection (per Section 9.3).
- **Idempotency tests:** Operations that should be idempotent (epoch sealing, hash computation) verified to produce identical results on repeated execution.
- **Boundary tests:** Edge cases (empty inputs, single-element Merkle trees, genesis sentinels, missing keys).

### 9.5 What the Test Suite Does Not Cover

- **Performance under load:** The test suite does not include load testing or benchmarking. Epoch sealing with millions of memories has not been tested.
- **Multi-node coordination:** OB is currently single-node. Distributed epoch sealing, conflict resolution, and consensus are designed but not implemented or tested.
- **Real blockchain interaction:** Tests use mocked blockchain interactions. The anchoring layer has been tested against Sepolia (Ethereum testnet) but not mainnet.
- **Adversarial cryptanalysis:** The test suite verifies that the verification chain works as designed but does not attempt to break the underlying cryptographic primitives (SHA-256, Ed25519). Security of these primitives is assumed based on their published cryptanalysis history.

**Falsification condition:** The evaluation protocol is inadequate if a category of real-world failure exists that no test covers and no falsification condition anticipates. The known gaps above are acknowledged; unknown gaps remain possible.

---

## 10. Limitations and Falsification Conditions

### 10.1 What OB Can Prove

For each memory, given the complete verification chain:

1. **Existence:** The memory's content hash was computed at a specific time (proven by epoch inclusion + blockchain anchor).
2. **Integrity:** The memory has not been modified since hashing (proven by content hash verification).
3. **Attribution:** The memory was signed by a specific key (proven by Ed25519 signature verification).
4. **Sequence:** The memory's position in the hash chain relative to other memories (proven by previous_hash linking).
5. **Batch inclusion:** The memory was included in a specific epoch batch (proven by Merkle inclusion proof).

### 10.2 What OB Cannot Prove

1. **Correctness.** A reasoning checkpoint records what an agent claims it was thinking. OB cannot verify this claim against the agent's actual internal state. An LLM's internal representations (attention patterns, hidden states, token probabilities) are not externally observable in a way that can be compared to the checkpoint content. The checkpoint is a self-report, and self-reports can be inaccurate or deliberately misleading.

2. **Completeness.** An agent may reason between checkpoints without recording the intermediate steps. OB captures discrete snapshots, not a continuous stream. The gaps between checkpoints are unobserved. An agent could perform significant reasoning between checkpoints that is never recorded.

3. **Honesty.** An agent could deliberately record misleading checkpoints — claiming to have considered factors it did not, or omitting factors it did. The hash chain proves that the recorded checkpoints are unmodified, but it cannot prove that they are truthful representations of the agent's reasoning.

4. **Sub-token internal state.** The fundamental limit: an LLM's reasoning occurs at the level of attention patterns and activation vectors, which are not representable as natural language text. Any textual checkpoint is necessarily an approximation of the actual computation. This is an irreducible floor — no system can fully capture internal neural computation in external text.

### 10.3 Falsification Conditions for Core Claims

**Claim: Reasoning checkpoints provide more precise context recovery than RAG retrieval.**
Falsification: Demonstrate a scenario where a volume-based RAG system consistently recovers more relevant context than reasoning checkpoints for the same set of tasks, controlling for total storage budget.

**Claim: The five-layer verification chain provides tamper-evident memory.**
Falsification: Demonstrate a modification to stored memory content that is not detected by any of the five verification checks, without breaking the underlying cryptographic primitives.

**Claim: The Proof Package is independently verifiable without OB.**
Falsification: Identify a verification step in the Proof Package that requires OB-specific code, data, or infrastructure beyond what is included in the package itself (excluding the block explorer for anchor verification).

**Claim: The memory format is scale-invariant.**
Falsification: Demonstrate a scale transition (e.g., Scale 0 to Scale 1, or Scale 2 to Scale 3) that requires modifying the memory format (the nine fields: id, raw_text, content_hash, previous_hash, signature, metadata, embedding, embedding_model, created_at) rather than only modifying transport, governance, or infrastructure.

**Claim: Graceful degradation preserves core functionality.**
Falsification: Demonstrate a configuration (e.g., no PostgreSQL, no Ed25519 keys) where the system fails silently — producing incorrect results without raising an error — rather than degrading gracefully with explicit notification of reduced capability.

**Claim: OB satisfies GDPR Article 22 and EU AI Act traceability requirements.**
Falsification: Produce a regulatory interpretation or enforcement decision that requires proof of reasoning completeness or correctness (not merely existence and integrity) for compliance.

### 10.4 The Irreducible Floor

There is a limit below which no external system can verify reasoning. An LLM processes tokens through layers of attention and feed-forward transformations. The resulting hidden states are high-dimensional vectors that do not map cleanly to natural language descriptions. A reasoning checkpoint captures a textual summary of the reasoning, not the reasoning itself.

This is analogous to a scientist's lab notebook: the notebook records observations, hypotheses, and conclusions, but it does not capture the scientist's actual thought process. The notebook is evidence of reasoning, not a recording of reasoning. Similarly, OB provides evidence that reasoning occurred and what the agent claimed to be thinking — not a recording of the actual neural computation.

This is not a limitation of OB's design but a fundamental property of the problem. Any system that stores textual descriptions of neural computation faces the same irreducible gap. OB's contribution is making the textual descriptions verifiable (hash-chained, signed, timestamped) rather than eliminating the gap between description and computation.

---

## 11. Conclusion

### 11.1 Summary of Contributions

This paper has presented Open Brain, a persistent, verifiable memory system for AI agents. The contributions are:

1. **The precision insight.** Reasoning checkpoints invert the context recovery problem: instead of retrieving relevant information from a large store (volume), the checkpoint records exactly what the agent needs on recovery (precision). The checkpoint IS the retrieval query. This is a category shift from volume-based to precision-based context recovery.

2. **The five-layer verification chain.** Content hashing (SHA-256), hash chain linking, Ed25519 signing, Merkle epoch batching, and blockchain anchoring compose into a verification chain where each layer adds a guarantee that the previous layers cannot provide alone. The combination produces memory that is not merely persistent but evidentially trustworthy.

3. **The Proof Package.** A self-contained, portable proof for any individual memory, verifiable with standard tools (SHA-256, Ed25519, a block explorer) and no OB dependency. This enables third-party verification without trust in the memory system itself.

4. **Chain verification.** Five-check verification of reasoning chains (hash integrity, chain continuity, signature validity, epoch inclusion, epoch chain) enables adversarial verification between agents — any agent can audit any other agent's reasoning.

5. **Regulatory alignment.** The verification chain provides cryptographic evidence for GDPR Article 22 (explanation of automated decisions) and EU AI Act (traceability of AI reasoning) — evidence that is independently verifiable, not merely self-reported.

### 11.2 Generality Conditions

OB is designed to be:

- **Model-agnostic.** The memory format and verification chain are independent of the underlying model. Any model that can produce text can produce reasoning checkpoints. The verification chain operates on text and metadata — it does not require access to model internals.

- **Vendor-agnostic.** OB does not depend on any specific AI vendor's API, infrastructure, or tooling. The MCP (Model Context Protocol) adapter enables integration with any MCP-compliant client. The IM (Institutional Memory) facade provides a Python API usable from any Python application.

- **Chain-agnostic.** Blockchain anchoring uses a generic metadata schema (`proof_type` key determining the schema) that supports multiple chains (Ethereum, Bitcoin via OpenTimestamps, RFC 3161 timestamping authorities). Adding a new chain requires implementing the anchoring call and defining the metadata schema — no changes to the verification chain itself.

These generality conditions are themselves falsifiable: the model-agnostic claim fails if a model exists whose outputs cannot be stored in the memory format; the vendor-agnostic claim fails if OB requires vendor-specific API calls; the chain-agnostic claim fails if adding a new blockchain requires modifying the verification chain (not just the anchoring adapter).

### 11.3 Invitation to Falsify

Every claim in this paper is accompanied by the conditions under which it would be falsified. This is not a rhetorical gesture — it is the project's epistemological commitment. The verification chain, the precision insight, the regulatory alignment claim, and the comparative advantage are all provisional. They stand because they have survived deliberate attempts at falsification, not because they are asserted as truths.

The test suite, the P-Pass methodology, and the seeded-fault evaluations are the current mechanisms for falsification. They are necessary but not sufficient — real-world deployment, independent security audit, regulatory review, and adversarial use will provide falsification opportunities that controlled testing cannot.

The source code, test suite, and this paper are available for independent verification. The invitation is open: falsify any claim, and the claim will be revised or withdrawn.
