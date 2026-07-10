"""Small, dependency-free retrieval metrics used by benchmark runners.

These helpers deliberately separate any-hit retrieval from true evidence recall.
They accept identifiers rather than model scores so their semantics remain stable
across runners.
"""

from __future__ import annotations

import math
from collections.abc import Iterable


def _top_k(retrieved: Iterable[str], k: int) -> list[str]:
    if k < 1:
        raise ValueError("k must be positive")
    return list(retrieved)[:k]


def hit_at_k(retrieved: Iterable[str], relevant: set[str], k: int) -> float:
    """Return 1 when any relevant item occurs in the first *k* results."""
    return float(bool(set(_top_k(retrieved, k)) & relevant))


def recall_at_k(retrieved: Iterable[str], relevant: set[str], k: int) -> float:
    """Return the fraction of all relevant identifiers retrieved by *k*."""
    if not relevant:
        return 0.0
    return len(set(_top_k(retrieved, k)) & relevant) / len(relevant)


def ndcg_at_k(retrieved: Iterable[str], relevant: set[str], k: int) -> float:
    """Return binary-relevance NDCG@K, normalized against all relevant items."""
    top = _top_k(retrieved, k)
    dcg = sum(
        1.0 / math.log2(position + 2)
        for position, identifier in enumerate(top)
        if identifier in relevant
    )
    ideal_count = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(position + 2) for position in range(ideal_count))
    return dcg / idcg if idcg else 0.0
