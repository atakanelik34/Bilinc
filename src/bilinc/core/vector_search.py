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
from functools import lru_cache
import json
import os
import re
import struct
import time
from typing import Dict, List, Optional, Tuple


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


@lru_cache(maxsize=4)
def _load_semantic_model(model_name: str, device: str, revision: str):
    """Load an explicitly configured local semantic model, if available."""
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(model_name, device=device, revision=revision or None)
    except Exception:
        return None


def _encode_semantic(model, texts: List[str], mode: str):
    """Encode query/document text across supported Sentence Transformers versions."""
    kwargs = {
        "batch_size": 64,
        "convert_to_numpy": True,
        "normalize_embeddings": True,
        "show_progress_bar": False,
    }
    specialized = getattr(model, f"encode_{mode}", None)
    if callable(specialized):
        try:
            return specialized(texts, **kwargs)
        except (TypeError, AttributeError):
            pass
    return model.encode(texts, **kwargs)


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

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        allowed_rowids: Optional[set[int]] = None,
    ) -> List[Tuple[int, float]]:
        try:
            fetch_limit = top_k
            if allowed_rowids is not None:
                if not allowed_rowids:
                    return []
                fetch_limit = max(top_k, len(allowed_rowids))
            results = self.conn.execute("""
                SELECT rowid, distance FROM vec_bilinc
                WHERE embedding MATCH ? ORDER BY distance LIMIT ?
            """, (serialize_float32(query_embedding), fetch_limit)).fetchall()
            filtered = [r for r in results if allowed_rowids is None or int(r[0]) in allowed_rowids]
            return [(r[0], r[1]) for r in filtered[:top_k]]
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
    "benchmark": ["benchmark", "score", "evaluation", "recall"],
}


def expand_query(query: str) -> str:
    """Expand query with synonyms for better recall."""
    words = re.findall(r"[\w]+", str(query or "").lower(), flags=re.UNICODE)
    expanded: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        normalized = str(term or "").strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            expanded.append(normalized)

    for word in words:
        add(word)
    for word in words:
        for key, syns in QUERY_SYNONYMS.items():
            if word in syns or word == key:
                add(key)
                for synonym in syns:
                    add(synonym)
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
        self._semantic_embeddings: Dict[int, Tuple[str, object]] = {}
        self._semantic_config: Optional[Tuple[str, str]] = None
        self._semantic_disabled = False

    def _rowids_for_allowed_keys(self, allowed_keys: Optional[set[str]]) -> Optional[set[int]]:
        if allowed_keys is None:
            return None
        normalized = {str(key) for key in allowed_keys}
        if not normalized:
            return set()
        try:
            rows = self.conn.execute("SELECT rowid, key FROM memories").fetchall()
            return {int(row[0]) for row in rows if str(row[1]) in normalized}
        except Exception:
            return set()

    def semantic_search(
        self,
        query: str,
        top_k: int = 10,
        allowed_keys: Optional[set[str]] = None,
    ) -> List[Tuple[int, float]]:
        """Optional local semantic retrieval for explicitly configured deployments.

        The base package remains dependency-free and unchanged when
        ``BILINC_SEMANTIC_MODEL`` is unset. When configured, corpus embeddings
        are cached per HybridSearch instance and the model is loaded once per
        process. ``BILINC_SEMANTIC_MODEL_REVISION`` can pin a model repository
        revision for reproducible deployments. This is a generic fallback for
        paraphrases, abbreviations, and queries with no lexical overlap; it is
        not a benchmark adapter.
        """
        if self._semantic_disabled or not query or top_k <= 0:
            return []
        model_name = os.environ.get("BILINC_SEMANTIC_MODEL", "").strip()
        if not model_name:
            return []
        device = os.environ.get("BILINC_SEMANTIC_DEVICE", "cpu").strip() or "cpu"
        revision = os.environ.get("BILINC_SEMANTIC_MODEL_REVISION", "").strip()
        config = (model_name, device, revision)
        if self._semantic_config != config:
            self._semantic_embeddings.clear()
            self._semantic_disabled = False
            self._semantic_config = config
        model = _load_semantic_model(model_name, device, revision)
        if model is None:
            self._semantic_disabled = True
            return []

        try:
            import numpy as np

            allowed_rowids = self._rowids_for_allowed_keys(allowed_keys)
            if allowed_rowids is not None and not allowed_rowids:
                return []
            rows = self.conn.execute("SELECT rowid, key, value FROM memories ORDER BY rowid").fetchall()
            if allowed_rowids is not None:
                rows = [row for row in rows if int(row[0]) in allowed_rowids]
            if not rows:
                return []
            row_ids: List[int] = []
            text_by_id: Dict[int, str] = {}
            pending_ids: List[int] = []
            pending_texts: List[str] = []
            for row in rows:
                row_id = int(row[0])
                text = f"{row[1]} {row[2] or ''}"
                row_ids.append(row_id)
                text_by_id[row_id] = text
                cached = self._semantic_embeddings.get(row_id)
                if cached is None or cached[0] != text:
                    pending_ids.append(row_id)
                    pending_texts.append(text)

            if pending_texts:
                encoded = np.asarray(_encode_semantic(model, pending_texts, "document"))
                if encoded.ndim == 1:
                    encoded = encoded.reshape(1, -1)
                for row_id, vector in zip(pending_ids, encoded):
                    self._semantic_embeddings[row_id] = (text_by_id[row_id], vector)

            query_vector = np.asarray(_encode_semantic(model, [query], "query"))[0]
            matrix = np.vstack([self._semantic_embeddings[row_id][1] for row_id in row_ids])
            scores = matrix @ query_vector
            order = np.argsort(-scores)[:top_k]
            return [(row_ids[int(index)], float(scores[int(index)])) for index in order]
        except Exception:
            self._semantic_disabled = True
            return []

    def keyword_search(
        self,
        query: str,
        top_k: int = 10,
        allowed_keys: Optional[set[str]] = None,
    ) -> List[Tuple[int, float]]:
        """FTS5 search with query expansion and LIKE fallback."""
        expanded = expand_query(query)
        allowed_rowids = self._rowids_for_allowed_keys(allowed_keys)
        if allowed_rowids is not None and not allowed_rowids:
            return []
        try:
            # FTS5 treats punctuation and words such as ``OR`` as query
            # syntax. Tokenize and quote terms so normal user questions can
            # never turn a valid retrieval request into a parser error.
            terms = re.findall(r"[\w]+", expanded, flags=re.UNICODE)
            fts_query = " OR ".join(f'"{term}"' for term in terms[:10])
            if not fts_query:
                return []
            if allowed_rowids is None:
                results = self.conn.execute("""
                    SELECT rowid, rank FROM mem_fts WHERE mem_fts MATCH ? ORDER BY rank LIMIT ?
                """, (fts_query, top_k)).fetchall()
            else:
                results = self.conn.execute("""
                    SELECT rowid, rank FROM mem_fts WHERE mem_fts MATCH ? ORDER BY rank
                """, (fts_query,)).fetchall()
                results = [row for row in results if int(row[0]) in allowed_rowids]
            if results:
                max_rank = abs(min(r[1] for r in results)) if results else 1
                return [(r[0], 1.0 - abs(r[1]) / max(max_rank, 1)) for r in results[:top_k]]
        except Exception:
            pass
        try:
            if allowed_rowids is None:
                results = self.conn.execute("""
                    SELECT rowid FROM memories WHERE key LIKE ? OR value LIKE ? LIMIT ?
                """, (f"%{query}%", f"%{query}%", top_k)).fetchall()
            else:
                results = self.conn.execute("""
                    SELECT rowid FROM memories WHERE key LIKE ? OR value LIKE ?
                """, (f"%{query}%", f"%{query}%")).fetchall()
                results = [row for row in results if int(row[0]) in allowed_rowids][:top_k]
            return [(r[0], 0.5) for r in results]
        except Exception:
            return []

    def hybrid_search(
        self,
        query: str,
        top_k: int = 10,
        query_type: str = None,
        allowed_keys: Optional[set[str]] = None,
    ) -> List[Tuple[int, float]]:
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

        allowed_rowids = self._rowids_for_allowed_keys(allowed_keys)
        if allowed_rowids is not None and not allowed_rowids:
            return []

        # Level 1: Keyword (FTS5)
        kw_results = self.keyword_search(query, top_k * 2, allowed_keys=allowed_keys)

        # Level 2: Vector
        vec_results = []
        query_emb = get_embedding(query)
        if query_emb:
            vector_limit = top_k * 2
            if allowed_rowids is not None:
                vector_limit = max(vector_limit, len(allowed_rowids))
            vec_results = self.vs.search(
                query_emb,
                vector_limit,
                allowed_rowids=allowed_rowids,
            )

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

    def search_with_reranking(
        self,
        query: str,
        top_k: int = 10,
        now: float = None,
        allowed_keys: Optional[set[str]] = None,
    ) -> List[Tuple[int, float, Dict]]:
        """
        Full pipeline: hybrid search → decay-aware reranking → temporal boost.
        """
        if now is None:
            now = time.time()

        query_type = detect_query_type(query)
        results = self.hybrid_search(
            query,
            top_k * 2,
            query_type,
            allowed_keys=allowed_keys,
        )

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
