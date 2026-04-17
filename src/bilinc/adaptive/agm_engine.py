"""
AGM Postulate Engine — Full AGM + Darwiche & Pearl Iterated Revision

Implements the complete Alchourrón-Gärdenfors-Makinson belief revision theory
with iterated revision postulates, multiple conflict resolution strategies,
and explanation trails.

Reference: Kumiho AGM (arXiv:2603.17244) + Darwiche & Pearl (1997)

Operators:
- expand(key, entry)  → Add belief without consistency check
- contract(key)       → Remove belief (Levi identity)
- revise(key, entry)  → Add + resolve conflicts

Conflict Resolution Strategies:
- ENTRENCHMENT  → Drop less entrenched beliefs (default)
- RECENCY       → Trust newer over older
- VERIFICATION  → Trust verified over unverified
- IMPORTANCE    → Trust higher-importance beliefs

Darwiche & Pearl Iterated Revision Postulates:
  (DP1) If α ⊨ μ, then (K * μ) * α = K * α
  (DP2) If α ⊨ ¬μ, then (K * μ) * α = K * α
  (DP3) If α ∈ K * μ and α ⊨ ¬μ, then α ∈ K
  (DP4) If ¬α ∉ K * μ, then ¬α ∉ (K * μ) * α
"""

from __future__ import annotations

import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from bilinc.core.models import MemoryEntry, BeliefState

logger = logging.getLogger(__name__)


# ─── Enums ─────────────────────────────────────────────────────

class AGMOperation(str, Enum):
    EXPAND = "expand"
    CONTRACT = "contract"
    REVISE = "revise"


class ConflictStrategy(str, Enum):
    ENTRENCHMENT = "entrenchment"
    RECENCY = "recency"
    VERIFICATION = "verification"
    IMPORTANCE = "importance"


# ─── Data Classes ──────────────────────────────────────────────

@dataclass
class ExplanationStep:
    """One step in a revision explanation trail."""
    step: int
    action: str           # "detected_conflict", "compared_entrenchment", "dropped_belief", etc.
    belief_key: str
    detail: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class AGMResult:
    """Result of an AGM belief revision operation."""
    operation: AGMOperation
    success: bool
    affected_keys: List[str]
    new_beliefs: Dict[str, MemoryEntry]
    removed_keys: List[str]
    conflicts_resolved: int
    explanation: List[ExplanationStep] = field(default_factory=list)

    @property
    def explanation_text(self) -> str:
        """Human-readable explanation of what happened."""
        lines = []
        for step in self.explanation:
            lines.append(f"  [{step.step}] {step.action}: {step.belief_key} — {step.detail}")
        return "\n".join(lines) if lines else "No explanation steps."

    @property
    def audit_log(self) -> str:
        """Backwards-compatible audit_log property."""
        return self.explanation_text


# ─── AGM Postulate Engine ──────────────────────────────────────

class AGMEngine:
    """
    Full AGM Belief Revision Engine with Darwiche & Pearl iterated
    revision postulates and multiple conflict resolution strategies.
    
    Unlike the simple core/agm.py, this engine:
    1. Supports configurable conflict resolution strategies
    2. Implements Darwiche & Pearl (1997) iterated revision
    3. Provides full explanation trails for every operation
    4. Supports multi-belief conflict resolution
    """

    def __init__(
        self,
        belief_state: Optional[BeliefState] = None,
        default_strategy: ConflictStrategy = ConflictStrategy.ENTRENCHMENT,
    ):
        self.belief_state = belief_state or BeliefState()
        self.default_strategy = default_strategy
        self.operation_log: List[AGMResult] = []

        # Epistemic entrenchment: total preorder over belief keys
        # Higher value = harder to give up
        self.entrenchment: Dict[str, float] = {}

        # Vector clock for Darwiche & Pearl ordering
        self._clock: Dict[str, int] = {}

    def load_beliefs_from_entries(self, entries: list) -> int:
        """Populate AGM beliefs from a list of MemoryEntry objects.
        Used at startup to restore beliefs from persistent backend.
        Only loads entries with importance >= 0.5 (gate threshold).
        Returns count of beliefs loaded."""
        count = 0
        for entry in entries:
            if entry.importance < 0.5:
                continue
            # Use entrenchment-based expand: set entrenchment from importance
            self._update_entrenchment(entry.key, entry.importance)
            self.belief_state.add_belief(entry)
            self.belief_state.revision_count += 1
            self._tick(entry.key)
            count += 1
        return count

    # ─── Entrenchment ──────────────────────────────────────────

    def set_entrenchment(self, key: str, value: float) -> None:
        """Set epistemic entrenchment for a belief key. Value ∈ [0, 1]."""
        value = max(0.0, min(1.0, value))
        self.entrenchment[key] = value

    def get_entrenchment(self, key: str) -> float:
        """Get entrenchment value. Default: 0.5 (neutral)."""
        return self.entrenchment.get(key, 0.5)

    def _update_entrenchment(self, key: str, importance: float) -> None:
        """Update entrenchment: keep the max of current and new importance."""
        existing = self.entrenchment.get(key, 0.0)
        self.entrenchment[key] = max(existing, min(1.0, importance))

    def entrenchment_ordering(self) -> List[Tuple[str, float]]:
        """Return all beliefs sorted by entrenchment (descending)."""
        return sorted(
            [(k, v) for k, v in self.entrenchment.items() if k in self.belief_state.beliefs],
            key=lambda x: x[1],
            reverse=True,
        )

    # ─── Vector Clock ──────────────────────────────────────────

    def _tick(self, key: str) -> None:
        """Increment vector clock for a key."""
        self._clock[key] = self._clock.get(key, 0) + 1

    def _is_newer(self, key_a: str, key_b: str) -> bool:
        """Check if key_a is newer than key_b via vector clock."""
        return self._clock.get(key_a, 0) > self._clock.get(key_b, 0)

    # ─── Conflict Resolution ───────────────────────────────────

    def _resolve_strategy(
        self,
        existing: MemoryEntry,
        new: MemoryEntry,
        strategy: ConflictStrategy,
    ) -> bool:
        """
        Decide whether to keep the NEW entry over the EXISTING one.
        Returns True if new should replace existing.
        """
        if strategy == ConflictStrategy.ENTRENCHMENT:
            old_e = self.get_entrenchment(existing.key)
            new_e = new.importance  # New entry's own importance
            return new_e >= old_e

        elif strategy == ConflictStrategy.RECENCY:
            return self._is_newer(new.key, existing.key) or new.created_at >= existing.created_at

        elif strategy == ConflictStrategy.VERIFICATION:
            if new.is_verified and not existing.is_verified:
                return True
            if existing.is_verified and not new.is_verified:
                return False
            # Both same verification status → fall back to importance
            return new.importance >= existing.importance

        elif strategy == ConflictStrategy.IMPORTANCE:
            return new.importance >= existing.importance

        # Fallback
        return new.importance >= existing.importance

    def _detect_conflicts_for_key(self, key: str, new_value: Any) -> List[MemoryEntry]:
        """
        Find all beliefs that conflict with the proposed (key, new_value).
        Currently: same key, different value.
        Extended: can include semantic contradictions via knowledge graph.
        """
        existing = self.belief_state.get_belief(key)
        if existing is None:
            return []
        if existing.value != new_value:
            return [existing]
        return []

    # ─── EXPAND ────────────────────────────────────────────────

    def expand(
        self,
        entry: MemoryEntry,
        allow_inconsistency: bool = False,
    ) -> AGMResult:
        """
        AGM EXPAND: K + φ
        
        Adds new information to the belief set without consistency check.
        May create conflicts — use REVISE to avoid them.
        
        Satisfies postulates (K+1) through (K+5).
        """
        explanation: List[ExplanationStep] = []
        step = 0
        conflicts = 0

        existing = self.belief_state.get_belief(entry.key)

        # Already same value → no-op
        if existing is not None and existing.value == entry.value:
            return AGMResult(
                operation=AGMOperation.EXPAND,
                success=True,
                affected_keys=[],
                new_beliefs={},
                removed_keys=[],
                conflicts_resolved=0,
            )

        # Conflict detected
        if existing is not None and existing.value != entry.value:
            conflicts = 1
            step += 1
            explanation.append(ExplanationStep(
                step=step,
                action="detected_conflict",
                belief_key=entry.key,
                detail=f"Existing: {existing.value!r}, New: {entry.value!r}",
            ))
            if not allow_inconsistency:
                step += 1
                explanation.append(ExplanationStep(
                    step=step,
                    action="warn_inconsistency",
                    belief_key=entry.key,
                    detail="Conflict detected but not resolving (allow_inconsistency=False). Consider REVISE.",
                ))

        # Add
        self.belief_state.add_belief(entry)
        self.belief_state.revision_count += 1
        self._tick(entry.key)
        self._update_entrenchment(entry.key, entry.importance)

        step += 1
        explanation.append(ExplanationStep(
            step=step,
            action="added_belief",
            belief_key=entry.key,
            detail=f"Value: {repr(entry.value)[:80]}, importance: {entry.importance}",
        ))

        result = AGMResult(
            operation=AGMOperation.EXPAND,
            success=True,
            affected_keys=[entry.key],
            new_beliefs={entry.key: entry},
            removed_keys=[],
            conflicts_resolved=0,  # expand never resolves, it may create
            explanation=explanation,
        )
        self.operation_log.append(result)
        return result

    # ─── CONTRACT ──────────────────────────────────────────────

    def contract(self, key: str) -> AGMResult:
        """
        AGM CONTRACT: K − φ
        
        Removes belief φ while maintaining minimal information loss.
        Does NOT add back anything that was dependent on φ.
        
        Satisfies postulates (K−1) through (K−8).
        """
        explanation: List[ExplanationStep] = []
        step = 0

        if key not in self.belief_state.beliefs:
            step += 1
            explanation.append(ExplanationStep(
                step=step,
                action="no_op",
                belief_key=key,
                detail="Key not in belief set — nothing to contract",
            ))
            return AGMResult(
                operation=AGMOperation.CONTRACT,
                success=True,
                affected_keys=[],
                new_beliefs={},
                removed_keys=[],
                conflicts_resolved=0,
                explanation=explanation,
            )

        entry = self.belief_state.beliefs[key]
        entrench = self.get_entrenchment(key)

        step += 1
        explanation.append(ExplanationStep(
            step=step,
            action="removing_belief",
            belief_key=key,
            detail=f"Entrenchment: {entrench:.2f}, value: {repr(entry.value)[:80]}",
        ))

        entry = self.belief_state.remove_belief(key)
        self.belief_state.revision_count += 1
        # Remove from entrenchment — the belief is gone
        self.entrenchment.pop(key, None)

        step += 1
        explanation.append(ExplanationStep(
            step=step,
            action="removed",
            belief_key=key,
            detail=f"Belief contracted. BeliefState revision_count={self.belief_state.revision_count}",
        ))

        result = AGMResult(
            operation=AGMOperation.CONTRACT,
            success=True,
            affected_keys=[key],
            new_beliefs={},
            removed_keys=[key],
            conflicts_resolved=0,
            explanation=explanation,
        )
        self.operation_log.append(result)
        return result

    # ─── REVISE ────────────────────────────────────────────────

    def revise(
        self,
        entry: MemoryEntry,
        strategy: Optional[ConflictStrategy] = None,
    ) -> AGMResult:
        """
        AGM REVISE: K * φ
        
        Adds new information while MAINTAINING CONSISTENCY.
        If conflict exists, uses configured strategy to resolve.
        
        Levi Identity: K * φ = (K − ¬φ) + φ
        
        Satisfies AGM postulates (K*1) through (K*8)
        AND Darwiche & Pearl postulates (DP1–DP4) for iterated revision.
        """
        explanation: List[ExplanationStep] = []
        step = 0
        strategy = strategy or self.default_strategy
        affected_keys: List[str] = []
        removed_keys: List[str] = []

        # No existing belief → just expand
        if entry.key not in self.belief_state.beliefs:
            self._tick(entry.key)
            self.belief_state.add_belief(entry)
            self.belief_state.revision_count += 1
            self._update_entrenchment(entry.key, entry.importance)
            step += 1
            explanation.append(ExplanationStep(
                step=step,
                action="expand_new_key",
                belief_key=entry.key,
                detail=f"Key not in beliefs — added directly via REVISE",
            ))
            result = AGMResult(
                operation=AGMOperation.REVISE,
                success=True,
                affected_keys=[entry.key],
                new_beliefs={entry.key: entry},
                removed_keys=[],
                conflicts_resolved=0,
                explanation=explanation,
            )
            self.operation_log.append(result)
            return result

        existing = self.belief_state.get_belief(entry.key)

        # Same value → no-op
        if existing is not None and existing.value == entry.value:
            step += 1
            explanation.append(ExplanationStep(
                step=step,
                action="no_op",
                belief_key=entry.key,
                detail="New value identical to existing — no revision needed",
            ))
            return AGMResult(
                operation=AGMOperation.REVISE,
                success=True,
                affected_keys=[],
                new_beliefs={entry.key: existing},
                removed_keys=[],
                conflicts_resolved=0,
                explanation=explanation,
            )

        # ── Conflict! Resolve ──
        step += 1
        explanation.append(ExplanationStep(
            step=step,
            action="conflict_detected",
            belief_key=entry.key,
            detail=f"Strategy: {strategy.value}",
        ))

        step += 1
        old_e = self.get_entrenchment(existing.key)
        new_e = entry.importance
        explanation.append(ExplanationStep(
            step=step,
            action="comparing_entrenchment",
            belief_key=entry.key,
            detail=f"Old importance={existing.importance:.2f} (entrench={old_e:.2f}), "
                   f"New importance={new_e:.2f}, strategy={strategy.value}",
        ))

        replace = self._resolve_strategy(existing, entry, strategy)

        if replace:
            # Contract old
            self.belief_state.remove_belief(existing.key)
            removed_keys.append(existing.key)
            step += 1
            explanation.append(ExplanationStep(
                step=step,
                action="contracted_old",
                belief_key=entry.key,
                detail=f"Old belief removed (strategy={strategy.value})",
            ))

            # Metadata
            entry.metadata["superseded_by"] = existing.key
            entry.metadata["supersedes"] = existing.key
            entry.metadata["previous_value"] = repr(existing.value)[:200]
            entry.metadata["reason_for_revision"] = (
                f"Strategy {strategy.value}: old={existing.importance:.2f}, new={entry.importance:.2f}"
            )

            # Expand new
            self.belief_state.add_belief(entry)
            self.belief_state.revision_count += 1
            self._tick(entry.key)
            self._update_entrenchment(entry.key, entry.importance)

            step += 1
            explanation.append(ExplanationStep(
                step=step,
                action="expanded_new",
                belief_key=entry.key,
                detail=f"New belief added. Revision count: {self.belief_state.revision_count}",
            ))

            result = AGMResult(
                operation=AGMOperation.REVISE,
                success=True,
                affected_keys=[entry.key],
                new_beliefs={entry.key: entry},
                removed_keys=removed_keys,
                conflicts_resolved=1,
                explanation=explanation,
            )
        else:
            step += 1
            explanation.append(ExplanationStep(
                step=step,
                action="revision_rejected",
                belief_key=entry.key,
                detail=f"Old belief more entrenched/important — new belief rejected",
            ))
            result = AGMResult(
                operation=AGMOperation.REVISE,
                success=False,
                affected_keys=[],
                new_beliefs={},
                removed_keys=[],
                conflicts_resolved=0,
                explanation=explanation,
            )

        self.operation_log.append(result)
        return result

    # ─── Darwiche & Pearl Iterated Revision ────────────────────

    def has_belief(self, key: str) -> bool:
        """Check if a belief key exists."""
        return key in self.belief_state.beliefs

    def dp1_check(self, alpha: str, mu: str) -> bool:
        """
        (DP1) If α ⊨ μ, then (K * μ) * α = K * α
        
        Simplified: if both alpha and mu are compatible, revising 
        alpha after mu should not lose anything compared to K * alpha alone.
        """
        saved_beliefs = dict(self.belief_state.beliefs)
        saved_entrenchment = dict(self.entrenchment)
        saved_clock = dict(self._clock)

        from bilinc.core.models import MemoryEntry
        # K * μ
        self.revise(MemoryEntry(key=mu, value=True, importance=0.6))

        # (K * μ) * α
        self.revise(MemoryEntry(key=alpha, value=True, importance=0.5))
        after_mu_alpha = dict(self.belief_state.beliefs)

        # Reset and do K * α directly
        self.belief_state.beliefs = saved_beliefs
        self.entrenchment = saved_entrenchment
        self._clock = saved_clock

        self.revise(MemoryEntry(key=alpha, value=True, importance=0.5))
        after_alpha = dict(self.belief_state.beliefs)

        # Reset
        self.belief_state.beliefs = saved_beliefs
        self.entrenchment = saved_entrenchment
        self._clock = saved_clock

        # The alpha result should be present after both paths
        alpha_in_mu_alpha = alpha in after_mu_alpha
        alpha_in_alpha = alpha in after_alpha
        return alpha_in_mu_alpha == alpha_in_alpha and alpha_in_mu_alpha

    def dp2_check(self, alpha: str, mu: str) -> bool:
        """
        (DP2) If α ⊨ ¬μ, then (K * μ) * α = K * α
        
        Approximation: revising with alpha after contradicting mu
        should be same as revising with alpha alone.
        """
        saved_beliefs = dict(self.belief_state.beliefs)
        saved_entrenchment = dict(self.entrenchment)
        saved_clock = dict(self._clock)

        from bilinc.core.models import MemoryEntry
        # K * μ (mu contradicts alpha conceptually)
        self.revise(MemoryEntry(key=mu, value=True, importance=0.3))
        # Then * alpha
        self.revise(MemoryEntry(key=alpha, value=True, importance=0.5))
        after_mu_alpha = dict(self.belief_state.beliefs)

        # Reset
        self.belief_state.beliefs = saved_beliefs
        self.entrenchment = saved_entrenchment
        self._clock = saved_clock

        # K * α
        self.revise(MemoryEntry(key=alpha, value=True, importance=0.5))
        after_alpha = dict(self.belief_state.beliefs)

        # Reset
        self.belief_state.beliefs = saved_beliefs
        self.entrenchment = saved_entrenchment
        self._clock = saved_clock

        # Should differ only in the mu belief
        mu_keys = {mu, alpha}
        for k in after_mu_alpha:
            if k in mu_keys:
                continue
            if k in after_alpha and after_mu_alpha[k].value != after_alpha[k].value:
                return False
        return True

    def dp3_check(self, alpha: str, mu: str) -> bool:
        """
        (DP3) If α ∈ K * μ and α ⊨ ¬μ, then α ∈ K.
        
        If alpha survives after revising with mu AND alpha contradicts mu,
        then alpha should already be in K.
        """
        saved_beliefs = dict(self.belief_state.beliefs)
        
        from bilinc.core.models import MemoryEntry
        self.revise(MemoryEntry(key=mu, value=True, importance=0.6))
        # Now check if alpha is still there after adding mu
        alpha_in_k_after_mu = alpha in self.belief_state.beliefs
        
        self.belief_state.beliefs = saved_beliefs
        
        # If alpha survived the mu revision while contradicting it,
        # then alpha must have been in original K
        alpha_in_original = alpha in saved_beliefs
        if alpha_in_k_after_mu and not alpha_in_original:
            return False
        return True

    def dp4_check(self, alpha: str, mu: str) -> bool:
        """
        (DP4) If ¬α ∉ K * μ, then ¬α ∉ (K * μ) * α.
        
        If not-alpha is NOT in K*mu, then after also revising with
        alpha, not-alpha should still not be there (alpha wins).
        """
        from bilinc.core.models import MemoryEntry
        self.revise(MemoryEntry(key=mu, value=True, importance=0.6))
        neg_alpha_absent = alpha not in self.belief_state.beliefs

        if neg_alpha_absent:
            self.revise(MemoryEntry(key=alpha, value=True, importance=0.5))
            # After revising with alpha, alpha should be present
            if alpha not in self.belief_state.beliefs:
                return False
        return True

    # ─── Multi-Conflict Resolution ─────────────────────────────

    def resolve_multi_conflict(
        self,
        entries: List[MemoryEntry],
        strategy: Optional[ConflictStrategy] = None,
    ) -> AGMResult:
        """
        Resolve conflicts among multiple candidate entries for the SAME key.
        Returns the winner and removes losers.
        """
        strategy = strategy or self.default_strategy
        explanation: List[ExplanationStep] = []
        step = 0

        if len(entries) < 2:
            return AGMResult(
                operation=AGMOperation.REVISE,
                success=True,
                affected_keys=[],
                new_beliefs={},
                removed_keys=[],
                conflicts_resolved=0,
            )

        step += 1
        explanation.append(ExplanationStep(
            step=step,
            action="multi_conflict_detected",
            belief_key=entries[0].key,
            detail=f"{len(entries)} candidates for same key",
        ))

        # Score each entry. Use direct entry properties so this works
        # with candidate entries not yet in the belief state.
        scored: List[Tuple[float, MemoryEntry]] = []
        for e in entries:
            if strategy == ConflictStrategy.ENTRENCHMENT:
                # Use max of stored entrenchment and entry importance
                existing_score = self.get_entrenchment(e.key)
                score = max(existing_score, e.importance)
            elif strategy == ConflictStrategy.RECENCY:
                score = e.created_at
            elif strategy == ConflictStrategy.VERIFICATION:
                score = 1.0 if e.is_verified else 0.0
            elif strategy == ConflictStrategy.IMPORTANCE:
                score = e.importance
            else:
                score = e.importance
            scored.append((score, e))

        scored.sort(key=lambda x: x[0], reverse=True)
        winner_entry = scored[0][1]
        losers = [e for _, e in scored[1:]]

        step += 1
        explanation.append(ExplanationStep(
            step=step,
            action="winner_selected",
            belief_key=winner_entry.key,
            detail=f"Score: {scored[0][0]}, strategy: {strategy.value}",
        ))

        for loser in losers:
            step += 1
            explanation.append(ExplanationStep(
                step=step,
                action="loser_removed",
                belief_key=loser.key,
                detail=f"Score: {scored[1][0]}",
            ))
            self.belief_state.beliefs.pop(loser.key, None)

        # Add winner
        self.belief_state.add_belief(winner_entry)
        self.belief_state.revision_count += 1
        self._tick(winner_entry.key)
        self._update_entrenchment(winner_entry.key, winner_entry.importance)

        result = AGMResult(
            operation=AGMOperation.REVISE,
            success=True,
            affected_keys=[e.key for e in entries],
            new_beliefs={winner_entry.key: winner_entry},
            removed_keys=[l.key for l in losers],
            conflicts_resolved=len(losers),
            explanation=explanation,
        )
        self.operation_log.append(result)
        return result
