#!/usr/bin/env python3
"""
SynapticAI CLI

Usage:
  synaptic commit --key USER_PREF --value '{"tabs": 2}'
  synaptic recall --intent "editor settings"
  synaptic forget --key USER_PREF
  synaptic explain --key USER_PREF
  synaptic status
"""

import argparse
import json
import sys

from synaptic_state.core.stateplane import StatePlane
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

def main():
    parser = argparse.ArgumentParser(description="SynapticAI CLI")
    sub = parser.add_subparsers(dest="command", help="Available commands")
    
    # Commit
    p_commit = sub.add_parser("commit", help="Commit a memory entry")
    p_commit.add_argument("--key", required=True, help="Memory key")
    p_commit.add_argument("--value", required=True, help="Memory value (JSON or string)")
    p_commit.add_argument("--type", default="episodic", choices=["episodic", "procedural", "semantic", "symbolic"])
    p_commit.add_argument("--verify", action="store_true", default=True)
    p_commit.add_argument("--ttl", type=float, default=None)
    p_commit.add_argument("--source", default="cli")
    p_commit.add_argument("--session", default="")
    
    # Recall
    p_recall = sub.add_parser("recall", help="Recall memories")
    p_recall.add_argument("--intent", default="", help="What you're looking for")
    p_recall.add_argument("--budget", type=int, default=2048)
    p_recall.add_argument("--strategy", default="rl_optimized")
    p_recall.add_argument("--min-confidence", type=float, default=0.3)
    
    # Forget
    p_forget = sub.add_parser("forget", help="Remove a memory entry")
    p_forget.add_argument("--key", required=True)
    
    # Explain
    p_explain = sub.add_parser("explain", help="Explain why a memory was forgotten")
    p_explain.add_argument("--key", required=True)
    
    # Status
    sub.add_parser("status", help="Show operational statistics")
    
    args = parser.parse_args()
    plane = StatePlane()
    
    if args.command == "commit":
        result = plane.commit(
            key=args.key,
            value=json.loads(args.value) if args.value.startswith(('{', '[')) else args.value,
            memory_type=args.type,
            verify=args.verify,
            ttl=args.ttl,
            source=args.source,
            session_id=args.session,
        )
        print(json.dumps(result, indent=2))
    
    elif args.command == "recall":
        result = plane.recall(
            intent=args.intent,
            budget_tokens=args.budget,
            strategy=args.strategy,
            min_confidence=args.min_confidence,
        )
        output = {
            "memories": [{"key": m.key, "type": m.memory_type.value, "strength": m.current_strength} for m in result.memories],
            "total_tokens": result.total_tokens_estimated,
            "budget_used": f"{result.total_tokens_estimated}/{result.budget_requested}",
            "stale_count": result.stale_count,
            "conflict_count": result.conflict_count,
        }
        print(json.dumps(output, indent=2))
    
    elif args.command == "forget":
        entry = plane.forget(args.key)
        if entry:
            print(f"Forgotten: {args.key}")
        else:
            print(f"Key not found: {args.key}")
    
    elif args.command == "explain":
        explanation = plane.explain_forgetting(args.key)
        print(json.dumps(explanation, indent=2))
    
    elif args.command == "status":
        stats = plane.get_stats()
        drift = plane.get_drift_report()
        print(json.dumps({"stats": stats, "drift": drift}, indent=2))
    
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
