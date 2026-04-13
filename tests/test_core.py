"""Tests for core components: models, verification, AGM, StatePlane."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from bilinc.core.models import MemoryEntry, MemoryType, BeliefState
from bilinc.adaptive.agm_engine import AGMEngine, AGMOperation
from bilinc.core.verification import VerificationGate, VerificationStatus
from bilinc.core.stateplane import StatePlane


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
    def test_commit_sync_and_working_memory_recall(self):
        plane = StatePlane(enable_verification=False, enable_audit=False)
        
        # Commit to working memory (default)
        entry = plane.commit_sync(
            key="editor",
            value={"theme": "dark", "tabs": 2},
            memory_type=MemoryType.WORKING,
        )
        # commit_sync returns the entry or coroutine (if async context)
        # In sync test, it's the entry itself
        assert entry is not None
        assert entry.key == "editor"
        assert entry.value["theme"] == "dark"
        
        # Verify it's in working memory
        assert plane.working_memory.count >= 1
        wm_entry = plane.working_memory.get("editor")
        assert wm_entry is not None
        assert wm_entry.value["tabs"] == 2

    def test_forget_sync(self):
        plane = StatePlane(enable_verification=False, enable_audit=False)
        plane.commit_sync(key="temp", value="forget_me", memory_type=MemoryType.WORKING)
        result = plane.forget_sync("temp")
        # forget_sync may return True/False depending on implementation
        # Main check: entry should be gone
        wm_entry = plane.working_memory.get("temp")
        assert wm_entry is None

    def test_commit_with_agm(self):
        """Phase 3: commit_with_agm should work synchronously."""
        plane = StatePlane()
        plane.init_agm()
        
        result1 = plane.commit_with_agm("key_a", "value_1", importance=0.5)
        assert result1.success is True
        
        result2 = plane.commit_with_agm("key_b", "value_2", importance=0.8)
        assert result2.success is True

    def test_phase3_stats(self):
        """Phase 3: phase3_stats should return component info."""
        plane = StatePlane()
        plane.init_agm()
        plane.init_knowledge_graph()
        
        plane.commit_with_agm("x", 1)
        plane.commit_with_agm("y", 2)
        
        stats = plane.phase3_stats()
        assert "phase" in stats
        assert stats["phase"] == 3
        assert "agm" in stats
        assert stats["agm"]["beliefs"] == 2


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
