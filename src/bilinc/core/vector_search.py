"""
Vector Search for Bilinc using sqlite-vec + Ollama embeddings.

Provides semantic search, keyword search, and hybrid RRF fusion.
ORIGINAL implementation.
"""
from __future__ import annotations
import json
import struct
import time
from typing import Any, Dict, List, Optional, Tuple


def serialize_float32(vector: List[float]) -> bytes:
    """Serialize a float32 list to bytes for sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector)


def get_embedding(text: str, base_url: str = "http://localhost:11434") -> Optional[List[float]]:
    """Get embedding from Ollama nomic-embed-text."""
    import urllib.request
    payload = json.dumps({
        "model": "nomic-embed-text:latest",
        "prompt": text
    }).encode()
    try:
        req = urllib.request.Request(
            f"{base_url}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return data.get("embedding")
    except Exception:
        return None


class VectorStore:
    """Vector search store backed by sqlite-vec."""

    def __init__(self, conn):
        self.conn = conn
        self._ensure_schema()

    def _ensure_schema(self):
        """Create vec_bilinc table if not exists."""
        try:
            self.conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_bilinc
                USING vec0(embedding float[768])
            """)
            self.conn.commit()
        except Exception:
            pass  # vec0 not loaded

    def is_available(self) -> bool:
        """Check if vector search is functional."""
        try:
            self.conn.execute("SELECT COUNT(*) FROM vec_bilinc").fetchone()
            return True
        except Exception:
            return False

    def index_entry(self, rowid: int, text: str) -> bool:
        """Generate embedding and store it for a memory entry."""
        embedding = get_embedding(text)
        if not embedding:
            return False
        try:
            # Delete existing if any
            self.conn.execute(
                "DELETE FROM vec_bilinc WHERE rowid = ?", (rowid,))
            # Insert new
            self.conn.execute(
                "INSERT INTO vec_bilinc (rowid, embedding) VALUES (?, ?)",
                (rowid, serialize_float32(embedding))
            )
            self.conn.commit()
            return True
        except Exception:
            return False

    def search(self, query_embedding: List[float], top_k: int = 10) -> List[Tuple[int, float]]:
        """Vector similarity search."""
        try:
            results = self.conn.execute("""
                SELECT rowid, distance
                FROM vec_bilinc
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            """, (serialize_float32(query_embedding), top_k)).fetchall()
            return [(r[0], r[1]) for r in results]
        except Exception:
            return []

    def count(self) -> int:
        """Count indexed entries."""
        try:
            return self.conn.execute("SELECT COUNT(*) FROM vec_bilinc").fetchone()[0]
        except Exception:
            return 0


class HybridSearch:
    """Hybrid search combining keyword + vector with RRF fusion."""

    def __init__(self, conn, vector_store: VectorStore):
        self.conn = conn
        self.vs = vector_store

    def keyword_search(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        """FTS5 full-text search with LIKE fallback."""
        try:
            # Try FTS5 first (porter stemming + unicode61)
            fts_query = ' OR '.join(query.split())
            results = self.conn.execute("""
                SELECT rowid, rank FROM mem_fts
                WHERE mem_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, top_k)).fetchall()
            if results:
                # Normalize rank (BM25 is negative, lower = better)
                max_rank = abs(min(r[1] for r in results)) if results else 1
                return [(r[0], 1.0 - abs(r[1]) / max(max_rank, 1)) for r in results]
        except Exception:
            pass
        # Fallback to LIKE
        try:
            results = self.conn.execute("""
                SELECT rowid FROM memories
                WHERE key LIKE ? OR value LIKE ?
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", top_k)).fetchall()
            return [(r[0], 0.5) for r in results]
        except Exception:
            return []

    def hybrid_search(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        """Hybrid search with RRF fusion (k=60)."""
        # Keyword results
        kw_results = self.keyword_search(query, top_k * 2)

        # Vector results
        vec_results = []
        query_emb = get_embedding(query)
        if query_emb:
            vec_results = self.vs.search(query_emb, top_k * 2)

        # RRF fusion
        fused = {}
        for rank, (rowid, _) in enumerate(kw_results):
            fused[rowid] = fused.get(rowid, 0) + 1.0 / (60 + rank + 1)
        for rank, (rowid, _) in enumerate(vec_results):
            fused[rowid] = fused.get(rowid, 0) + 1.0 / (60 + rank + 1)

        # Sort by fused score
        sorted_results = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        return sorted_results[:top_k]

    def search_with_decay(self, query: str, top_k: int = 10, now: float = None) -> List[Tuple[int, float, Dict]]:
        """Hybrid search with decay-aware reranking."""
        if now is None:
            now = time.time()

        results = self.hybrid_search(query, top_k * 2)

        reranked = []
        for rowid, base_score in results:
            try:
                row = self.conn.execute(
                    "SELECT * FROM memories WHERE rowid = ?", (rowid,)
                ).fetchone()
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

                final_score = base_score * (0.5 + new_strength * 0.5)
                reranked.append((rowid, final_score, {
                    "key": row["key"],
                    "strength": round(new_strength, 3),
                    "importance": round(row["importance"], 3),
                }))
            except Exception:
                continue

        reranked.sort(key=lambda x: x[1], reverse=True)
        return reranked[:top_k]
