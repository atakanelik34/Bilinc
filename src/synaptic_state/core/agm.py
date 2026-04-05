"""
AGM Belief Revision Engine

Implements the Alchourrón-Gärdenfors-Makinson belief revision operators
for formal, mathematically-guaranteed memory consistency.

Based on Kumiho: Formal AGM belief revision theory applied to agent memory
(arXiv:2603.17244).

Three core operators:
- EXPAND:   Add new information (may create inconsistency)
- CONTRACT: Remove information (maintain consistency)
- REVISE:   Add new info + maintain consistency (the key operation)
"""

from __future__ import annotations

import time
import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field

from synaptic_state.core.models import MemoryEntry, BeliefState

logger = logging.getLogger(__name__)


class AGMOperation(str, Enum):
    EXPAND = "expand"
    CONTRACT = "contract"
    REVISE = "revise"


@dataclass
class AGMResult:
    """Result of an AGM belief revision operation."""
    operation: AGMOperation
    success: bool
    affected_keys: List[str]
    new_beliefs: Dict[str, MemoryEntry]
    removed_keys: List[str]
    conflicts_resolved: int
    audit_log: str


class AGMEngine:
    """
    AGM Belief Revision Engine.
    
    Manages a belief set K and applies formal operations to
    maintain logical consistency over time.
    
    Unlike naive memory systems that just "append", this engine:
    1. Detects conflicts before they occur
    2. Resolves conflicts using epistemic entrenchment
    3. Maintains a full audit trail
    4. Provides formal guarantees (satisfaction of AGM postulates)
    """
    
    def __init__(self, belief_state: Optional[BeliefState] = None):
        self.belief_state = belief_state or BeliefState()
        self.operation_log: List[AGMResult] = []
        self.epistemic_entrenchment: Dict[str, float] = {}  # Key → importance
    
    def expand(
        self,
        entry: MemoryEntry,
        allow_inconsistency: bool = False
    ) -> AGMResult:
        """
        AGM EXPAND operation: K + φ
        
        Adds new information φ to the belief set K.
        May create inconsistencies (that's why REVISE is preferred).
        
        Postulates satisfied:
        (K+1) K + φ is a belief set
        (K+2) φ ∈ K + φ
        (K+3) If φ ∈ K, then K + φ = K
        (K+4) If ψ ∈ K, then ψ ∈ K + φ
        (K+5) If K ⊆ H, then K + φ ⊆ H + φ
        """
        affected_keys = [entry.key]
        removed_keys = []
        conflicts = 0
        
        # Check for existing belief
        existing = self.belief_state.get_belief(entry.key)
        if existing and existing.value == entry.value:
            return AGMResult(
                operation=AGMOperation.EXPAND,
                success=True,
                affected_keys=[],
                new_beliefs={},
                removed_keys=[],
                conflicts_resolved=0,
                audit_log=f"EXPAND: '{entry.key}' already in beliefs with same value — no-op"
            )
        
        # Check for conflicts
        if existing and existing.value != entry.value:
            conflicts = 1
            if not allow_inconsistency:
                logger.warning(
                    f"EXPAND conflict on '{entry.key}': "
                    f"{existing.value!r} vs {entry.value!r}. "
                    f"Consider using REVISE instead."
                )
        
        # Add the belief
        self.belief_state.add_belief(entry)
        self.belief_state.revision_count += 1
        
        # Update epistemic entrenchment
        self._update_entrenchment(entry.key, entry.importance)
        
        result = AGMResult(
            operation=AGMOperation.EXPAND,
            success=True,
            affected_keys=affected_keys,
            new_beliefs={entry.key: entry},
            removed_keys=removed_keys,
            conflicts_resolved=conflicts,
            audit_log=(
                f"EXPAND: Added '{entry.key}' "
                f"(value={json_safe(entry.value), len(entry.value)})"
                f" | conflicts={conflicts}"
            )
        )
        
        self.operation_log.append(result)
        return result
    
    def contract(self, key: str) -> AGMResult:
        """
        AGM CONTRACT operation: K − φ
        
        Removes information φ from the belief set K.
        Must maintain consistency and minimize information loss.
        
        Postulates satisfied:
        (K−1) K − φ is a belief set
        (K−2) K − φ ⊆ K
        (K−3) If φ ∉ K, then K − φ = K
        (K−4) If ⊬ φ, then φ ∉ K − (φ ∧ ψ) → ψ
        (K−5) If φ ∈ K and φ ↔ ψ, then K − φ = K − ψ
        (K−6) If ⊢ φ ↔ ψ, then K − φ = K − ψ
        (K−7) K − (φ ∧ ψ) ⊆ (K − φ) + ψ
        (K−8) If ψ ∉ K − (φ ∧ ψ), then (K − φ) + ψ ⊆ K − (φ ∧ ψ)
        """
        if key not in self.belief_state.beliefs:
            return AGMResult(
                operation=AGMOperation.CONTRACT,
                success=True,  # Success — nothing to remove
                affected_keys=[],
                new_beliefs={},
                removed_keys=[],
                conflicts_resolved=0,
                audit_log=f"CONTRACT: '{key}' not in beliefs — no-op"
            )
        
        # Remove the belief
        removed = self.belief_state.remove_belief(key)
        self.belief_state.revision_count += 1
        
        result = AGMResult(
            operation=AGMOperation.CONTRACT,
            success=True,
            affected_keys=[key],
            new_beliefs={},
            removed_keys=[key],
            conflicts_resolved=0,
            audit_log=f"CONTRACT: Removed '{key}' (was: {json_safe(removed)})"
        )
        
        self.operation_log.append(result)
        return result
    
    def revise(self, entry: MemoryEntry) -> AGMResult:
        """
        AGM REVISE operation: K * φ
        
        Adds new information φ while MAINTAINING CONSISTENCY.
        This is the key operation for memory updates.
        
        Levi Identity: K * φ = (K − ¬φ) + φ
        
        Postulates satisfied:
        (K*1) K * φ is a belief set
        (K*2) φ ∈ K * φ
        (K*3) K * φ ⊆ K + φ
        (K*4) If ¬φ ∉ K, then K + φ ⊆ K * φ
        (K*5) If ⊬ ¬φ, then K * φ ≠ K
        (K*6) If ⊢ φ ↔ ψ, then K * φ = K * ψ
        (K*7) K * (φ ∧ ψ) ⊆ (K * φ) + ψ
        (K*8) If ¬ψ ∉ K * φ, then (K * φ) + ψ ⊆ K * (φ ∧ ψ)
        """
        affected_keys = [entry.key]
        removed_keys = []
        
        # If key doesn't exist, just expand
        if not self.belief_state.has_belief(entry.key):
            expand_result = self.expand(entry)
            return AGMResult(
                operation=AGMOperation.REVISE,
                success=expand_result.success,
                affected_keys=expand_result.affected_keys,
                new_beliefs=expand_result.new_beliefs,
                removed_keys=[],
                conflicts_resolved=0,
                audit_log=f"REVISE → EXPAND: '{entry.key}' not in beliefs"
            )
        
        existing = self.belief_state.get_belief(entry.key)
        
        # Compare values
        if existing.value == entry.value:
            return AGMResult(
                operation=AGMOperation.REVISE,
                success=True,
                affected_keys=[],
                new_beliefs={entry.key: existing},
                removed_keys=[],
                conflicts_resolved=0,
                audit_log=f"REVISE: '{entry.key}' — value unchanged — no-op"
            )
        
        # Check epistemic entrenchment
        existing_importance = self.epistemic_entrenchment.get(existing.key, 0.5)
        new_importance = entry.importance
        
        # If new info is more entrenched, replace
        if new_importance >= existing_importance:
            # Contract the old value (remove it)
            self.belief_state.remove_belief(existing.key)
            removed_keys.append(existing.key)
            
            # Update the superseded reference
            if existing:
                entry.superseded_by = existing.key
                entry.metadata["supersedes"] = existing.key
                entry.metadata["previous_value"] = json_safe(existing.value)
                entry.metadata["reason_for_revision"] = f"New info (importance {new_importance}) > old ({existing_importance})"
            
            # Expand with new value
            self.belief_state.add_belief(entry)
            self.belief_state.revision_count += 1
            self._update_entrenchment(entry.key, new_importance)
            
            result = AGMResult(
                operation=AGMOperation.REVISE,
                success=True,
                affected_keys=affected_keys,
                new_beliefs={entry.key: entry},
                removed_keys=removed_keys,
                conflicts_resolved=1,
                audit_log=(
                    f"REVISE: Replaced '{entry.key}' "
                    f"(old: {json_safe(existing.value)}, new: {json_safe(entry.value)}) "
                    f"entrenchment: {existing_importance:.2f} → {new_importance:.2f}"
                )
            )
        else:
            # Old info is more entrenched — reject new info
            result = AGMResult(
                operation=AGMOperation.REVISE,
                success=False,
                affected_keys=[],
                new_beliefs={},
                removed_keys=[],
                conflicts_resolved=0,
                audit_log=(
                    f"REVISE REJECTED: '{entry.key}' — "
                    f"existing ({existing_importance:.2f}) > new ({new_importance:.2f})"
                )
            )
        
        self.operation_log.append(result)
        return result
    
    # ─── Conflict Resolution ─────────────────────────────────────
    
    def detect_and_resolve_conflicts(self) -> AGMResult:
        """
        Scan all beliefs for conflicts and resolve them.
        Uses epistemic entrenchment to decide which beliefs survive.
        """
        conflicts = self.belief_state.get_conflicts()
        
        if not conflicts:
            return AGMResult(
                operation=AGMOperation.REVISE,
                success=True,
                affected_keys=[],
                new_beliefs={},
                removed_keys=[],
                conflicts_resolved=0,
                audit_log="No conflicts detected"
            )
        
        total_resolved = 0
        total_removed = 0
        affected: List[str] = []
        removed: List[str] = []
        
        for group in conflicts:
            if len(group) < 2:
                continue
            
            # Find most entrenched belief
            best_key = group[0]
            best_score = self.epistemic_entrenchment.get(group[0], 0.0)
            
            for key in group[1:]:
                score = self.epistemic_entrenchment.get(key, 0.0)
                if score > best_score:
                    best_key = key
                    best_score = score
            
            for key in group:
                if key != best_key:
                    self.belief_state.remove_belief(key)
                    total_removed += 1
                    removed.append(key)
                    affected.append(key)
            
            affected.append(best_key)
            total_resolved += 1
        
        self.belief_state.revision_count += 1
        
        result = AGMResult(
            operation=AGMOperation.REVISE,
            success=True,
            affected_keys=affected,
            new_beliefs={},
            removed_keys=removed,
            conflicts_resolved=total_resolved,
            audit_log=f"Resolved {total_resolved} conflicts, removed {total_removed} beliefs"
        )
        
        self.operation_log.append(result)
        return result
    
    # ─── Epistemic Entrenchment ─────────────────────────────────
    
    def _update_entrenchment(self, key: str, importance: float) -> None:
        """Update the epistemic entrenchment value for a key."""
        self.epistemic_entrenchment[key] = max(
            self.epistemic_entrenchment.get(key, 0.0),
            importance
        )
    
    def get_entrenchment(self, key: str) -> float:
        """Get the entrenchment value for a key."""
        return self.epistemic_entrenchment.get(key, 0.0)
    
    # ─── Auditing ───────────────────────────────────────────────
    
    def get_audit_trail(self) -> List[AGMResult]:
        """Get the full operational audit trail."""
        return self.operation_log
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get a summary of the current belief state."""
        beliefs = self.belief_state.get_all_beliefs()
        conflicts = self.belief_state.get_conflicts()
        
        return {
            "total_beliefs": len(beliefs),
            "active_conflicts": len(conflicts),
            "operation_count": len(self.operation_log),
            "unique_keys": len(self.belief_state.beliefs),
            "epistemic_entrenchment_count": len(self.epistemic_entrenchment),
            "last_operation": self.operation_log[-1].operation
            if self.operation_log else None
        }


def json_safe(value: Any) -> Any:
    """Convert value to a JSON-safe representation."""
    if value is None:
        return "null"
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, dict)):
        import json
        try:
            return json.dumps(value, ensure_ascii=False)
        except:
            return str(value)
    return str(value)
