#!/usr/bin/env python3
"""
Bilinc CLI — Persistent memory operations via StatePlane.

Supports:
- In-memory mode (default, ephemeral)
- SQLite persistence via --db <path> or BILINC_DB_URL
- PostgreSQL persistence via --db 'postgresql://...' or BILINC_DB_URL

Usage:
  bilinc commit --key USER_PREF --value '{"tabs": 2}'
  bilinc --db ./bilinc.db commit --key USER_PREF --value 'hello'
  bilinc recall --key USER_PREF
  bilinc --db ./bilinc.db recall --key USER_PREF
  bilinc forget --key USER_PREF
  bilinc status
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


def _structured_error_payload(exc: Exception, default_code: str, **extra):
    message = str(exc)
    if "database is locked" in message.lower():
        return {
            "success": False,
            "error": "database_locked",
            "message": "SQLite database is locked. Retry shortly or use a different db path.",
            "retryable": True,
            "details": message,
            **extra,
        }
    return {
        "success": False,
        "error": default_code,
        "message": message,
        "retryable": False,
        **extra,
    }



def _parse_value(val: str):
    """Parse value as JSON if possible, otherwise treat as plain string."""
    try:
        return json.loads(val)
    except json.JSONDecodeError:
        return val


def _resolve_backend(db_path: str | None):
    """
    Resolve storage backend from --db argument or BILINC_DB_URL env var.

    Priority:
    1. --db CLI argument (explicit, overrides env)
    2. BILINC_DB_URL env var
    3. None (in-memory mode)
    """
    # CLI arg takes priority
    source = db_path

    # Fallback to env var
    if source is None:
        source = os.environ.get("BILINC_DB_URL")

    if source is None:
        return None, "in-memory"

    if source.startswith("postgresql://") or source.startswith("postgres://"):
        from bilinc.storage.postgres import PostgresBackend
        return PostgresBackend(dsn=source), "postgresql"

    # Default to SQLite for file paths
    from bilinc.storage.sqlite import SQLiteBackend
    return SQLiteBackend(db_path=source), "sqlite"


def main():
    parser = argparse.ArgumentParser(
        description="Bilinc — Verifiable State Plane for Autonomous Agents"
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Database path for persistent storage. "
             "SQLite: ./bilinc.db  |  PostgreSQL: postgresql://user:pass@host/db",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # Commit
    p_commit = sub.add_parser("commit", help="Commit a memory entry")
    p_commit.add_argument("--key", required=True, help="Memory key")
    p_commit.add_argument("--value", required=True, help="Memory value (JSON or string)")
    p_commit.add_argument(
        "--type",
        default="semantic",
        choices=["episodic", "procedural", "semantic", "working", "spatial"],
    )
    p_commit.add_argument("--importance", type=float, default=1.0)

    # Recall
    p_recall = sub.add_parser("recall", help="Recall memories")
    p_recall.add_argument("--key", help="Specific memory key")
    p_recall.add_argument("--limit", type=int, default=20)

    # Forget
    p_forget = sub.add_parser("forget", help="Remove a memory entry")
    p_forget.add_argument("--key", required=True)

    # Status
    sub.add_parser("status", help="Show operational statistics")

    # Eval
    p_eval = sub.add_parser("eval", help="Retrieval eval capture/replay commands")
    eval_sub = p_eval.add_subparsers(dest="eval_command", required=True)
    p_eval_export = eval_sub.add_parser("export", help="Export captured retrieval eval rows as JSONL")
    p_eval_export.add_argument("--since", help="Only export rows since duration like 7d/12h or unix timestamp")
    p_eval_export.add_argument("--limit", type=int, help="Maximum rows to export")
    p_eval_replay = eval_sub.add_parser("replay", help="Replay captured retrieval eval rows against current recall")
    p_eval_replay.add_argument("--against", required=True, help="Baseline JSONL file")
    p_eval_replay.add_argument("--limit", type=int, help="Maximum rows to replay")
    p_eval_contradictions = eval_sub.add_parser("contradictions", help="Run read-only contradiction probe over projected claims")
    p_eval_contradictions.add_argument("--query", help="Recall query to probe")
    p_eval_contradictions.add_argument("--queries", help="File containing one recall query per line")
    p_eval_contradictions.add_argument("--top-k", type=int, default=5, help="Recall results per query when probing by query")
    p_eval_contradictions.add_argument("--holder", help="Filter claims by holder")
    p_eval_contradictions.add_argument("--subject", help="Filter claims by subject/entity")
    p_eval_contradictions.add_argument("--limit", type=int, default=1000, help="Maximum active claims to inspect")
    p_eval_contradictions.add_argument("--json", action="store_true", help="Print JSON report")

    # Hermes
    hermes = sub.add_parser("hermes", help="Hermes integration commands")
    hermes_sub = hermes.add_subparsers(dest="hermes_command", required=True)

    p_bootstrap = hermes_sub.add_parser("bootstrap", help="Bootstrap Bilinc for Hermes")
    p_bootstrap.add_argument("--hermes-home", default="~/.hermes", help="Hermes home directory")
    p_bootstrap.add_argument("--db-path", default="~/bilinc.db", help="Database path")
    p_bootstrap.add_argument("--use-temp-db-for-smoke", action="store_true", help="Use temp DB for smoke test")

    p_smoke = hermes_sub.add_parser("smoke", help="Run Hermes smoke test")
    p_smoke.add_argument("--hermes-home", default="~/.hermes")
    p_smoke.add_argument("--db-path", default="~/bilinc.db")

    args = parser.parse_args()

    # Resolve backend
    backend, backend_type = _resolve_backend(args.db)

    # Create StatePlane with persistence support
    try:
        plane = _create_plane(backend, backend_type)
    except Exception as exc:
        print(
            json.dumps(_structured_error_payload(exc, "init_failed", command=args.command), indent=2),
            file=sys.stderr,
        )
        sys.exit(1)

    if args.command == "commit":
        value = _parse_value(args.value)
        _run_commit(plane, backend, args, value, backend_type)

    elif args.command == "recall":
        _run_recall(plane, backend, args, backend_type)

    elif args.command == "forget":
        _run_forget(plane, backend, args, backend_type)

    elif args.command == "status":
        _run_status(plane, backend, backend_type)

    elif args.command == "eval":
        _run_eval(plane, backend, args, backend_type)

    elif args.command == "hermes":
        _run_hermes(args)

    else:
        parser.print_help()



def _create_plane(backend, backend_type: str):
    """Create and initialize a StatePlane with the given backend."""
    from bilinc.core.stateplane import StatePlane

    plane = StatePlane(
        backend=backend,
        enable_verification=False,
        enable_audit=(backend is not None),  # Audit only with persistent backend
    )
    plane.init_agm()
    plane.init_knowledge_graph()

    # Initialize persistent backend if provided
    if backend is not None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(plane.init())
        finally:
            loop.close()
            asyncio.set_event_loop(None)  # Reset so commit_sync gets a fresh loop

    return plane


def _run_commit(plane, backend, args, value, backend_type: str):
    """Commit a memory entry."""
    try:
        # Use commit_sync — it handles async internally without nested-loop conflicts
        plane.commit_sync(
            key=args.key,
            value=value,
            memory_type=_memory_type_from_str(args.type),
            importance=args.importance,
        )

        print(json.dumps({
            "success": True,
            "key": args.key,
            "backend": backend_type,
        }, indent=2))
    except Exception as e:
        print(
            json.dumps(_structured_error_payload(e, "commit_failed", key=args.key), indent=2),
            file=sys.stderr,
        )
        sys.exit(1)


def _run_recall(plane, backend, args, backend_type: str):
    """Recall memory entries."""
    try:
        # Try persistence backend first if available
        if backend:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                if args.key:
                    entries = loop.run_until_complete(plane.recall(key=args.key))
                    if entries:
                        entry = entries[0]
                        print(json.dumps({
                            "found": True,
                            "key": entry.key,
                            "value": entry.value,
                            "backend": backend_type,
                        }, indent=2, default=str))
                    else:
                        print(json.dumps({
                            "found": False,
                            "key": args.key,
                            "backend": backend_type,
                        }, indent=2))
                else:
                    entries = loop.run_until_complete(backend.list_all())
                    limited = entries[:args.limit]
                    print(json.dumps({
                        "count": len(limited),
                        "total": len(entries),
                        "entries": [{"key": e.key, "value": e.value, "type": e.memory_type.value} for e in limited],
                        "backend": backend_type,
                    }, indent=2, default=str))
            finally:
                loop.close()
        else:
            # In-memory mode: read from working memory
            if args.key:
                entry = plane.working_memory.get(args.key) if hasattr(plane, 'working_memory') else None
                if entry:
                    print(json.dumps({"found": True, "key": entry.key, "value": entry.value}, indent=2, default=str))
                else:
                    print(json.dumps({"found": False, "key": args.key}, indent=2))
            else:
                entries = plane.working_memory.get_all() if hasattr(plane, 'working_memory') else []
                limited = entries[:args.limit]
                print(json.dumps({
                    "count": len(limited),
                    "entries": [{"key": e.key, "value": e.value, "type": e.memory_type.value} for e in limited],
                    "backend": backend_type,
                }, indent=2, default=str))
    except Exception as e:
        print(
            json.dumps(_structured_error_payload(e, "recall_failed", key=args.key), indent=2),
            file=sys.stderr,
        )
        sys.exit(1)


def _run_forget(plane, backend, args, backend_type: str):
    """Forget a memory entry."""
    try:
        # Try persistence backend first
        if backend:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(backend.delete(args.key))
                print(json.dumps({
                    "removed": result,
                    "key": args.key,
                    "backend": backend_type,
                }, indent=2))
            finally:
                loop.close()
        else:
            # In-memory mode: delete from working memory
            if hasattr(plane, 'working_memory'):
                plane.working_memory.remove(args.key)
                print(json.dumps({
                    "removed": True,
                    "key": args.key,
                    "backend": backend_type,
                }, indent=2))
            else:
                print(json.dumps({"error": "working_memory not initialized"}))
    except Exception as e:
        print(
            json.dumps(_structured_error_payload(e, "forget_failed", key=args.key), indent=2),
            file=sys.stderr,
        )
        sys.exit(1)


def _run_status(plane, backend, backend_type: str):
    """Show operational statistics."""
    try:
        status = {"backend": backend_type}

        # Backend stats
        if backend:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                status["backend_stats"] = loop.run_until_complete(backend.stats())
                status["backend_health"] = "healthy"
            except Exception as e:
                status["backend_health"] = f"error: {e}"
            finally:
                loop.close()

        # AGM stats
        if hasattr(plane, 'agm_engine') and plane.agm_engine:
            agm = plane.agm_engine
            status["agm"] = {
                "beliefs": len(agm.belief_state.get_all_beliefs()),
                "operations": len(agm.operation_log),
            }

        # Knowledge graph stats
        if hasattr(plane, 'knowledge_graph') and plane.knowledge_graph:
            status["knowledge_graph"] = plane.knowledge_graph.stats

        print(json.dumps(status, indent=2, default=str))
    except Exception as e:
        print(json.dumps(_structured_error_payload(e, "status_failed"), indent=2), file=sys.stderr)
        sys.exit(1)


def _parse_since(value: str | None):
    if not value:
        return None
    text = value.strip().lower()
    try:
        if text.endswith("d"):
            return __import__("time").time() - float(text[:-1]) * 86400
        if text.endswith("h"):
            return __import__("time").time() - float(text[:-1]) * 3600
        if text.endswith("m"):
            return __import__("time").time() - float(text[:-1]) * 60
        return float(text)
    except ValueError as exc:
        raise ValueError(f"invalid --since value: {value}") from exc


def _run_eval(plane, backend, args, backend_type: str):
    """Run retrieval eval export/replay commands."""
    try:
        if args.eval_command == "export":
            if not backend or not hasattr(backend, "list_eval_candidates"):
                raise RuntimeError(f"eval export requires SQLite backend, got {backend_type}")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                rows = loop.run_until_complete(
                    backend.list_eval_candidates(since=_parse_since(args.since), limit=args.limit)
                )
            finally:
                loop.close()
                asyncio.set_event_loop(None)
            from bilinc.eval.capture import row_to_jsonl

            for row in rows:
                print(row_to_jsonl(row), end="")
            return

        if args.eval_command == "replay":
            from bilinc.eval.capture import row_from_jsonl
            from bilinc.eval.replay import replay_rows

            with open(args.against, encoding="utf-8") as handle:
                rows = [row_from_jsonl(line) for line in handle if line.strip()]
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                report = loop.run_until_complete(replay_rows(plane, rows, limit=args.limit))
            finally:
                loop.close()
                asyncio.set_event_loop(None)
            print(json.dumps(report.to_dict(), indent=2, default=str))
            return

        if args.eval_command == "contradictions":
            if not backend or not hasattr(backend, "list_claims"):
                raise RuntimeError(f"eval contradictions requires claim storage, got {backend_type}")
            queries = []
            if args.query:
                queries.append(args.query)
            if args.queries:
                with open(args.queries, encoding="utf-8") as handle:
                    queries.extend(line.strip() for line in handle if line.strip())
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                if queries:
                    from bilinc.eval.contradictions import probe_claim_contradictions_for_queries

                    report = loop.run_until_complete(
                        probe_claim_contradictions_for_queries(plane, queries, top_k=args.top_k)
                    )
                    payload = report.to_dict()
                else:
                    claims = loop.run_until_complete(
                        backend.list_claims(
                            holder=args.holder,
                            subject=args.subject,
                            active=True,
                            limit=args.limit,
                        )
                    )
                    from bilinc.eval.contradictions import ContradictionReport, detect_claim_contradictions

                    findings = detect_claim_contradictions(claims)
                    payload = ContradictionReport.from_findings(findings).to_dict()
            finally:
                loop.close()
                asyncio.set_event_loop(None)
            payload.update({"tool": "eval_contradictions", "success": True, "read_only": True})
            print(json.dumps(payload, indent=2, default=str))
            return

        raise RuntimeError(f"unknown eval command: {args.eval_command}")
    except Exception as e:
        print(json.dumps(_structured_error_payload(e, "eval_failed"), indent=2), file=sys.stderr)
        sys.exit(1)


def _text_payload(result):
    """Decode MCP TextContent payload into python object."""
    return json.loads(result[0].text)


def _run_hermes_smoke(db_path: str) -> dict:
    """Run deterministic commit/recall/revise/diff/rollback smoke on a fresh sqlite db."""
    from bilinc.core.stateplane import StatePlane
    from bilinc.mcp_server.server_v2 import (
        _handle_commit_mem,
        _handle_diff,
        _handle_recall,
        _handle_revise,
        _handle_rollback,
        _handle_snapshot,
    )
    from bilinc.storage.sqlite import SQLiteBackend

    async def _smoke_async():
        plane = StatePlane(
            backend=SQLiteBackend(db_path=db_path),
            enable_verification=True,
            enable_audit=True,
        )
        await plane.init()
        plane.init_agm()
        plane.init_knowledge_graph()

        step = {}
        commit = _text_payload(await _handle_commit_mem(plane, {
            "key": "company_truth",
            "value": json.dumps({"name": "Bilinc"}),
            "memory_type": "semantic",
            "source": "hermes",
            "canonical": True,
            "priority": "high",
        }))
        step["commit"] = bool(commit.get("success"))

        recall = _text_payload(await _handle_recall(plane, {"canonical_only": True, "limit": 10}))
        entries = recall.get("entries", [])
        step["recall"] = bool(
            recall.get("count", 0) > 0
            and isinstance(entries[0].get("metadata"), dict)
            and entries[0]["metadata"].get("canonical", False)
        )

        revise = _text_payload(await _handle_revise(plane, {
            "key": "company_truth",
            "value": json.dumps({"name": "Bilinc AI"}),
            "strategy": "entrenchment",
        }))
        step["revise"] = bool(revise.get("success"))

        snap_a = _text_payload(await _handle_snapshot(plane, {}))
        _text_payload(await _handle_commit_mem(plane, {
            "key": "new_fact",
            "value": "v2",
            "memory_type": "semantic",
        }))
        snap_b = _text_payload(await _handle_snapshot(plane, {}))

        diff = _text_payload(await _handle_diff(plane, {"ts_a": snap_a["timestamp"], "ts_b": snap_b["timestamp"]}))
        step["diff"] = bool(diff.get("success"))

        rollback = _text_payload(await _handle_rollback(plane, {"ts": snap_a["timestamp"]}))
        step["rollback"] = bool(rollback.get("success"))

        return {
            "success": all(step.values()),
            "steps": step,
            "snapshot_a": snap_a.get("timestamp"),
            "snapshot_b": snap_b.get("timestamp"),
        }

    return asyncio.run(_smoke_async())


def _write_hermes_launcher(hermes_home: Path) -> Path:
    launcher_path = hermes_home / "bilinc_stdio_v2.py"
    launcher_path.write_text(
        "#!/usr/bin/env python3\n"
        "import asyncio\n"
        "from bilinc.mcp_server.hermes_stdio import main\n\n"
        "if __name__ == '__main__':\n"
        "    asyncio.run(main())\n",
        encoding="utf-8",
    )
    launcher_path.chmod(0o755)
    return launcher_path


def _write_hermes_env(hermes_home: Path, db_path: str) -> Path:
    env_path = hermes_home / "bilinc.env"
    env_path.write_text(
        f"BILINC_DB_PATH={db_path}\n"
        "BILINC_ENABLE_VERIFICATION=1\n"
        "BILINC_ENABLE_AUDIT=1\n"
        "BILINC_RATE_LIMIT_MAX_TOKENS=10\n"
        "BILINC_RATE_LIMIT_REFILL_RATE=1.0\n",
        encoding="utf-8",
    )
    return env_path


def _run_hermes(args):
    hermes_home = Path(args.hermes_home).expanduser().resolve()
    db_path = str(Path(args.db_path).expanduser().resolve())
    hermes_home.mkdir(parents=True, exist_ok=True)

    if args.hermes_command == "smoke":
        smoke = _run_hermes_smoke(db_path)
        print(json.dumps({
            "command": "hermes_smoke",
            "db_path": db_path,
            **smoke,
        }, indent=2))
        return

    if args.hermes_command != "bootstrap":
        raise ValueError(f"Unknown hermes command: {args.hermes_command}")

    launcher_path = _write_hermes_launcher(hermes_home)
    env_path = _write_hermes_env(hermes_home, db_path)

    smoke_db_path = db_path
    temp_dir = None
    if args.use_temp_db_for_smoke:
        temp_dir = tempfile.TemporaryDirectory(prefix="bilinc-hermes-smoke-")
        smoke_db_path = str(Path(temp_dir.name) / "smoke.db")

    try:
        smoke = _run_hermes_smoke(smoke_db_path)
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    print(json.dumps({
        "command": "hermes_bootstrap",
        "success": bool(smoke.get("success")),
        "hermes_home": str(hermes_home),
        "db_path": db_path,
        "launcher": str(launcher_path),
        "env_file": str(env_path),
        "smoke": smoke,
    }, indent=2))


def _memory_type_from_str(type_str: str):
    """Convert string to MemoryType enum."""
    from bilinc.core.models import MemoryType
    return MemoryType(type_str)


if __name__ == "__main__":
    main()
