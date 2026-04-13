"""
Vector Search + Hybrid Retrieval for Bilinc.

3-level recall architecture:
  Level 1: FTS5 keyword search (exact matches, BM25)
  Level 2: Vector similarity search (semantic matches)
  Level 3: Knowledge graph traversal (multi-hop)
  
RRF fusion + decay-aware reranking + temporal boost.
ORIGINAL implementation.
"""
from __future__ import annotations
import json
import struct
import time
import re
from typing import Any, Dict, List, Optional, Tuple


def serialize_float32(vector: List[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def get_embedding(text: str, base_url: str = "http://localhost:11434") -> Optional[List[float]]:
    import urllib.request
    payload = json.dumps({"model": "nomic-embed-text:latest", "prompt": text}).encode()
    try:
        req = urllib.request.Request(f"{base_url}/api/embeddings", data=payload,
                                     headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read()).get("embedding")
    except Exception:
        return None


class VectorStore:
    def __init__(self, conn):
        self.conn = conn
        self._ensure_schema()

    def _ensure_schema(self):
        try:
            self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS vec_bilinc USING vec0(embedding float[768])")
            self.conn.commit()
        except Exception:
            pass

    def is_available(self) -> bool:
        try:
            self.conn.execute("SELECT COUNT(*) FROM vec_bilinc").fetchone()
            return True
        except Exception:
            return False

    def index_entry(self, rowid: int, text: str) -> bool:
        embedding = get_embedding(text)
        if not embedding:
            return False
        try:
            self.conn.execute("DELETE FROM vec_bilinc WHERE rowid = ?", (rowid,))
            self.conn.execute("INSERT INTO vec_bilinc (rowid, embedding) VALUES (?, ?)",
                              (rowid, serialize_float32(embedding)))
            self.conn.commit()
            return True
        except Exception:
            return False

    def search(self, query_embedding: List[float], top_k: int = 10) -> List[Tuple[int, float]]:
        try:
            results = self.conn.execute("""
                SELECT rowid, distance FROM vec_bilinc
                WHERE embedding MATCH ? ORDER BY distance LIMIT ?
            """, (serialize_float32(query_embedding), top_k)).fetchall()
            return [(r[0], r[1]) for r in results]
        except Exception:
            return []

    def count(self) -> int:
        try:
            return self.conn.execute("SELECT COUNT(*) FROM vec_bilinc").fetchone()[0]
        except Exception:
            return 0


# =============================================================================
# QUERY EXPANSION
# =============================================================================

QUERY_SYNONYMS = {
    "verification": ["verify", "verified", "verification_score", "z3", "formal"],
    "belief": ["belief", "revision", "agm", "contradiction", "conflict"],
    "memory": ["memory", "remember", "recall", "retrieval", "state"],
    "decay": ["decay", "strength", "forgetting", "stale", "prune"],
    "seed": ["seed", "round", "funding", "investor", "cap", "safe"],
    "product": ["product", "protocol", "platform", "service"],
    "reputation": ["reputation", "trust", "agent", "on-chain"],
    "document": ["document", "pdf", "ocr", "tool", "saas"],
    "cfo": ["cfo", "finance", "accounting", "erp", "fintarx"],
    "benchmark": ["benchmark", "score", "evaluation", "longmemeval", "recall"],
}


def expand_query(query: str) -> str:
    """Expand query with synonyms for better recall."""
    words = query.lower().split()
    expanded = set(words)
    for word in words:
        for key, syns in QUERY_SYNONYMS.items():
            if word in syns or word == key:
                expanded.update(syns)
                expanded.add(key)
    return " ".join(expanded)


def detect_query_type(query: str) -> str:
    """Detect query type for adaptive scoring."""
    ql = query.lower()
    if any(w in ql for w in ["when", "before", "after", "first", "order", "timeline"]):
        return "temporal"
    if any(w in ql for w in ["why", "because", "reason", "cause"]):
        return "causal"
    if any(w in ql for w in ["who", "what", "which", "how many"]):
        return "factual"
    if any(w in ql for w in ["how", "connect", "relate", "link"]):
        return "relational"
    return "general"


# =============================================================================
# HYBRID SEARCH
# =============================================================================

class HybridSearch:
    def __init__(self, conn, vector_store: VectorStore):
        self.conn = conn
        self.vs = vector_store

    def keyword_search(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        """FTS5 search with query expansion and LIKE fallback."""
        expanded = expand_query(query)
        try:
            fts_query = " OR ".join(expanded.split()[:10])
            results = self.conn.execute("""
                SELECT rowid, rank FROM mem_fts WHERE mem_fts MATCH ? ORDER BY rank LIMIT ?
            """, (fts_query, top_k)).fetchall()
            if results:
                max_rank = abs(min(r[1] for r in results)) if results else 1
                return [(r[0], 1.0 - abs(r[1]) / max(max_rank, 1)) for r in results]
        except Exception:
            pass
        try:
            results = self.conn.execute("""
                SELECT rowid FROM memories WHERE key LIKE ? OR value LIKE ? LIMIT ?
            """, (f"%{query}%", f"%{query}%", top_k)).fetchall()
            return [(r[0], 0.5) for r in results]
        except Exception:
            return []

    def hybrid_search(self, query: str, top_k: int = 10, query_type: str = None) -> List[Tuple[int, float]]:
        """
        Hybrid search with adaptive RRF fusion.
        
        Query type affects weighting:
          - temporal: boost keyword (exact dates/names)
          - causal: balance keyword + vector
          - factual: boost vector (semantic understanding)
          - relational: boost vector (relationship understanding)
          - general: balanced
        """
        if query_type is None:
            query_type = detect_query_type(query)

        # Level 1: Keyword (FTS5)
        kw_results = self.keyword_search(query, top_k * 2)

        # Level 2: Vector
        vec_results = []
        query_emb = get_embedding(query)
        if query_emb:
            vec_results = self.vs.search(query_emb, top_k * 2)

        # Adaptive RRF weights based on query type
        kw_weight, vec_weight = {
            "temporal": (0.7, 0.3),
            "causal": (0.5, 0.5),
            "factual": (0.3, 0.7),
            "relational": (0.3, 0.7),
            "general": (0.5, 0.5),
        }.get(query_type, (0.5, 0.5))

        # RRF fusion with weighted scoring
        fused = {}
        for rank, (rowid, _) in enumerate(kw_results):
            fused[rowid] = fused.get(rowid, 0) + kw_weight / (60 + rank + 1)
        for rank, (rowid, _) in enumerate(vec_results):
            fused[rowid] = fused.get(rowid, 0) + vec_weight / (60 + rank + 1)

        sorted_results = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        return sorted_results[:top_k]

    def search_with_reranking(self, query: str, top_k: int = 10, now: float = None) -> List[Tuple[int, float, Dict]]:
        """
        Full pipeline: hybrid search → decay-aware reranking → temporal boost.
        """
        if now is None:
            now = time.time()

        query_type = detect_query_type(query)
        results = self.hybrid_search(query, top_k * 2, query_type)

        reranked = []
        for rowid, base_score in results:
            try:
                row = self.conn.execute("SELECT * FROM memories WHERE rowid = ?", (rowid,)).fetchone()
                if not row:
                    continue

                from bilinc.core.decay import compute_new_strength
                days_elapsed = (now - row["last_accessed"]) / 86400.0 if row["last_accessed"] > 0 else 0
                new_strength, _ = compute_new_strength(
                    current_strength=row["current_strength"],
                    memory_type=row["memory_type"],
                    days_elapsed=days_elapsed,
                    importance=row["importance"],
                    verification_score=row["verification_score"],
                    access_count=row["access_count"],
                )

                # Decay-aware score
                decay_factor = 0.5 + new_strength * 0.5

                # Temporal boost
                temporal_factor = 1.0
                if query_type == "temporal" and (row["valid_at"] or row["created_at"]):
                    temporal_factor = 1.3

                # Importance boost
                importance_factor = 1.0 + row["importance"] * 0.2

                # Access frequency boost
                access_factor = 1.0 + min(row["access_count"], 20) * 0.01

                final_score = base_score * decay_factor * temporal_factor * importance_factor * access_factor

                reranked.append((rowid, final_score, {
                    "key": row["key"],
                    "memory_type": row["memory_type"],
                    "strength": round(new_strength, 3),
                    "importance": round(row["importance"], 3),
                    "query_type": query_type,
                }))
            except Exception:
                continue

        reranked.sort(key=lambda x: x[1], reverse=True)
        return reranked[:top_k]
