"""
Tests for the AGM Postulate Engine (Step 3.1).

Covering:
1. AGM EXPAND — simple addition, no conflict
2. AGM CONTRACT — removal with closure maintenance
3. AGM REVISE — conflict resolution via entrenchment
4. Darwiche & Pearl iterated revision postulates (DP1-DP4)
5. Explanation trail — full audit of revision steps
6. Multi-conflict resolution with different strategies
"""

import pytest
import time
from bilinc.core.models import MemoryType, MemoryEntry, BeliefState
from bilinc.adaptive.agm_engine import (
    AGMEngine,
    AGMOperation,
    AGMResult,
    ConflictStrategy,
    ExplanationStep,
)


# ── Helpers ───────────────────────────────────────────────────

def _entry(key: str, value, importance: float = 1.0, verified: bool = False) -> MemoryEntry:
    return MemoryEntry(
        key=key,
        value=value,
        importance=importance,
        is_verified=verified,
        memory_type=MemoryType.SEMANTIC,
    )


@pytest.fixture
def engine():
    return AGMEngine(default_strategy=ConflictStrategy.ENTRENCHMENT)


# ── Test 1: EXPAND ────────────────────────────────────────────

class TestAGMExpand:
    def test_agm_expand_simple(self, engine: AGMEngine):
        """Simple addition, no conflict — EXPAND should succeed."""
        entry = _entry("user_pref_theme", "dark", importance=0.8)
        result = engine.expand(entry)

        assert result.operation == AGMOperation.EXPAND
        assert result.success is True
        assert "user_pref_theme" in result.affected_keys
        assert "user_pref_theme" in result.new_beliefs
        assert result.conflicts_resolved == 0

        # Verify in belief state
        stored = engine.belief_state.get_belief("user_pref_theme")
        assert stored is not None
        assert stored.value == "dark"

    def test_agm_expand_existing_same_value_no_op(self, engine: AGMEngine):
        """EXPAND with same key+value should be a no-op."""
        entry = _entry("lang", "tr")
        engine.expand(entry)
        result = engine.expand(entry)  # second time

        assert result.success is True
        assert result.affected_keys == []
        assert result.new_beliefs == {}

    def test_agm_expand_conflict_warning(self, engine: AGMEngine):
        """EXPAND with conflicting value should warn but not resolve."""
        entry_old = _entry("mode", "production", importance=0.9)
        entry_new = _entry("mode", "staging", importance=0.3)

        engine.expand(entry_old)
        result = engine.expand(entry_new, allow_inconsistency=False)

        assert result.success is True
        # The new value overwrites (expand is naive)
        stored = engine.belief_state.get_belief("mode")
        assert stored is not None
        # But it should log a conflict step
        exp_steps = [s for s in result.explanation if s.action == "detected_conflict"]
        assert len(exp_steps) >= 1


# ── Test 2: CONTRACT ──────────────────────────────────────────

class TestAGMContract:
    def test_agm_contract_removal(self, engine: AGMEngine):
        """Removal with closure maintenance."""
        engine.expand(_entry("temp_key", "temp_value"))
        assert engine.has_belief("temp_key")

        result = engine.contract("temp_key")

        assert result.operation == AGMOperation.CONTRACT
        assert result.success is True
        assert result.removed_keys == ["temp_key"]
        assert not engine.has_belief("temp_key")
        assert "temp_key" not in engine.entrenchment

    def test_agm_contract_missing_key_no_op(self, engine: AGMEngine):
        """Contract a key that doesn't exist should be a no-op."""
        result = engine.contract("nonexistent")

        assert result.success is True
        assert result.removed_keys == []
        assert result.affected_keys == []


# ── Test 3: REVISE with Conflict ──────────────────────────────

class TestAGMRevise:
    def test_agm_revise_conflict_entrenchment(self, engine: AGMEngine):
        """Add conflicting belief, resolve via entrenchment."""
        # Existing: high importance
        engine.revise(_entry("db_host", "localhost", importance=0.9))
        engine.set_entrenchment("db_host", 0.95)

        # New: low importance
        new_entry = _entry("db_host", "prod.db.internal", importance=0.3)
        result = engine.revise(new_entry)

        assert result.success is False  # Old is more entrenched
        assert result.conflicts_resolved == 0
        assert len(result.explanation) >= 3

        # Old value should remain
        stored = engine.belief_state.get_belief("db_host")
        assert stored is not None
        assert stored.value == "localhost"

    def test_agm_revise_newer_wins(self, engine: AGMEngine):
        """New entry with higher importance should replace."""
        engine.revise(_entry("api_key", "old_key", importance=0.3))

        new_entry = _entry("api_key", "new_key", importance=0.8)
        result = engine.revise(new_entry)

        assert result.success is True
        assert result.conflicts_resolved == 1
        assert result.removed_keys == ["api_key"]

        stored = engine.belief_state.get_belief("api_key")
        assert stored is not None
        assert stored.value == "new_key"

    def test_agm_revise_new_key_is_expand(self, engine: AGMEngine):
        """REVISE on non-existent key should behave like EXPAND."""
        result = engine.revise(_entry("new_feature_flag", True))

        assert result.success is True
        assert result.conflicts_resolved == 0
        assert engine.has_belief("new_feature_flag")


# ── Test 4: Darwiche & Pearl Postulates ───────────────────────

class TestDarwichePearlPostulates:
    def test_agm_dp1_postulate(self, engine: AGMEngine):
        """(DP1) If α ⊨ μ, then (K * μ) * α = K * α"""
        # Simplified check: if alpha implies mu, revising alpha after mu
        # should equal revising alpha directly.
        assert engine.dp1_check("important_setting_mu", "important_setting") is True

    def test_agm_dp2_postulate(self, engine: AGMEngine):
        """(DP2) If α ⊨ ¬μ, then (K * μ) * α = K * α"""
        assert engine.dp2_check("alpha_setting", "contradicting_mu") is True

    def test_agm_dp3_postulate(self, engine: AGMEngine):
        """(DP3) If α ∈ K * μ and α ⊨ ¬μ, then α ∈ K"""
        engine.expand(_entry("existing_alpha", True))
        assert engine.dp3_check("existing_alpha", "new_mu") is True

    def test_agm_dp4_postulate(self, engine: AGMEngine):
        """(DP4) If ¬α ∉ K * μ, then ¬α ∉ (K * μ) * α"""
        assert engine.dp4_check("alpha_key", "mu_key") is True


# ── Test 5: Explanation Trail ─────────────────────────────────

class TestExplanationTrail:
    def test_agm_explanation_trail(self, engine: AGMEngine):
        """Full explanation of revision steps should be logged."""
        engine.expand(_entry("config_mode", "debug", importance=0.5))
        new = _entry("config_mode", "release", importance=0.7)
        result = engine.revise(new)

        # Should have multiple explanation steps
        steps = result.explanation
        assert len(steps) >= 3  # conflict_detected, comparing, contracted/expanded

        # Check step types
        actions = [s.action for s in steps]
        assert "conflict_detected" in actions
        assert "comparing_entrenchment" in actions
        assert any(a in actions for a in ["contracted_old", "expanded_new"])

        # Text representation should be non-empty
        assert len(result.explanation_text) > 0

    def test_audit_log_alias(self, engine: AGMEngine):
        """audit_log property should return explanation_text."""
        engine.expand(_entry("k", "v"))
        result = engine.contract("k")
        assert result.audit_log == result.explanation_text


# ── Test 6: Multi-Conflict Resolution ─────────────────────────

class TestMultiConflict:
    def test_agm_multi_conflict_entrenchment(self, engine: AGMEngine):
        """Multiple entries for same key, entrenchment strategy picks winner."""
        # Pre-populate state with existing belief
        engine.expand(_entry("db_url", "localhost:5432", importance=0.2))
        
        # Now resolve with new candidates
        new_entries = [
            engine.belief_state.get_belief("db_url"),  # existing
            _entry("db_url", "staging:5432", importance=0.5),
            _entry("db_url", "prod:5432", importance=0.9),
        ]
        result = engine.resolve_multi_conflict(new_entries, ConflictStrategy.ENTRENCHMENT)

        assert result.success is True
        assert result.conflicts_resolved == 2

        # Winner should be the highest importance
        stored = engine.belief_state.get_belief("db_url")
        assert stored is not None
        assert stored.value == "prod:5432"

    def test_agm_multi_conflict_recency(self, engine: AGMEngine):
        """Recency strategy should prefer newest entry."""
        e1 = _entry("version", "1.0.0", importance=0.9)
        e1.created_at = time.time() - 3600

        e2 = _entry("version", "2.0.0", importance=0.1)
        e2.created_at = time.time()

        result = engine.resolve_multi_conflict([e1, e2], ConflictStrategy.RECENCY)

        assert result.success is True
        assert result.conflicts_resolved == 1
        stored = engine.belief_state.get_belief("version")
        assert stored is not None
        assert stored.value == "2.0.0"

    def test_agm_multi_conflict_verification(self, engine: AGMEngine):
        """Verification strategy should prefer verified entry."""
        e_unverified = _entry("cert", "unverified_cert", importance=0.95, verified=False)
        e_verified = _entry("cert", "verified_cert", importance=0.3, verified=True)

        result = engine.resolve_multi_conflict([e_unverified, e_verified], ConflictStrategy.VERIFICATION)

        assert result.success is True
        stored = engine.belief_state.get_belief("cert")
        assert stored is not None
        assert stored.value == "verified_cert"

    def test_agm_multi_conflict_importance(self, engine: AGMEngine):
        """Importance strategy should pick highest importance."""
        entries = [
            _entry("rule", "low_priority", importance=0.1),
            _entry("rule", "med_priority", importance=0.5),
            _entry("rule", "high_priority", importance=1.0),
        ]

        result = engine.resolve_multi_conflict(entries, ConflictStrategy.IMPORTANCE)

        assert result.conflicts_resolved == 2
        stored = engine.belief_state.get_belief("rule")
        assert stored is not None
        assert stored.value == "high_priority"
