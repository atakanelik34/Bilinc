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

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")



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
    plane = _create_plane(backend, backend_type)

    if args.command == "commit":
        value = _parse_value(args.value)
        _run_commit(plane, backend, args, value, backend_type)

    elif args.command == "recall":
        _run_recall(plane, backend, args, backend_type)

    elif args.command == "forget":
        _run_forget(plane, backend, args, backend_type)

    elif args.command == "status":
        _run_status(plane, backend, backend_type)

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
        print(json.dumps({
            "success": False,
            "error": str(e),
            "key": args.key,
        }, indent=2), file=sys.stderr)
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
        print(json.dumps({
            "success": False,
            "error": str(e),
        }, indent=2), file=sys.stderr)
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
        print(json.dumps({
            "success": False,
            "error": str(e),
            "key": args.key,
        }, indent=2), file=sys.stderr)
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
        print(json.dumps({
            "success": False,
            "error": str(e),
        }, indent=2), file=sys.stderr)
        sys.exit(1)


def _memory_type_from_str(type_str: str):
    """Convert string to MemoryType enum."""
    from bilinc.core.models import MemoryType
    return MemoryType(type_str)


if __name__ == "__main__":
    main()
