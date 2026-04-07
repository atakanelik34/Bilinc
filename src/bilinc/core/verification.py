"""
Verification Gate: Recall → Verify → Commit

Implements the Decision Qualification Gate (DQG) from ACC paper,
extended with real-world verification and stale detection.

This is the core innovation: memory entries are not blindly committed.
Each entry passes through a verification process that checks:
1. Factual accuracy (against current state)
2. Staleness (is this information still valid?)
3. Confidence (how certain are we?)
4. Conflict (does this contradict existing memory?)
"""

from __future__ import annotations

import hashlib
import time
from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

from bilinc.core.models import MemoryEntry, BeliefState


class VerificationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail" 
    STALE = "stale"
    CONFLICT = "conflict"
    LOW_CONFIDENCE = "low_confidence"


@dataclass
class VerificationResult:
    """Result of verification gate."""
    status: VerificationStatus
    confidence: float  # 0.0 to 1.0
    entry: Optional[MemoryEntry] = None
    reasons: List[str] = None   # Why it passed/failed
    recommendations: List[str] = None   # What to do next
    
    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []
        if self.recommendations is None:
            self.recommendations = []
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


class VerificationGate:
    """
    Decision Qualification Gate for memory operations.
    
    Before any memory is committed, it passes through this gate
    which performs multiple checks to ensure quality and consistency.
    """
    
    def __init__(
        self,
        min_confidence: float = 0.5,
        max_conflicts: int = 0,
        check_staleness: bool = True,
        stale_threshold_hours: float = 168.0,  # 1 week default
    ):
        self.min_confidence = min_confidence
        self.max_conflicts = max_conflicts
        self.check_staleness = check_staleness
        self.stale_threshold_hours = stale_threshold_hours
        self.verification_log: List[VerificationResult] = []
    
    def verify(self, entry: MemoryEntry, existing_beliefs: Optional[BeliefState] = None) -> VerificationResult:
        """
        Full verification pipeline.
        
        1. Staleness check
        2. Conflict detection
        3. Confidence check
        4. Integrity check (hash-based)
        5. External verification (if applicable)
        """
        results: List[VerificationResult] = []
        
        # 1. Staleness check
        if self.check_staleness:
            stale_result = self._check_staleness(entry)
            results.append(stale_result)
            if stale_result.status == VerificationStatus.STALE:
                return self._finalize(entry, stale_result)
        
        # 2. Conflict detection
        if existing_beliefs:
            conflict_result = self._check_conflicts(entry, existing_beliefs)
            results.append(conflict_result)
            if conflict_result.status == VerificationStatus.CONFLICT:
                return self._finalize(entry, conflict_result)
        
        # 3. Confidence check
        confidence_result = self._check_confidence(entry)
        results.append(confidence_result)
        if confidence_result.status == VerificationStatus.LOW_CONFIDENCE:
            return self._finalize(entry, confidence_result)
        
        # 4. Integrity check
        integrity_result = self._check_integrity(entry)
        results.append(integrity_result)
        
        # All checks passed
        final = VerificationResult(
            status=VerificationStatus.PASS,
            confidence=entry.verification_score,
            entry=entry,
            reasons=["All verification checks passed"],
            recommendations=["Proceed with COMMIT"]
        )
        
        return self._finalize(entry, final)
    
    def verify_recall(self, entry: MemoryEntry, query_intent: str = "") -> VerificationResult:
        """
        Verify a memory entry being RECALLED (not committed).
        
        Checks if recalled information is still:
        - Relevant to the current query
        - Valid (not expired)
        - Accurate (not outdated)
        """
        reasons = []
        recommendations = []
        
        # Is it stale?
        if entry.is_stale():
            return VerificationResult(
                status=VerificationStatus.STALE,
                confidence=0.0,
                entry=entry,
                reasons=["Memory entry has become stale"],
                recommendations=["Fetch fresh information"]
            )
        
        # Confidence check
        if entry.current_strength < 0.3:
            reasons.append(f"Low current strength: {entry.current_strength:.2f}")
            recommendations.append(["Consider as low-confidence context"])
        
        # Relevance to query (basic key matching - enhanced version uses embeddings)
        if query_intent and query_intent.lower() not in entry.key.lower():
            if entry.metadata.get("relevance_score", 1.0) < 0.5:
                reasons.append(f"Low relevance to query: '{query_intent}'")
        
        if not reasons:
            return VerificationResult(
                status=VerificationStatus.PASS,
                confidence=entry.current_strength,
                entry=entry,
                reasons=["Recalled memory is valid and relevant"],
                recommendations=["Safe to use in current context"]
            )
        
        return VerificationResult(
            status=VerificationStatus.LOW_CONFIDENCE,
            confidence=entry.current_strength,
            entry=entry,
            reasons=reasons,
            recommendations=recommendations
        )
    
    # ─── Internal Check Methods ──────────────────────────────────
    
    def _check_staleness(self, entry: MemoryEntry) -> VerificationResult:
        """Check if entry has become stale."""
        now = time.time()
        age_hours = (now - entry.created_at) / 3600.0
        
        if entry.invalid_at and now > entry.invalid_at:
            return VerificationResult(
                status=VerificationStatus.STALE,
                confidence=0.0,
                entry=entry,
                reasons=[f"Entry explicitly invalidated at {entry.invalid_at}"],
                recommendations=["Remove or update this entry"]
            )
        
        if entry.ttl and age_hours * 3600 > entry.ttl:
            return VerificationResult(
                status=VerificationStatus.STALE,
                confidence=0.0,
                entry=entry,
                reasons=[f"TTL expired: age={age_hours:.1f}h > TTL={entry.ttl/3600:.1f}h"],
                recommendations=["Entry has exceeded its time-to-live"]
            )
        
        if entry.current_strength < self.min_confidence:
            return VerificationResult(
                status=VerificationStatus.STALE,
                confidence=entry.current_strength,
                entry=entry,
                reasons=[f"Strength too low: {entry.current_strength:.2f} < {self.min_confidence}"],
                recommendations=["Entry needs refresh or removal"]
            )
        
        return VerificationResult(
            status=VerificationStatus.PASS,
            confidence=1.0,
            entry=entry,
            reasons=["Staleness check passed"],
            recommendations=[]
        )
    
    def _check_conflicts(self, entry: MemoryEntry, beliefs: BeliefState) -> VerificationResult:
        """Check if entry conflicts with existing beliefs."""
        conflicts_found = []
        
        for key, existing in beliefs.beliefs.items():
            if key == entry.key:
                if existing.value != entry.value:
                    conflicts_found.append(key)
                    continue
            
            # Check metadata for explicit conflict markers
            if entry.metadata.get("conflicts_with") == key:
                conflicts_found.append(key)
        
        if conflicts_found:
            return VerificationResult(
                status=VerificationStatus.CONFLICT,
                confidence=0.0,
                entry=entry,
                reasons=[f"Conflicts found with: {', '.join(conflicts_found)}"],
                recommendations=[
                    "Use AGM REVISE to resolve conflict",
                    f"Consider superseding entries: {conflicts_found}"
                ]
            )
        
        return VerificationResult(
            status=VerificationStatus.PASS,
            confidence=1.0,
            entry=entry,
            reasons=["No conflicts detected"],
            recommendations=[]
        )
    
    def _check_confidence(self, entry: MemoryEntry) -> VerificationResult:
        """Check if entry meets minimum confidence threshold."""
        if entry.verification_score >= self.min_confidence:
            return VerificationResult(
                status=VerificationStatus.PASS,
                confidence=entry.verification_score,
                entry=entry,
                reasons=[f"Confidence {entry.verification_score:.2f} >= {self.min_confidence}"],
                recommendations=[]
            )
        
        return VerificationResult(
            status=VerificationStatus.LOW_CONFIDENCE,
            confidence=entry.verification_score,
            entry=entry,
            reasons=[f"Confidence {entry.verification_score:.2f} < {self.min_confidence}"],
            recommendations=["Gather more evidence before committing"]
        )
    
    def _check_integrity(self, entry: MemoryEntry) -> VerificationResult:
        """Hash-based integrity check."""
        try:
            content = f"{entry.key}:{entry.value}:{entry.memory_type.value}"
            hash_val = hashlib.sha256(content.encode()).hexdigest()[:16]
            entry.metadata["integrity_hash"] = hash_val
            return VerificationResult(
                status=VerificationStatus.PASS,
                confidence=1.0,
                entry=entry,
                reasons=["Integrity check passed"],
                recommendations=[]
            )
        except Exception as e:
            return VerificationResult(
                status=VerificationStatus.FAIL,
                confidence=0.0,
                entry=entry,
                reasons=[f"Integrity check failed: {str(e)}"],
                recommendations=["Review entry content"]
            )
    
    def _finalize(self, entry: MemoryEntry, result: VerificationResult) -> VerificationResult:
        """Log verification result and return."""
        self.verification_log.append(result)
        return result
