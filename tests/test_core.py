"""Tests for core components: models, verification, AGM, StatePlane."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from synaptic_state.core.models import MemoryEntry, MemoryType, BeliefState
from synaptic_state.core.agm import AGMEngine, AGMOperation
from synaptic_state.core.verification import VerificationGate, VerificationStatus
from synaptic_state.core.stateplane import StatePlane


class TestMemoryEntry:
    def test_creation(self):
        entry = MemoryEntry(key="test", value="hello", memory_type=MemoryType.EPISODIC)
        assert entry.key == "test"
        assert entry.value == "hello"
        assert entry.memory_type == MemoryType.EPISODIC
        assert entry.is_verified is False
        assert entry.current_strength == 1.0

    def test_staleness(self):
        entry = MemoryEntry(key="test", value="data", ttl=1.0)
        import time
        time.sleep(0.1)  # Just check it doesn't crash
        assert not entry.is_stale()


class TestVerificationGate:
    def test_pass(self):
        gate = VerificationGate()
        entry = MemoryEntry(
            key="test",
            value="data",
            verification_score=0.8,
        )
        result = gate.verify(entry)
        assert result.status == VerificationStatus.PASS

    def test_low_confidence(self):
        gate = VerificationGate(min_confidence=0.5)
        entry = MemoryEntry(
            key="test",
            value="data",
            verification_score=0.3,
        )
        result = gate.verify(entry)
        assert result.status == VerificationStatus.LOW_CONFIDENCE


class TestAGMEngine:
    def test_expand(self):
        engine = AGMEngine()
        entry = MemoryEntry(key="k1", value="v1")
        result = engine.expand(entry)
        assert result.success is True
        assert "k1" in result.new_beliefs

    def test_contract(self):
        engine = AGMEngine()
        entry = MemoryEntry(key="k1", value="v1")
        engine.expand(entry)
        
        result = engine.contract("k1")
        assert result.success is True
        assert "k1" in result.removed_keys

    def test_revise(self):
        engine = AGMEngine()
        old = MemoryEntry(key="pref", value="dark", importance=0.5)
        engine.expand(old)
        
        new = MemoryEntry(key="pref", value="light", importance=0.7)
        result = engine.revise(new)
        assert result.success is True
        assert result.conflicts_resolved >= 1

    def test_revise_reject(self):
        engine = AGMEngine()
        old = MemoryEntry(key="pref", value="dark", importance=0.9)
        engine.expand(old)
        
        new = MemoryEntry(key="pref", value="light", importance=0.3)
        result = engine.revise(new)
        assert result.success is False


class TestStatePlane:
    def test_commit_and_recall(self):
        plane = StatePlane()
        
        # Commit
        result = plane.commit(
            key="editor",
            value={"theme": "dark", "tabs": 2},
            memory_type="semantic",
        )
        assert result["status"] == "SUCCESS"
        
        # Recall
        recalled = plane.recall(intent="editor settings")
        assert len(recalled.memories) >= 1
        found = [m for m in recalled.memories if m.key == "editor"]
        assert len(found) >= 1
        assert found[0].value["theme"] == "dark"

    def test_forget(self):
        plane = StatePlane()
        plane.commit(key="temp", value="forget_me")
        entry = plane.forget("temp")
        assert entry is not None
        assert entry.value == "forget_me"

    def test_drift_report(self):
        plane = StatePlane()
        plane.commit(key="a", value="1")
        plane.commit(key="b", value="2")
        report = plane.get_drift_report()
        assert report["total_entries"] == 2
        assert 0 <= report["drift_score"] <= 1
        assert 0 <= report["quality_score"] <= 1

    def test_stats(self):
        plane = StatePlane()
        plane.commit(key="x", value="1")
        plane.commit(key="y", value="2")
        plane.recall(intent="test")
        stats = plane.get_stats()
        assert stats["total_commits"] == 2
        assert stats["total_recalls"] == 1


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
