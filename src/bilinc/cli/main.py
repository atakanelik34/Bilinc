#!/usr/bin/env python3
"""
Bilinc CLI — Stateless in-memory memory operations.

Note: Each command invocation creates a new in-memory StatePlane.
Data is NOT persisted between commands. Use the Python API with a
SQLite/PostgreSQL backend for persistent storage.

Usage:
  bilinc commit --key USER_PREF --value '{"tabs": 2}'
  bilinc recall --key USER_PREF
  bilinc forget --key USER_PREF
  bilinc status
"""

import argparse
import json
import sys

from bilinc.core.stateplane import StatePlane
from bilinc.core.models import MemoryType
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


def _parse_value(val: str):
    """Parse value as JSON if possible, otherwise treat as plain string."""
    if val.startswith('{') or val.startswith('['):
        try:
            return json.loads(val)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON input: {e}", "value": val}, indent=2),
                  file=sys.stderr)
            sys.exit(1)
    return val

def main():
    parser = argparse.ArgumentParser(description="Bilinc — Verifiable State Plane for Autonomous Agents")
    sub = parser.add_subparsers(dest="command", help="Available commands")
    
    # Commit
    p_commit = sub.add_parser("commit", help="Commit a memory entry")
    p_commit.add_argument("--key", required=True, help="Memory key")
    p_commit.add_argument("--value", required=True, help="Memory value (JSON or string)")
    p_commit.add_argument("--type", default="semantic", 
                          choices=["episodic", "procedural", "semantic", "working", "spatial"])
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
    
    args = parser.parse_args()
    plane = StatePlane(enable_verification=False, enable_audit=False)
    plane.init_agm()
    plane.init_knowledge_graph()
    
    if args.command == "commit":
        value = _parse_value(args.value)
        result = plane.commit_with_agm(
            key=args.key,
            value=value,
            memory_type=args.type,
            importance=args.importance,
        )
        print(json.dumps({
            "success": result.success if hasattr(result, 'success') else True,
            "key": result.key if hasattr(result, 'key') else args.key,
        }, indent=2))
    
    elif args.command == "recall":
        if args.key:
            entry = plane.agm_engine.belief_state.get_belief(args.key) if hasattr(plane, 'agm_engine') else None
            if entry:
                print(json.dumps({"found": True, "key": entry.key, "value": entry.value}, indent=2, default=str))
            else:
                print(json.dumps({"found": False, "key": args.key}, indent=2))
        else:
            beliefs = plane.agm_engine.belief_state.get_all_beliefs()
            result = beliefs[:args.limit]
            print(json.dumps({
                "count": len(result),
                "beliefs": [{"key": e.key, "value": e.value} for e in result]
            }, indent=2, default=str))
    
    elif args.command == "forget":
        if hasattr(plane, 'agm_engine') and plane.agm_engine:
            result = plane.agm_engine.contract(args.key)
            print(json.dumps({"removed": result.success, "key": args.key}, indent=2))
        else:
            print(json.dumps({"error": "AGM engine not initialized"}))
    
    elif args.command == "status":
        if hasattr(plane, 'agm_engine') and plane.agm_engine:
            agm = plane.agm_engine
            kg = plane.knowledge_graph.stats if hasattr(plane, 'knowledge_graph') else {}
            print(json.dumps({
                "agm": {
                    "beliefs": len(agm.belief_state.get_all_beliefs()),
                    "operations": len(agm.operation_log),
                },
                "knowledge_graph": kg,
            }, indent=2))
        else:
            print(json.dumps({"status": "no_components_initialized"}))
    
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
