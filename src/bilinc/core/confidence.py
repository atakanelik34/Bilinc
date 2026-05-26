"""
ConfidenceEstimator: Uncertainty quantification for each decision.

Sources of confidence:
1. Retrieval quality — similarity score, recency, consistency
2. Source reliability — verified vs unverified, source type
3. Consensus — agreement across similar entries
4. Temporal strength — decay-adjusted current_strength

Returns: ConfidenceScore (float 0.0-1.0) with breakdown.
"""
from __future__ import annotations
import time
import math
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from bilinc.core.models import MemoryEntry, MemoryType


@dataclass
class ConfidenceScore:
    """Structured confidence estimate with component breakdown."""
    overall: float  # 0.0 - 1.0
    retrieval_quality: float = 0.0
    source_reliability: float = 0.0
    consensus: float = 0.0
    temporal_strength: float = 0.0
    num_entries_considered: int = 0
    
    def is_high(self, threshold: float = 0.7) -> bool:
        return self.overall >= threshold
    
    def is_low(self, threshold: float = 0.3) -> bool:
        return self.overall <= threshold


class ConfidenceEstimator:
    """
    Confidence quantification modeled after metacognitive monitoring.
    
    Combines 4 independent confidence sources:
    1. Retrieval: how well does the query match existing memories?
    2. Reliability: how trustworthy is the source of the memory?
    3. Consensus: do multiple independent sources agree?
    4. Temporal: how strong is the memory after decay?
    """
    
    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.weights = weights or {
            'retrieval': 0.30,
            'reliability': 0.25,
            'consensus': 0.25,
            'temporal': 0.20,
        }
        # Normalize weights to sum to 1.0
        total = sum(self.weights.values())
        for k in self.weights:
            self.weights[k] /= total
    
    def estimate(
        self,
        query: Optional[str] = None,
        entries: Optional[List[MemoryEntry]] = None,
        retrieval_scores: Optional[List[float]] = None,
    ) -> ConfidenceScore:
        """
        Estimate confidence based on available information.
        
        Args:
            query: The original query/intent (for relevance scoring)
            entries: List of relevant memory entries
            retrieval_scores: Optional per-entry relevance scores [0.0, 1.0]
        
        Returns:
            ConfidenceScore with overall score and component breakdown
        """
        if not entries:
            return ConfidenceScore(overall=0.0, num_entries_considered=0)
        
        retrieval_q = self._calc_retrieval_quality(entries, retrieval_scores)
        reliability = self._calc_source_reliability(entries)
        consensus = self._calc_consensus(entries)
        temporal = self._calc_temporal_strength(entries)
        
        # Weighted combination
        overall = (
            self.weights['retrieval'] * retrieval_q +
            self.weights['reliability'] * reliability +
            self.weights['consensus'] * consensus +
            self.weights['temporal'] * temporal
        )
        
        # Clip to [0, 1]
        overall = max(0.0, min(1.0, overall))
        
        return ConfidenceScore(
            overall=round(overall, 3),
            retrieval_quality=round(retrieval_q, 3),
            source_reliability=round(reliability, 3),
            consensus=round(consensus, 3),
            temporal_strength=round(temporal, 3),
            num_entries_considered=len(entries),
        )
    
    def _calc_retrieval_quality(
        self,
        entries: List[MemoryEntry],
        scores: Optional[List[float]] = None,
    ) -> float:
        """How relevant are the retrieved entries?"""
        if scores:
            # Use provided relevance scores
            return max(scores) if scores else 0.0
        # Default: based on number of entries and access patterns
        n = len(entries)
        if n == 0:
            return 0.0
        avg_access = sum(e.access_count for e in entries) / n
        access_score = min(1.0, avg_access / 10.0)
        return access_score
    
    def _calc_source_reliability(self, entries: List[MemoryEntry]) -> float:
        """How trustworthy are the sources?"""
        if not entries:
            return 0.0
        scores = []
        for e in entries:
            s = 0.5  # Base reliability
            if e.is_verified:
                s += 0.3
            if e.verification_score > 0:
                s += 0.2 * e.verification_score
            if e.source in ('user', 'verified_tool', 'consolidation'):
                s += 0.1
            scores.append(min(1.0, s))
        return max(scores)  # Best source determines reliability
    
    def _calc_consensus(self, entries: List[MemoryEntry]) -> float:
        """Do independent entries agree with each other?"""
        if len(entries) <= 1:
            return 0.5  # Neutral (can't determine consensus)
        
        # Group by value similarity
        value_counts: Dict[str, int] = {}
        for e in entries:
            val_key = str(e.value)[:50]  # Truncate for grouping
            value_counts[val_key] = value_counts.get(val_key, 0) + 1
        
        max_count = max(value_counts.values())
        total = sum(value_counts.values())
        
        # Consensus = fraction of entries agreeing with majority
        return max_count / total
    
    def _calc_temporal_strength(self, entries: List[MemoryEntry]) -> float:
        """Apply Ebbinghaus decay to get current strength."""
        if not entries:
            return 0.0
        # Update decay for each entry
        now = time.time()
        strengths = []
        for e in entries:
            hours_elapsed = (now - e.updated_at) / 3600.0
            if e.decay_rate > 0 and hours_elapsed > 0:
                e.current_strength = max(0.0, e.current_strength * (1 - e.decay_rate) ** hours_elapsed)
            strengths.append(e.current_strength)
        return sum(strengths) / len(strengths)
