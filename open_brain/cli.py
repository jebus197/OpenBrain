"""Open Brain CLI — clean text output for CX and CW agents.

Run: python3 -m open_brain.cli <command> [options]
"""

import argparse
import json
import os
import sys
from datetime import datetime

from open_brain import config
from open_brain import db
from open_brain.capture import capture_memory, embed_text


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="open_brain",
        description="Open Brain — persistent cross-agent memory",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # status
    sub.add_parser("status", help="Check database connection")

    # capture
    p_cap = sub.add_parser("capture", help="Store a memory")
    p_cap.add_argument("text", help="Memory content")
    _agent_choices = config.get_valid_agents() or None  # None = accept any
    p_cap.add_argument("--agent", required=True, choices=_agent_choices)
    p_cap.add_argument("--type", required=True, dest="memory_type",
                       choices=sorted(config.VALID_MEMORY_TYPES))
    p_cap.add_argument("--area", default="general", choices=sorted(config.VALID_AREAS))
    p_cap.add_argument("--status", dest="action_status",
                       choices=sorted(config.VALID_ACTION_STATUSES))
    _assignee_choices = (config.get_valid_agents() + ["all"]) if config.get_valid_agents() else None
    p_cap.add_argument("--assigned-to", choices=_assignee_choices)
    p_cap.add_argument("--priority", choices=["low", "medium", "high", "critical"])
    p_cap.add_argument("--project", help="Project name for scoping")

    # search
    p_search = sub.add_parser("search", help="Semantic search")
    p_search.add_argument("query", help="Natural language query")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--agent", dest="source_agent")
    p_search.add_argument("--type", dest="memory_type")
    p_search.add_argument("--area")
    p_search.add_argument("--project", help="Filter by project name")

    # list-recent
    p_recent = sub.add_parser("list-recent", help="List recent memories")
    p_recent.add_argument("--limit", type=int, default=20)
    p_recent.add_argument("--agent", dest="source_agent")
    p_recent.add_argument("--type", dest="memory_type")
    p_recent.add_argument("--area")
    p_recent.add_argument("--project", help="Filter by project name")

    # pending-tasks
    p_pending = sub.add_parser("pending-tasks", help="Get pending/blocked tasks")
    p_pending.add_argument("--agent", dest="assigned_to")
    p_pending.add_argument("--project", help="Filter by project name")

    # update-task
    p_update = sub.add_parser("update-task", help="Update task status")
    p_update.add_argument("memory_id", help="UUID of the task")
    p_update.add_argument("--status", required=True, dest="new_status",
                          choices=sorted(config.VALID_ACTION_STATUSES))
    p_update.add_argument("--agent", required=True, choices=config.get_valid_agents() or None)
    p_update.add_argument("--note")

    # session-context
    p_ctx = sub.add_parser("session-context", help="Get startup context for an agent")
    p_ctx.add_argument("--agent", required=True, choices=config.get_valid_agents() or None)
    p_ctx.add_argument("--project", help="Scope context to a project")

    # export
    p_export = sub.add_parser("export", help="Export memories to JSONL file")
    p_export.add_argument("output", help="Output file path (.jsonl)")
    p_export.add_argument("--project", help="Filter by project")
    p_export.add_argument("--since", help="Export memories created after this ISO date")
    p_export.add_argument("--encrypt", metavar="PASSPHRASE",
                          help="Encrypt the export file with AES-256-GCM")

    # import
    p_import = sub.add_parser("import", help="Import memories from JSONL file")
    p_import.add_argument("input", help="Input JSONL file path")
    p_import.add_argument("--decrypt", metavar="PASSPHRASE",
                          help="Decrypt the file before importing (AES-256-GCM)")
    p_import.add_argument("--source-node",
                          help="Source node ID for provenance tracking")

    # verify
    sub.add_parser("verify", help="Verify hash chain integrity and signatures")

    # seal-epoch
    p_seal = sub.add_parser("seal-epoch",
                            help="Seal the most recent completed epoch")
    p_seal.add_argument("--window-s", type=int, default=None,
                        help="Epoch window size in seconds (default: 3600)")

    # list-epochs
    p_epochs = sub.add_parser("list-epochs", help="List sealed epochs")
    p_epochs.add_argument("--limit", type=int, default=20)

    # verify-epochs
    sub.add_parser("verify-epochs", help="Verify epoch chain integrity")

    # migrate
    p_migrate = sub.add_parser("migrate", help="Run database migration")
    p_migrate.add_argument("migration", help="Migration file path (.sql)")

    # generate-keys
    p_genkeys = sub.add_parser("generate-keys",
                               help="Generate Ed25519 keypair for this node")
    p_genkeys.add_argument("--force", action="store_true",
                           help="Regenerate even if keys exist (invalidates signatures)")

    # prove
    p_prove = sub.add_parser("prove",
                             help="Assemble a proof package for a memory")
    p_prove.add_argument("memory_id", help="UUID of the memory to prove")

    # reasoning
    p_reasoning = sub.add_parser("reasoning",
                                 help="Show reasoning chain for an agent")
    p_reasoning.add_argument("agent", help="Agent identifier")
    p_reasoning.add_argument("--session", dest="session_id",
                             help="Filter to a specific session")
    p_reasoning.add_argument("--limit", type=int, default=20)

    # verify-reasoning
    p_vr = sub.add_parser("verify-reasoning",
                          help="Verify a reasoning checkpoint chain")
    p_vr.add_argument("agent", help="Agent identifier")
    p_vr.add_argument("--session", dest="session_id",
                      help="Filter to a specific session")

    # im — delegates to open_brain.im.service
    p_im = sub.add_parser("im", help="IM service (SQLite WAL-mode messaging)")
    p_im.add_argument("im_args", nargs=argparse.REMAINDER,
                       help="Arguments passed to IM service")

    # Intercept 'im' before full parse — it delegates to its own parser.
    effective_argv = argv if argv is not None else sys.argv[1:]
    if effective_argv and effective_argv[0] == "im":
        from open_brain.im.service import main as im_main
        im_main(effective_argv[1:])
        return

    args = parser.parse_args(argv)

    try:
        if args.command == "status":
            _cmd_status()
        elif args.command == "capture":
            _cmd_capture(args)
        elif args.command == "search":
            _cmd_search(args)
        elif args.command == "list-recent":
            _cmd_list_recent(args)
        elif args.command == "pending-tasks":
            _cmd_pending_tasks(args)
        elif args.command == "update-task":
            _cmd_update_task(args)
        elif args.command == "session-context":
            _cmd_session_context(args)
        elif args.command == "export":
            _cmd_export(args)
        elif args.command == "import":
            _cmd_import(args)
        elif args.command == "verify":
            _cmd_verify()
        elif args.command == "migrate":
            _cmd_migrate(args)
        elif args.command == "generate-keys":
            _cmd_generate_keys(args)
        elif args.command == "seal-epoch":
            _cmd_seal_epoch(args)
        elif args.command == "list-epochs":
            _cmd_list_epochs(args)
        elif args.command == "verify-epochs":
            _cmd_verify_epochs()
        elif args.command == "prove":
            _cmd_prove(args)
        elif args.command == "reasoning":
            _cmd_reasoning(args)
        elif args.command == "verify-reasoning":
            _cmd_verify_reasoning(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _cmd_status():
    ok = db.verify_connection()
    if ok:
        print("Database connection: OK")
        print(f"  Host: {config.DB_HOST}:{config.DB_PORT}")
        print(f"  Database: {config.DB_NAME}")
        print(f"  Embedding model: {config.EMBEDDING_MODEL_NAME}")
        print(f"  Dimension: {config.EMBEDDING_DIMENSION}")
    else:
        print("Database connection: FAILED", file=sys.stderr)
        sys.exit(1)


def _cmd_capture(args):
    mem_id = capture_memory(
        text=args.text,
        source_agent=args.agent,
        memory_type=args.memory_type,
        area=args.area,
        action_status=args.action_status,
        assigned_to=args.assigned_to,
        priority=args.priority,
        project=args.project,
    )
    print(f"Stored: {mem_id}")


def _cmd_search(args):
    query_vec = embed_text(args.query)
    results = db.semantic_search(
        query_embedding=query_vec,
        limit=args.limit,
        source_agent=args.source_agent,
        memory_type=args.memory_type,
        area=args.area,
        project=args.project,
    )
    if not results:
        print("No results.")
        return
    _print_results(results, show_distance=True)


def _cmd_list_recent(args):
    results = db.list_recent(
        limit=args.limit,
        source_agent=args.source_agent,
        memory_type=args.memory_type,
        area=args.area,
        project=args.project,
    )
    if not results:
        print("No memories found.")
        return
    _print_results(results)


def _cmd_pending_tasks(args):
    results = db.get_pending_tasks(
        assigned_to=args.assigned_to,
        project=getattr(args, "project", None),
    )
    if not results:
        print("No pending or blocked tasks.")
        return
    for r in results:
        meta = r.get("metadata", {})
        status = meta.get("action_status", "?")
        assigned = meta.get("assigned_to", "?")
        area = meta.get("area", "?")
        priority = meta.get("priority", "-")
        print(f"[{status.upper()}] [{area}] (assigned: {assigned}, priority: {priority})")
        print(f"  ID: {r['id']}")
        print(f"  {_truncate(r['raw_text'], 200)}")
        print()


def _cmd_update_task(args):
    updated = db.update_task_status(
        memory_id=args.memory_id,
        new_status=args.new_status,
        agent=args.agent,
        note=args.note,
    )
    if updated:
        print(f"Task {args.memory_id} → {args.new_status}")
    else:
        print(f"Task {args.memory_id} not found (or not a task)", file=sys.stderr)
        sys.exit(1)


def _cmd_session_context(args):
    ctx = db.get_session_context(
        agent=args.agent,
        project=getattr(args, "project", None),
    )

    print(f"=== Session Context for {args.agent.upper()} ===\n")

    print(f"Pending tasks ({len(ctx['pending_tasks'])}):")
    if ctx["pending_tasks"]:
        for t in ctx["pending_tasks"]:
            meta = t.get("metadata", {})
            print(f"  - [{meta.get('area', '?')}] {_truncate(t['raw_text'], 120)}")
            print(f"    ID: {t['id']}")
    else:
        print("  (none)")

    print(f"\nBlocked tasks ({len(ctx['blocked_tasks'])}):")
    if ctx["blocked_tasks"]:
        for t in ctx["blocked_tasks"]:
            meta = t.get("metadata", {})
            print(f"  - [{meta.get('area', '?')}] {_truncate(t['raw_text'], 120)}")
            print(f"    ID: {t['id']}")
    else:
        print("  (none)")

    print(f"\nRecent from other agents ({len(ctx['other_agents_recent'])}):")
    if ctx["other_agents_recent"]:
        for r in ctx["other_agents_recent"]:
            meta = r.get("metadata", {})
            agent = meta.get("source_agent", "?")
            mtype = meta.get("memory_type", "?")
            print(f"  [{agent}] [{mtype}] {_truncate(r['raw_text'], 100)}")
    else:
        print("  (none)")

    print(f"\nLast session summary:")
    if ctx["last_session_summary"]:
        print(f"  {ctx['last_session_summary']['raw_text'][:300]}")
    else:
        print("  (none)")


def _cmd_export(args):
    memories = db.export_memories(
        project=args.project,
        since=args.since,
    )
    if not memories:
        print("No memories to export.")
        return

    # Write JSONL content
    jsonl_content = ""
    for mem in memories:
        jsonl_content += json.dumps(mem, separators=(",", ":")) + "\n"

    if args.encrypt:
        # Write plaintext to a temp location, then encrypt
        from open_brain.crypto import encrypt_bytes
        encrypted = encrypt_bytes(jsonl_content.encode("utf-8"), args.encrypt)
        with open(args.output, "wb") as f:
            f.write(encrypted)
        print(f"Exported {len(memories)} memories to {args.output} (encrypted)")
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(jsonl_content)
        print(f"Exported {len(memories)} memories to {args.output}")

    latest_hash = memories[-1].get("content_hash")
    if latest_hash:
        print(f"  Chain head: {latest_hash}")

    # Report signing status
    signed = sum(1 for m in memories if m.get("signature"))
    if signed:
        print(f"  Signed: {signed}/{len(memories)}")


def _cmd_import(args):
    if not os.path.isfile(args.input):
        print(f"File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Read file content — decrypt if needed
    if args.decrypt:
        from open_brain.crypto import decrypt_bytes
        with open(args.input, "rb") as f:
            encrypted_data = f.read()
        try:
            plaintext = decrypt_bytes(encrypted_data, args.decrypt)
        except Exception as e:
            print(f"Decryption failed: {e}", file=sys.stderr)
            print("  Wrong passphrase or corrupted file.", file=sys.stderr)
            sys.exit(1)
        lines = plaintext.decode("utf-8").splitlines()
    else:
        with open(args.input, "r", encoding="utf-8") as f:
            lines = f.readlines()

    counts = {"inserted": 0, "skipped": 0, "conflict": 0}

    for line_no, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            mem = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"  Line {line_no}: invalid JSON — {e}", file=sys.stderr)
            continue

        result = db.import_memory(mem, source_node=args.source_node)
        counts[result] += 1

    total = counts["inserted"] + counts["skipped"] + counts["conflict"]
    print(f"Import complete: {total} memories processed")
    print(f"  Inserted: {counts['inserted']}")
    print(f"  Skipped (already exist): {counts['skipped']}")
    if counts["conflict"]:
        print(f"  Conflicts (same UUID, different hash): {counts['conflict']}")


def _cmd_verify():
    from open_brain.hashing import verify_chain

    memories = db.get_all_for_verification()
    result = verify_chain(memories)

    print(f"Hash chain verification: {result['total']} memories")
    print(f"  Valid: {result['valid']}")
    print(f"  Unhashed (pre-migration): {result['unhashed']}")

    if result["broken_content"]:
        print(f"  BROKEN content hashes: {len(result['broken_content'])}")
        for b in result["broken_content"][:5]:
            print(f"    {b['id']}: expected {b['expected'][:20]}... got {b['actual'][:20]}...")
    if result["broken_chain"]:
        print(f"  BROKEN chain links: {len(result['broken_chain'])}")
        for b in result["broken_chain"][:5]:
            print(f"    {b['id']}: expected prev {b['expected_prev'][:20]}... got {b['actual_prev'][:20] if b['actual_prev'] else 'None'}...")

    if not result["broken_content"] and not result["broken_chain"]:
        print("  Chain integrity: OK")
    else:
        sys.exit(1)

    # Signature verification
    signed = [m for m in memories if m.get("signature")]
    unsigned = [m for m in memories if m.get("content_hash") and not m.get("signature")]

    if signed:
        try:
            from open_brain.crypto import verify_signature
            valid_sigs = 0
            bad_sigs = []
            for m in signed:
                if verify_signature(m["raw_text"], m["metadata"], m["signature"]):
                    valid_sigs += 1
                else:
                    bad_sigs.append(str(m["id"]))
            print(f"\n  Signatures: {valid_sigs}/{len(signed)} verified")
            if unsigned:
                print(f"  Unsigned (pre-keygen): {len(unsigned)}")
            if bad_sigs:
                print(f"  INVALID signatures: {len(bad_sigs)}")
                for bid in bad_sigs[:5]:
                    print(f"    {bid}")
                sys.exit(1)
        except FileNotFoundError:
            print(f"\n  Signed memories: {len(signed)} (no local key to verify against)")
    elif memories:
        print(f"\n  Signatures: none (no keypair configured)")


def _cmd_migrate(args):
    if not os.path.isfile(args.migration):
        print(f"File not found: {args.migration}", file=sys.stderr)
        sys.exit(1)

    with open(args.migration, "r", encoding="utf-8") as f:
        sql = f.read()

    db.run_migration(sql)
    print(f"Migration applied: {args.migration}")


def _cmd_generate_keys(args):
    from open_brain.crypto import generate_keypair, has_keypair, KEYS_DIR

    if has_keypair() and not args.force:
        print(f"Keypair already exists at {KEYS_DIR}")
        print("  Use --force to regenerate (invalidates existing signatures)")
        return

    pub_path = generate_keypair(force=args.force)
    print(f"Ed25519 keypair generated")
    print(f"  Keys directory: {KEYS_DIR}")
    print(f"  Public key: {pub_path}")
    print(f"  New memories will be signed automatically")
    if args.force:
        print("  WARNING: existing signatures from this node are now invalid")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _print_results(results, show_distance=False):
    for i, r in enumerate(results, 1):
        meta = r.get("metadata", {})
        tags = []
        for key in ("source_agent", "memory_type", "area", "action_status"):
            if key in meta:
                tags.append(meta[key])
        tag_str = " | ".join(tags) if tags else "-"

        created = r.get("created_at", "?")
        if isinstance(created, str) and "T" in created:
            created = created[:19].replace("T", " ")

        line = f"{i}. [{tag_str}] {created}"
        if show_distance and "distance" in r:
            line += f"  (dist: {r['distance']:.4f})"
        print(line)
        print(f"   {_truncate(r['raw_text'], 200)}")
        print(f"   ID: {r['id']}")
        print()


def _cmd_prove(args):
    from open_brain.reasoning import assemble_proof

    proof = assemble_proof(args.memory_id)
    if proof is None:
        print(f"Memory not found: {args.memory_id}", file=sys.stderr)
        sys.exit(1)

    print(f"Proof package for memory {args.memory_id}")
    print(f"  Content hash: {proof.content_hash}")
    print(f"  Signature: {'present' if proof.signature else 'none'}")
    print(f"  Public key: {'present' if proof.public_key_pem else 'none'}")
    print(f"  Merkle proof: {'present' if proof.merkle_proof else 'none (epoch not sealed)'}")
    print(f"  Anchor: {'present' if proof.anchor else 'none'}")
    print(f"  Created: {proof.created_at}")
    print(f"  Generated: {proof.generated_at}")
    print(f"\nFull JSON:")
    print(proof.to_json())


def _cmd_reasoning(args):
    from open_brain.reasoning import get_reasoning_chain

    chain = get_reasoning_chain(
        args.agent,
        session_id=args.session_id,
        limit=args.limit,
    )
    if not chain:
        print(f"No reasoning checkpoints for agent '{args.agent}'.")
        return

    print(f"Reasoning chain for {args.agent}: {len(chain)} checkpoints\n")
    for i, cp in enumerate(chain, 1):
        created = cp.get("created_at", "?")
        if isinstance(created, str) and "T" in created:
            created = created[:19].replace("T", " ")
        meta = cp.get("metadata", {})
        session = meta.get("session_id", "-")
        print(f"{i}. [{created}] session={session}")
        print(f"   Hash: {cp.get('content_hash', 'none')}")
        print(f"   Prev: {cp.get('previous_hash', 'none')}")
        print(f"   {_truncate(cp['raw_text'], 200)}")
        print()


def _cmd_verify_reasoning(args):
    from open_brain.reasoning import verify_reasoning_chain

    result = verify_reasoning_chain(
        args.agent,
        session_id=args.session_id,
    )
    print(f"Reasoning chain verification for {args.agent}: {result.total} checkpoints")
    print(f"  Valid: {result.valid}")
    print(f"  Hash chain intact: {result.hash_chain_intact}")
    print(f"  Signatures: {result.signatures_valid} valid, "
          f"{result.signatures_invalid} invalid, "
          f"{result.signatures_missing} missing")
    print(f"  Epoch proofs: {result.epoch_proofs} found, "
          f"{result.epoch_proofs_missing} missing")
    print(f"  Anchored: {result.anchored}")

    if result.breaks:
        print(f"\n  BREAKS ({len(result.breaks)}):")
        for b in result.breaks[:10]:
            check = b.get("check", "?")
            detail = b.get("detail", "?")
            mem_id = b.get("memory_id", "")
            print(f"    [{check}] {detail}")
            if mem_id:
                print(f"      Memory: {mem_id}")
        sys.exit(1)
    else:
        print("  Chain integrity: OK")


def _cmd_seal_epoch(args):
    from open_brain.epoch import seal_epoch, EPOCH_WINDOW_S

    window_s = args.window_s or EPOCH_WINDOW_S
    record = seal_epoch(window_s=window_s)

    if record is None:
        print("No epoch to seal (empty window or already sealed).")
        return

    print(f"Epoch sealed: {record.window_start} → {record.window_end}")
    print(f"  Merkle root: {record.merkle_root}")
    print(f"  Memories: {record.memory_count}")
    print(f"  Sealed by: {record.sealed_by}")


def _cmd_list_epochs(args):
    from open_brain.epoch import list_epochs

    epochs = list_epochs(limit=args.limit)
    if not epochs:
        print("No sealed epochs.")
        return

    for e in epochs:
        print(f"{e['window_start']} → {e['window_end']}")
        print(f"  Root: {e['merkle_root']}")
        print(f"  Memories: {e['memory_count']}")
        print(f"  Sealed: {e['sealed_at']} by {e['sealed_by']}")
        if e.get("anchored_at"):
            anchor = e.get("anchor_metadata", {})
            print(f"  Anchored: {e['anchored_at']} ({anchor.get('proof_type', '?')})")
        else:
            print(f"  Anchored: no")
        print()


def _cmd_verify_epochs():
    from open_brain.epoch import verify_epoch_chain

    result = verify_epoch_chain()
    print(f"Epoch chain verification: {result['total']} epochs")
    print(f"  Valid: {result['valid']}")

    if result["broken"]:
        print(f"  BROKEN links: {len(result['broken'])}")
        for b in result["broken"][:5]:
            print(f"    {b['epoch_id']}: expected {b['expected'][:30]}... "
                  f"got {b['actual'][:30]}...")
        sys.exit(1)
    else:
        print("  Chain integrity: OK")


def _truncate(text, max_len):
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


if __name__ == "__main__":
    main()
