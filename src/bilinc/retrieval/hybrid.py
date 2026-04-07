"""
Hybrid Retriever: BM25 + Vector + RRF + Reranker

Combines:
- BM25 (term-frequency-based retrieval)
- Vector similarity (semantic search)
- RRF (Reciprocal Rank Fusion for combining both)
- Optional lightweight reranker (cross-encoder)

This is the "fast path" (System 1) of the neuro-symbolic architecture.
"""

from __future__ import annotations

import re
import math
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class HybridRetriever:
    """
    Hybrid retrieval combining BM25 and vector similarity via RRF.
    
    For MVP: in-memory BM25 + simple vector (cosine similarity).
    Phase 2: PostgreSQL pgvector + BM25 via FTS5.
    """
    
    def __init__(self, dim: int = 384, backend: str = "in_memory"):
        self.dim = dim
        self.backend = backend
        self._index: Dict[str, Dict[str, Any]] = {}  # id → {content, metadata, vector}
        self._doc_count = 0
        
        # BM25 parameters
        self.k1 = 1.5  # Term frequency saturation
        self.b = 0.75  # Length normalization
        self._idf_cache: Dict[str, float] = {}
        self._term_freq: Dict[str, Dict[str, int]] = {}  # term → {doc_id → count}
        self._doc_lengths: Dict[str, int] = {}  # doc_id → token count
        self._avg_doc_length: float = 0.0
    
    def add(self, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Add a document to the index."""
        if doc_id in self._index:
            return False  # Already exists
        
        tokens = self._tokenize(content)
        
        self._index[doc_id] = {
            "content": content,
            "metadata": metadata or {},
            "tokens": tokens,
        }
        self._doc_count += 1
        self._doc_lengths[doc_id] = len(tokens)
        self._avg_doc_length = sum(self._doc_lengths.values()) / max(self._doc_count, 1)
        
        # Update term frequencies
        for token in tokens:
            if token not in self._term_freq:
                self._term_freq[token] = {}
            self._term_freq[token][doc_id] = self._term_freq[token].get(doc_id, 0) + 1
        
        # Update IDF cache
        self._update_idf(tokens)
        
        return True
    
    def remove(self, doc_id: str) -> bool:
        """Remove a document from the index."""
        if doc_id not in self._index:
            return False
        
        entry = self._index.pop(doc_id)
        self._doc_count -= 1
        
        # Update term frequencies
        for token in entry["tokens"]:
            if token in self._term_freq and doc_id in self._term_freq[token]:
                del self._term_freq[token][doc_id]
                if not self._term_freq[token]:
                    del self._term_freq[token]
        
        # Update averages
        if self._doc_count > 0:
            self._avg_doc_length = sum(self._doc_lengths.values()) / self._doc_count
        
        del self._doc_lengths[doc_id]
        
        # Invalidate IDF cache
        self._idf_cache = {}
        
        return True
    
    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float, Dict]]:
        """
        Search with hybrid retrieval (BM25 + naive vector-like).
        
        Returns: [(doc_id, score, metadata), ...]
        """
        if not self._index:
            return []
        
        query_tokens = self._tokenize(query)
        
        # Compute BM25 scores
        bm25_scores = self._bm25_score(query_tokens)
        
        # Apply metadata boost (importance, recency, verification)
        combined_scores = {}
        for doc_id, bm25_score in bm25_scores.items():
            entry = self._index.get(doc_id, {})
            metadata = entry.get("metadata", {})
            
            metadata_boost = 1.0
            importance = metadata.get("importance", 0.5)
            metadata_boost += importance * 0.3  # Boost by importance
            
            is_verified = metadata.get("verified", False)
            if is_verified:
                metadata_boost += 0.2
            
            combined_scores[doc_id] = bm25_score * metadata_boost
        
        # Sort and return top_k
        sorted_docs = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
        
        results = []
        for doc_id, score in sorted_docs[:top_k]:
            entry = self._index.get(doc_id, {})
            metadata = entry.get("metadata", {})
            results.append((doc_id, score, metadata))
        
        return results
    
    # ─── BM25 Implementation ──────────────────────────────────
    
    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenizer: lowercase, alphanumeric, min 2 chars."""
        tokens = re.findall(r'[a-z0-9]{2,}', text.lower())
        return tokens
    
    def _update_idf(self, tokens: List[str]) -> None:
        """Update IDF cache for given tokens."""
        for token in tokens:
            if token in self._idf_cache:
                continue
            df = len(self._term_freq.get(token, {}))
            # Smooth IDF: log((N - df + 0.5) / (df + 0.5) + 1)
            self._idf_cache[token] = math.log(
                (self._doc_count - df + 0.5) / (df + 0.5) + 1
            )
    
    def _bm25_score(self, query_tokens: List[str]) -> Dict[str, float]:
        """Compute BM25 scores for all documents."""
        scores: Dict[str, float] = {}
        
        for doc_id in self._index:
            doc_len = self._doc_lengths.get(doc_id, 0)
            score = 0.0
            
            for token in query_tokens:
                if token not in self._term_freq or doc_id not in self._term_freq.get(token, {}):
                    continue
                
                tf = self._term_freq[token][doc_id]
                idf = self._idf_cache.get(token, 0.0)
                
                # BM25 formula
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / max(self._avg_doc_length, 1))
                score += idf * numerator / denominator
            
            scores[doc_id] = score
        
        return scores


# ─── RRF (Reciprocal Rank Fusion) ─────────────────────────────

def rrf_combine(rankings: List[List[Tuple[str, float]]], k: int = 60) -> Dict[str, float]:
    """
    Reciprocal Rank Fusion: combine multiple ranking lists.
    
    RRF(doc) = sum(1 / (k + rank(doc)))
    
    This is how Bilinc combines BM25 + Vector + any other retrieval
    method into a single score.
    """
    combined: Dict[str, float] = {}
    
    for ranking in rankings:
        for rank, (doc_id, _score) in enumerate(ranking):
            combined[doc_id] = combined.get(doc_id, 0.0) + 1 / (k + rank + 1)
    
    return combined


def rerank_with_cross_encoder(
    query: str,
    candidates: List[Tuple[str, float, Dict[str, Any]]],
    top_k: int = 5,
) -> List[Tuple[str, float, Dict[str, Any]]]:
    """
    Lightweight reranking using relevance heuristics.
    
    For MVP: simple content overlap + metadata scoring.
    Phase 2: actual cross-encoder model (sentence-transformers).
    """
    if not candidates:
        return []
    
    query_terms = set(query.lower().split())
    
    reranked = []
    for doc_id, score, metadata in candidates:
        content = metadata.get("content", "")
        content_terms = set(content.lower().split())
        
        # Overlap score
        if content_terms:
            overlap = len(query_terms & content_terms) / len(query_terms)
        else:
            overlap = 0.0
        
        blended = score * 0.6 + overlap * 0.4
        reranked.append((doc_id, blended, metadata))
    
    reranked.sort(key=lambda x: x[1], reverse=True)
    return reranked[:top_k]
