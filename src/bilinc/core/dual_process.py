"""
System1Engine + System2Engine + Arbiter

Dual-process architecture modeled after Kahneman's System 1 / System 2:
- System 1: Fast, automatic, pattern-based (<100ms)
- System 2: Slow, deliberative, verification-based (1-10s)
- Arbiter: Routes based on complexity + confidence

Based on:
- Kahneman "Thinking, Fast and Slow" dual-process theory
- ACC conflict monitoring and System 1/2 arbitration
- Neural evidence: lateral PFC for System 2, basal ganglia for System 1
"""
from __future__ import annotations
import time
import logging
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.confidence import ConfidenceEstimator, ConfidenceScore


logger = logging.getLogger(__name__)


@dataclass
class ArbiterDecision:
    """Decision from the arbiter about which system to use."""
    chosen_system: str  # "system1" or "system2"
    reason: str
    complexity_score: float
    confidence: Optional[ConfidenceScore] = None
    escalation: bool = False


@dataclass 
class SystemResult:
    """Result from either System 1 or System 2."""
    response: Any
    confidence: float
    reasoning_trace: Optional[str] = None
    system_used: str = ""
    latency_ms: float = 0.0
    entries_consulted: int = 0


class System1Engine:
    """
    Fast, automatic, pattern-based processing.
    Modeled after basal ganglia / intuitive processing.
    Target latency: <100ms
    """
    
    def __init__(self, state_plane=None):
        self.state_plane = state_plane
        self._response_cache: Dict[str, tuple] = {}
        self._cache_max_size = 1000
        self._stats = {'calls': 0, 'cache_hits': 0}
    
    async def process(self, query: str, entries: List[MemoryEntry] = None) -> SystemResult:
        start = time.time()
        self._stats['calls'] += 1
        
        # Check cache first
        if query in self._response_cache:
            self._stats['cache_hits'] += 1
            cached = self._response_cache[query]
            return SystemResult(
                response=cached[0],
                confidence=cached[1],
                reasoning_trace="system1:cached",
                system_used="system1",
                latency_ms=(time.time()-start)*1000,
            )
        
        # Fast path: pattern matching on entries
        if not entries and self.state_plane:
            entries = await self.state_plane.recall_all_working()
        
        if not entries:
            return SystemResult(
                response=None, confidence=0.0, reasoning_trace="system1:no_entries",
                system_used="system1", latency_ms=(time.time()-start)*1000,
            )
        
        # Simple pattern: return highest-value entry
        best = max(entries, key=lambda e: e.importance * e.current_strength)
        
        result = SystemResult(
            response=best.value,
            confidence=0.6,  # System 1 is moderately confident
            reasoning_trace=f"system1:fast_match key={best.key} importance={best.importance}",
            system_used="system1",
            latency_ms=(time.time()-start)*1000,
            entries_consulted=len(entries),
        )
        
        # Cache the result
        if len(self._response_cache) >= self._cache_max_size:
            # Evict oldest
            oldest_key = next(iter(self._response_cache))
            del self._response_cache[oldest_key]
        self._response_cache[query] = (result.response, result.confidence)
        
        return result
    
    def get_stats(self) -> Dict:
        return {**self._stats, 'cache_size': len(self._response_cache)}


class System2Engine:
    """
    Slow, deliberative, verification-based processing.
    Modeled after prefrontal cortex / analytical processing.
    Target latency: 1-10s
    """
    
    def __init__(self, state_plane=None, agm_engine=None):
        self.state_plane = state_plane
        self.agm_engine = agm_engine
        self._stats = {'calls': 0}
    
    async def process(self, query: str, entries: List[MemoryEntry] = None) -> SystemResult:
        start = time.time()
        self._stats['calls'] += 1
        
        if not entries and self.state_plane:
            entries = await self.state_plane.recall_all_working()
        
        if not entries:
            return SystemResult(
                response=None, confidence=0.0, reasoning_trace="system2:no_entries",
                system_used="system2", latency_ms=(time.time()-start)*1000,
            )
        
        # Step 1: Verify consistency across entries (AGM-like)
        conflicts = []
        by_key: Dict[str, List[MemoryEntry]] = {}
        for e in entries:
            by_key.setdefault(e.key, []).append(e)
        
        for key, group in by_key.items():
            values = set(str(e.value) for e in group)
            if len(values) > 1:
                conflicts.append(key)
        
        # Step 2: Conflict resolution strategy
        resolution = 'consistent'
        if conflicts:
            resolution = f"conflicts_in:{len(conflicts)}_keys"
            # Resolve: keep highest-confidence entry per key
            resolved = []
            for key, group in by_key.items():
                best = max(group, key=lambda e: e.verification_score or 0)
                resolved.append(best)
            entries = resolved
        
        # Step 3: Aggregate result with trace
        trace_parts = [
            f"system2:deliberative entries={len(entries)}",
            f"conflicts_found={len(conflicts)}",
            f"resolution={resolution}",
        ]
        
        if entries:
            best = max(entries, key=lambda e: (e.verification_score or 0) * e.importance)
        else:
            best = None
        
        confidence = 0.8 if not conflicts else 0.6
        
        return SystemResult(
            response=best.value if best else None,
            confidence=confidence,
            reasoning_trace=" | ".join(trace_parts),
            system_used="system2",
            latency_ms=(time.time()-start)*1000,
            entries_consulted=len(entries),
        )
    
    def get_stats(self) -> Dict:
        return self._stats


class Arbiter:
    """
    Dual-process arbiter modeled after Anterior Cingulate Cortex (ACC).
    Decides whether to use System 1 (fast) or System 2 (slow) based on:
    - Query complexity
    - Confidence estimation
    - Past performance history
    """
    
    def __init__(
        self,
        system1=None,
        system2=None,
        estimator=None,
        low_complexity_threshold: float = 0.3,
        high_complexity_threshold: float = 0.7,
        system1_confidence_cutoff: float = 0.5,
        escalation_enabled: bool = True,
    ):
        self.system1 = system1 or System1Engine()
        self.system2 = system2 or System2Engine()
        self.estimator = estimator or ConfidenceEstimator()
        
        self.low_complexity_threshold = low_complexity_threshold
        self.high_complexity_threshold = high_complexity_threshold
        self.system1_confidence_cutoff = system1_confidence_cutoff
        self.escalation_enabled = escalation_enabled
        
        self._stats = {
            'total_queries': 0,
            'system1_calls': 0,
            'system2_calls': 0,
            'escalations': 0,
        }
        self._learning_history: List[Dict] = []
    
    def decide(self, query: str, entries: List[MemoryEntry] = None) -> ArbiterDecision:
        """Route decision: which system should handle this query?"""
        complexity = self._estimate_complexity(query, entries)
        
        if complexity < self.low_complexity_threshold:
            return ArbiterDecision(
                chosen_system="system1", reason="low_complexity",
                complexity_score=complexity,
            )
        elif complexity > self.high_complexity_threshold:
            return ArbiterDecision(
                chosen_system="system2", reason="high_complexity",
                complexity_score=complexity,
            )
        else:
            # Medium complexity: try System 1, escalate if needed
            return ArbiterDecision(
                chosen_system="system1", reason="medium_complexity_try_first",
                complexity_score=complexity,
            )
    
    async def route(self, query: str, entries: List[MemoryEntry] = None) -> SystemResult:
        """Route query through appropriate system, with optional escalation."""
        self._stats['total_queries'] += 1
        decision = self.decide(query, entries)
        
        if decision.chosen_system == "system1":
            self._stats['system1_calls'] += 1
            result = await self.system1.process(query, entries)
            
            # Escalation: if System 1 confidence is too low, try System 2
            if (self.escalation_enabled and 
                result.confidence < self.system1_confidence_cutoff and
                result.response is not None):
                self._stats['escalations'] += 1
                decision.escalation = True
                s2_result = await self.system2.process(query, entries)
                # Use System 2 result if it exists
                if s2_result.response is not None:
                    return s2_result
            
            return result
        else:
            self._stats['system2_calls'] += 1
            return await self.system2.process(query, entries)
    
    def _estimate_complexity(self, query: str, entries: List[MemoryEntry] = None) -> float:
        """
        Estimate query complexity (0.0-1.0).
        Based on:
        - Query length (token count approximation)
        - Number of entries to consider
        - Entropy/conflict among entries
        - Presence of keywords indicating deliberation
        """
        scores = []
        
        # 1. Query length heuristic
        word_count = len(query.split()) if query else 0
        complexity_length = min(1.0, word_count / 20.0)  # 20+ words = complex
        scores.append(0.3 * complexity_length)
        
        # 2. Entry count
        n_entries = len(entries) if entries else 0
        complexity_size = min(1.0, n_entries / 10.0)
        scores.append(0.3 * complexity_size)
        
        # 3. Conflict among entries (more conflicts = more complex)
        if entries and len(entries) > 1:
            value_set = set(str(e.value)[:30] for e in entries)
            conflict_ratio = 1.0 - (len(value_set) / len(entries))
            scores.append(0.2 * conflict_ratio)
        
        # 4. Query complexity keywords
        complex_keywords = ['why', 'how', 'analyze', 'compare', 'evaluate', 'decide', 'plan']
        has_complex = any(kw in query.lower() for kw in complex_keywords)
        scores.append(0.2 * (1.0 if has_complex else 0.0))
        
        # Pad to 4 scores if needed
        while len(scores) < 4:
            scores.append(0.0)
        
        return min(1.0, sum(scores))
    
    def get_stats(self) -> Dict:
        return {
            'arbiter': self._stats,
            'system1': self.system1.get_stats(),
            'system2': self.system2.get_stats(),
            'estimator_weights': self.estimator.weights.copy(),
        }
    
    def update_thresholds(self, history: List[Dict]) -> None:
        """
        Learn optimal thresholds from history.
        If System 1 failures at X complexity, raise low_threshold.
        """
        if not history:
            return
        
        s1_failures = [h for h in history if h.get('system') == 'system1' and h.get('failed')]
        if len(s1_failures) >= 3:
            avg_complexity = sum(h.get('complexity', 0.5) for h in s1_failures) / len(s1_failures)
            self.low_complexity_threshold = min(self.high_complexity_threshold - 0.1, avg_complexity - 0.1)
            logger.info(f"Arbiter: lowered System 1 threshold to {self.low_complexity_threshold:.2f}")
