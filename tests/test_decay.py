"""
Tests for hybrid decay model.
"""
import math
import time
import pytest
from bilinc.core.decay import (
    DecayProfile, LTPStatus, compute_ltp_status, hybrid_decay_factor,
    access_frequency_boost, compute_new_strength, decay_for_entry,
    should_prune, decay_preview,
)

class TestDecayProfile:
    def test_all_types_have_profiles(self):
        for mt in ["working", "episodic", "procedural", "semantic", "spatial"]:
            p = DecayProfile.for_memory_type(mt)
            assert p.base_rate > 0 and p.half_life_days > 0
    def test_working_decays_fastest(self):
        w = DecayProfile.for_memory_type("working")
        s = DecayProfile.for_memory_type("semantic")
        assert w.base_rate > s.base_rate and w.half_life_days < s.half_life_days
    def test_unknown_defaults_to_semantic(self):
        assert DecayProfile.for_memory_type("x").base_rate == DecayProfile.for_memory_type("semantic").base_rate

class TestLTP:
    def test_full(self):
        assert compute_ltp_status(0.95, 0.9) == LTPStatus.FULL
    def test_weekly(self):
        assert compute_ltp_status(0.75) == LTPStatus.WEEKLY
    def test_burst(self):
        assert compute_ltp_status(0.5) == LTPStatus.BURST
    def test_none(self):
        assert compute_ltp_status(0.3) == LTPStatus.NONE

class TestHybridDecay:
    def test_zero_days(self):
        assert hybrid_decay_factor(0.0, DecayProfile.for_memory_type("semantic")) == 1.0
    def test_exponential_phase(self):
        p = DecayProfile.for_memory_type("semantic")
        f = hybrid_decay_factor(1.0, p)
        assert abs(f - math.exp(-p.base_rate)) < 0.001
    def test_power_law_preserves_more_than_exp(self):
        p = DecayProfile.for_memory_type("episodic")
        f100 = hybrid_decay_factor(100.0, p)
        pure_exp = math.exp(-p.base_rate * 100.0)
        assert f100 > pure_exp
    def test_ltp_slows(self):
        p = DecayProfile.for_memory_type("semantic")
        assert hybrid_decay_factor(7.0, p, LTPStatus.FULL) > hybrid_decay_factor(7.0, p, LTPStatus.NONE)

class TestAccessBoost:
    def test_no_access(self):
        assert access_frequency_boost(0) == 1.0
    def test_frequent(self):
        assert access_frequency_boost(0) < access_frequency_boost(10) < access_frequency_boost(25)

class TestComputeNewStrength:
    def test_zero_days(self):
        s, m = compute_new_strength(0.8, "semantic", 0.0)
        assert s == 0.8
    def test_decreases(self):
        s, _ = compute_new_strength(1.0, "episodic", 7.0)
        assert s < 1.0
    def test_importance_preserves(self):
        low, _ = compute_new_strength(1.0, "semantic", 30.0, importance=0.3)
        high, _ = compute_new_strength(1.0, "semantic", 30.0, importance=0.95, verification_score=0.9)
        assert high > low
    def test_working_decays_faster(self):
        w, _ = compute_new_strength(1.0, "working", 2.0)
        s, _ = compute_new_strength(1.0, "semantic", 2.0)
        assert w < s

class TestPrune:
    def test_strong(self):
        assert not should_prune(0.5, "semantic")
    def test_weak_working(self):
        assert should_prune(0.2, "working")
    def test_weak_semantic(self):
        assert should_prune(0.01, "semantic")

class TestPreview:
    def test_starts_at_one(self):
        assert decay_preview("semantic", days=30)[0] == (0, 1.0)
    def test_decreases(self):
        p = decay_preview("semantic", days=30)
        assert all(p[i][1] >= p[i+1][1] for i in range(len(p)-1))
    def test_ltp_preserves(self):
        no = decay_preview("semantic", importance=0.3, days=90)
        full = decay_preview("semantic", importance=0.95, verification_score=0.9, days=90)
        assert full[-1][1] > no[-1][1]

class TestDecayForEntry:
    def test_dict(self):
        entry = {"current_strength": 0.8, "memory_type": "semantic", "importance": 0.7,
                 "verification_score": 0.0, "access_count": 5,
                 "created_at": time.time() - 86400*7, "last_accessed": time.time() - 86400*7}
        s = decay_for_entry(entry)
        assert 0.0 <= s <= 0.8