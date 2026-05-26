"""
Temporal Reasoning for Bilinc Memory System.

Handles temporal queries:
  - "When did X happen?"
  - "What happened before/after Y?"
  - "What was the chronological order?"
  - "How long between X and Y?"

Based on Allen's interval algebra.
ORIGINAL implementation.
"""
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class TemporalRelation(str, Enum):
    BEFORE = "before"
    AFTER = "after"
    DURING = "during"
    CONTAINS = "contains"
    OVERLAPS = "overlaps"
    EQUALS = "equals"


def classify_temporal_query(query: str) -> Optional[str]:
    """Detect if query is temporal and what type."""
    ql = query.lower()

    if any(w in ql for w in ["when", "date", "time", "day", "month"]):
        return "when"
    if any(w in ql for w in ["before", "earlier", "prior", "first"]):
        return "before"
    if any(w in ql for w in ["after", "later", "following", "then", "last"]):
        return "after"
    if any(w in ql for w in ["how long", "duration", "between", "gap", "elapsed"]):
        return "duration"
    if any(w in ql for w in ["order", "sequence", "chronolog", "timeline"]):
        return "ordering"

    return None


def temporal_relation(t1: float, t2: float, tolerance: float = 0) -> TemporalRelation:
    """Determine temporal relation between two timestamps."""
    if abs(t1 - t2) <= tolerance:
        return TemporalRelation.EQUALS
    if t1 < t2:
        return TemporalRelation.BEFORE
    return TemporalRelation.AFTER


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    if seconds < 60:
        return f"{int(seconds)} seconds"
    if seconds < 3600:
        return f"{int(seconds/60)} minutes"
    if seconds < 86400:
        return f"{int(seconds/3600)} hours"
    days = int(seconds / 86400)
    if days < 30:
        return f"{days} days"
    if days < 365:
        return f"{days//30} months"
    return f"{days//365} years"


def temporal_boost(entry: Dict, query_type: str) -> float:
    """
    Boost score for entries with temporal relevance.

    Args:
        entry: Memory entry dict
        query_type: From classify_temporal_query()

    Returns:
        Boost factor (1.0 = no boost, >1.0 = boost)
    """
    if query_type is None:
        return 1.0

    has_timestamp = entry.get("valid_at") or entry.get("created_at")
    if not has_timestamp:
        return 0.8  # Penalize entries without temporal data for temporal queries

    if query_type in ("when", "before", "after", "ordering"):
        return 1.4
    if query_type == "duration":
        return 1.2

    return 1.0


def sort_by_temporal(entries: List[Tuple], query_type: str) -> List[Tuple]:
    """Sort entries based on temporal query type."""
    if query_type == "ordering":
        # Chronological order
        return sorted(entries, key=lambda e: e[1].get("created_at", 0) if len(e) > 1 else 0)
    if query_type == "before":
        # Most recent first
        return sorted(entries, key=lambda e: e[1].get("created_at", 0) if len(e) > 1 else 0, reverse=True)
    if query_type == "after":
        # Oldest first
        return sorted(entries, key=lambda e: e[1].get("created_at", 0) if len(e) > 1 else 0)
    return entries


def find_temporal_context(conn, reference_key: str, window_days: float = 7) -> List[Dict]:
    """
    Find memories temporally close to a reference memory.

    Args:
        conn: SQLite connection
        reference_key: Key of the reference memory
        window_days: Days before/after to search

    Returns:
        List of temporally related memories
    """
    try:
        ref = conn.execute(
            "SELECT created_at FROM memories WHERE key = ?", (reference_key,)
        ).fetchone()
        if not ref:
            return []

        ref_time = ref[0]
        window_seconds = window_days * 86400

        rows = conn.execute("""
            SELECT key, memory_type, importance, created_at, value
            FROM memories
            WHERE created_at BETWEEN ? AND ?
            AND key != ?
            ORDER BY created_at
        """, (ref_time - window_seconds, ref_time + window_seconds, reference_key)).fetchall()

        return [{
            "key": r[0], "memory_type": r[1], "importance": r[2],
            "created_at": r[3], "value": r[4],
            "relation": temporal_relation(r[3], ref_time).value,
        } for r in rows]
    except Exception:
        return []
