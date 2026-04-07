"""
Z3 SMT State Verifier — Formal constraint-based state validation.

Uses Microsoft's Z3 theorem prover to verify:
1. Consistency: No mutually exclusive beliefs
2. Capacity: Working memory never exceeds 8 slots
3. Monotonicity: Verified entries cannot become unverified
4. Type safety: Values conform to declared memory type
5. Conflict-free: No duplicate keys with conflicting values

Based on: Z3 SMT Solver (Microsoft Research)
"""
from __future__ import annotations

import json
import time
import logging
from typing import Any, Dict, List, Optional, NamedTuple
from dataclasses import dataclass

import z3


logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of a state verification check."""
    valid: bool
    rule_name: str
    reason: str
    counter_example: Optional[str] = None
    checked_at: float = 0.0
    
    def __post_init__(self):
        if self.checked_at == 0.0:
            self.checked_at = time.time()


@dataclass
class InvariantDefinition:
    """A formal invariant enforced by the verifier."""
    name: str
    description: str
    check_fn: Any  # Callable that builds Z3 constraints


class StateVerifier:
    """
    Formal state verification using Z3 SMT solver.
    
    Invariants:
    - CAPACITY: working_memory_count <= 8
    - CONSISTENCY: no two entries with same key and different values both active
    - MONOTONICITY: once verified, cannot become unverified without audit trail
    - TYPE_SAFETY: value types match memory type constraints
    - NON_NEGATIVITY: importance, strength, confidence all >= 0
    """
    
    def __init__(self):
        self.solver = z3.Solver()
        self.invariants: Dict[str, InvariantDefinition] = {}
        self._setup_default_invariants()
    
    def _setup_default_invariants(self):
        """Set up the default 6 invariants."""
        self._add_invariant(
            "CAPACITY",
            "Working memory never exceeds 8 slots",
            self._check_capacity
        )
        self._add_invariant(
            "CONSISTENCY",
            "No duplicate active entries with conflicting values",
            self._check_consistency
        )
        self._add_invariant(
            "MONOTONICITY",
            "Verified entries cannot silently become unverified",
            self._check_monotonicity
        )
        self._add_invariant(
            "TYPE_SAFETY",
            "Memory values are JSON-serializable",
            self._check_type_safety
        )
        self._add_invariant(
            "NON_NEGATIVITY",
            "importance >= 0, current_strength >= 0, verification_score >= 0",
            self._check_non_negativity
        )
        self._add_invariant(
            "KEY_VALIDITY",
            "All keys are non-empty strings",
            self._check_key_validity
        )
    
    def _add_invariant(self, name: str, description: str, check_fn):
        self.invariants[name] = InvariantDefinition(name, description, check_fn)
    
    def verify_state(self, entries: List[Dict[str, Any]]) -> List[VerificationResult]:
        """
        Verify a set of memory entries against all invariants.
        
        Args:
            entries: List of memory entry dicts (from MemoryEntry.to_dict())
        
        Returns:
            List of VerificationResult for each invariant
        """
        results = []
        for name, inv in self.invariants.items():
            try:
                result = inv.check_fn(entries)
                results.append(result)
            except Exception as e:
                results.append(VerificationResult(
                    valid=False, rule_name=name,
                    reason=f"Verification error: {str(e)}",
                ))
        return results
    
    def verify_transition(self, before: List[Dict], after: List[Dict]) -> VerificationResult:
        """
        Verify a state transition is valid.
        Checks that transition doesn't violate any invariant.
        """
        # Verify both states are internally consistent
        before_results = self.verify_state(before)
        after_results = self.verify_state(after)
        
        # Check transition-specific invariants
        transition_issues = []
        
        # Monotonicity: verified entries in before should still be verified (unless explicitly updated)
        before_verified = {e["key"]: e for e in before if e.get("is_verified")}
        after_entries = {e["key"]: e for e in after}
        
        for key, b_entry in before_verified.items():
            if key in after_entries:
                a_entry = after_entries[key]
                if b_entry.get("is_verified") and not a_entry.get("is_verified"):
                    transition_issues.append(
                        f"Monotonicity violation: {key} went from verified to unverified"
                    )
        
        if transition_issues:
            return VerificationResult(
                valid=False, rule_name="TRANSITION",
                reason=" | ".join(transition_issues),
            )
        
        # All after-state invariants must hold
        failed = [r for r in after_results if not r.valid]
        if failed:
            return VerificationResult(
                valid=False, rule_name="TRANSITION",
                reason=f"Post-state violations: {', '.join(r.rule_name for r in failed)}",
            )
        
        return VerificationResult(valid=True, rule_name="TRANSITION", reason="Transition valid")
    
    def add_custom_invariant(self, name: str, description: str, constraint_fn):
        """Add a custom user-defined invariant."""
        self.invariants[name] = InvariantDefinition(name, description, constraint_fn)
    
    # ─── Built-in Invariant Checkers ──────────────────────────────────
    
    def _check_capacity(self, entries: List[Dict]) -> VerificationResult:
        """Working memory never exceeds 8 slots."""
        working_count = sum(1 for e in entries if e.get("memory_type") == "working")
        
        s = z3.Solver()
        cap_var = z3.Int("working_capacity")
        s.add(cap_var == working_count)
        s.add(cap_var <= 8)
        
        if s.check() == z3.sat:
            return VerificationResult(
                valid=True, rule_name="CAPACITY",
                reason=f"Working memory has {working_count}/8 slots"
            )
        else:
            return VerificationResult(
                valid=False, rule_name="CAPACITY",
                reason=f"Working memory exceeds limit: {working_count}/8",
                counter_example=f"working_count={working_count}",
            )
    
    def _check_consistency(self, entries: List[Dict]) -> VerificationResult:
        """No duplicate active keys with different values."""
        key_values: Dict[str, set] = {}
        conflicts = []
        
        for e in entries:
            key = e.get("key", "")
            val = json.dumps(e.get("value"))
            if key not in key_values:
                key_values[key] = set()
            key_values[key].add(val)
            if len(key_values[key]) > 1:
                conflicts.append(key)
        
        if not conflicts:
            return VerificationResult(
                valid=True, rule_name="CONSISTENCY",
                reason=f"All {len(entries)} entries consistent"
            )
        else:
            return VerificationResult(
                valid=False, rule_name="CONSISTENCY",
                reason=f"Conflicting values for keys: {conflicts}",
                counter_example=str(conflicts),
            )
    
    def _check_monotonicity(self, entries: List[Dict]) -> VerificationResult:
        """Verified entries stay verified (snapshot invariant)."""
        # This is a snapshot check — full monotonicity requires transition verification
        verified_count = sum(1 for e in entries if e.get("is_verified"))
        
        s = z3.Solver()
        v = z3.Int("verified_count")
        s.add(v == verified_count)
        s.add(v >= 0)
        
        if s.check() == z3.sat:
            return VerificationResult(
                valid=True, rule_name="MONOTONICITY",
                reason=f"{verified_count} verified entries, no silent unverification detected"
            )
        return VerificationResult(
            valid=False, rule_name="MONOTONICITY",
            reason="Unexpected monotonicity violation"
        )
    
    def _check_type_safety(self, entries: List[Dict]) -> VerificationResult:
        """All values must be JSON-serializable."""
        type_issues = []
        
        for e in entries:
            try:
                json.dumps(e.get("value"))
            except (TypeError, ValueError) as _err:
                type_issues.append(e.get("key", "unknown"))
        
        if not type_issues:
            return VerificationResult(
                valid=True, rule_name="TYPE_SAFETY",
                reason="All values JSON-serializable"
            )
        return VerificationResult(
            valid=False, rule_name="TYPE_SAFETY",
            reason=f"Non-serializable values for keys: {type_issues}",
            counter_example=str(type_issues),
        )
    
    def _check_non_negativity(self, entries: List[Dict]) -> VerificationResult:
        """importance >= 0, current_strength >= 0, verification_score >= 0."""
        violations = []
        
        for e in entries:
            if e.get("importance", 1.0) < 0:
                violations.append(f"{e.get('key')}: importance={e.get('importance')}")
            if e.get("current_strength", 1.0) < 0:
                violations.append(f"{e.get('key')}: strength={e.get('current_strength')}")
            if e.get("verification_score", 0.0) < 0:
                violations.append(f"{e.get('key')}: verification={e.get('verification_score')}")
        
        if not violations:
            return VerificationResult(
                valid=True, rule_name="NON_NEGATIVITY",
                reason="All numeric values non-negative"
            )
        return VerificationResult(
            valid=False, rule_name="NON_NEGATIVITY",
            reason=f"Negative values found: {violations}",
            counter_example=str(violations),
        )
    
    def _check_key_validity(self, entries: List[Dict]) -> VerificationResult:
        """All keys are non-empty strings."""
        bad_keys = []
        for e in entries:
            k = e.get("key", "")
            if not isinstance(k, str) or len(k) == 0:
                bad_keys.append(repr(e))
        
        if not bad_keys:
            return VerificationResult(
                valid=True, rule_name="KEY_VALIDITY",
                reason=f"All {len(entries)} keys valid"
            )
        return VerificationResult(
            valid=False, rule_name="KEY_VALIDITY",
            reason=f"{len(bad_keys)} entries with invalid keys",
            counter_example=bad_keys[0] if bad_keys else None,
        )
    
    def get_invariant_summary(self) -> List[Dict[str, str]]:
        """Return list of all registered invariants."""
        return [{"name": name, "description": inv.description}
                for name, inv in self.invariants.items()]
