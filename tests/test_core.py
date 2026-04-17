"""Tests for core components: models, verification, AGM, StatePlane."""

import sys
import os
import tempfile
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from bilinc.core.models import MemoryEntry, MemoryType, BeliefState
from bilinc.adaptive.agm_engine import AGMEngine, AGMOperation
from bilinc.core.verification import VerificationGate, VerificationStatus
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend


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
    def test_working_memory_persist_roundtrip(self):
        """Working memory entries should persist across process restarts."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "phase1_working.db")

            plane1 = StatePlane(
                backend=SQLiteBackend(db_path=db_path),
                enable_verification=False,
                enable_audit=True,
            )
            import asyncio
            asyncio.run(plane1.init())
            plane1.commit_sync(
                key="wm_roundtrip",
                value={"pref": "dark"},
                memory_type=MemoryType.WORKING,
            )

            plane2 = StatePlane(
                backend=SQLiteBackend(db_path=db_path),
                enable_verification=False,
                enable_audit=True,
            )
            asyncio.run(plane2.init())
            restored = plane2.working_memory.get("wm_roundtrip")
            assert restored is not None
            assert restored.value == {"pref": "dark"}

    def test_auto_recall_threshold(self):
        """Init should auto-recall only semantic entries above threshold, capped at 5."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "phase1_autorecall.db")
            import asyncio

            seed = StatePlane(
                backend=SQLiteBackend(db_path=db_path),
                enable_verification=False,
                enable_audit=True,
            )
            asyncio.run(seed.init())

            now = time.time()
            # 6 eligible entries: only 5 should load.
            for i in range(6):
                entry = MemoryEntry(
                    key=f"sem_good_{i}",
                    value=f"good_{i}",
                    memory_type=MemoryType.SEMANTIC,
                    importance=0.9 - (i * 0.01),
                    access_count=5 + i,
                    last_accessed=now - i,
                )
                asyncio.run(seed.backend.restore(entry))

            # Non-eligible entries: must not load.
            low_importance = MemoryEntry(
                key="sem_low_importance",
                value="x",
                memory_type=MemoryType.SEMANTIC,
                importance=0.7,
                access_count=10,
                last_accessed=now,
            )
            low_access = MemoryEntry(
                key="sem_low_access",
                value="y",
                memory_type=MemoryType.SEMANTIC,
                importance=0.95,
                access_count=3,
                last_accessed=now,
            )
            asyncio.run(seed.backend.restore(low_importance))
            asyncio.run(seed.backend.restore(low_access))

            fresh = StatePlane(
                backend=SQLiteBackend(db_path=db_path),
                enable_verification=False,
                enable_audit=True,
            )
            asyncio.run(fresh.init())

            wm_entries = fresh.working_memory.get_all()
            wm_keys = {e.key for e in wm_entries}

            assert len(wm_entries) == 5
            assert "sem_low_importance" not in wm_keys
            assert "sem_low_access" not in wm_keys

    def test_semantic_fallback_on_working_eviction(self):
        """When working memory is full, evicted entry should be persisted as semantic."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "phase1_fallback.db")
            import asyncio

            plane = StatePlane(
                backend=SQLiteBackend(db_path=db_path),
                enable_verification=False,
                enable_audit=True,
                max_working_slots=2,
            )
            asyncio.run(plane.init())

            plane.commit_sync("wm_low", "a", memory_type=MemoryType.WORKING, importance=0.1)
            plane.commit_sync("wm_high", "b", memory_type=MemoryType.WORKING, importance=0.9)
            plane.commit_sync("wm_new", "c", memory_type=MemoryType.WORKING, importance=0.8)

            evicted = asyncio.run(plane.backend.load("wm_low"))
            assert evicted is not None
            assert evicted.memory_type == MemoryType.SEMANTIC

    def test_heat_tracking_in_working_memory(self):
        """Working memory access should increase wm_heat metadata."""
        plane = StatePlane(enable_verification=False, enable_audit=False)
        plane.commit_sync("wm_heat", {"v": 1}, memory_type=MemoryType.WORKING, importance=0.8)

        entry = plane.working_memory.get("wm_heat")
        initial_heat = float(entry.metadata.get("wm_heat", 0.0))
        plane.working_memory.get("wm_heat")
        plane.working_memory.get("wm_heat")
        updated = plane.working_memory.get("wm_heat")
        updated_heat = float(updated.metadata.get("wm_heat", 0.0))

        assert updated_heat >= initial_heat
        assert 0.0 <= updated_heat <= 1.0

    def test_heat_based_consolidation_promotes_low_importance_entry(self):
        """Low-importance entries should promote if heat passes threshold."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "phase3_heat_consolidate.db")
            import asyncio

            plane = StatePlane(
                backend=SQLiteBackend(db_path=db_path),
                enable_verification=False,
                enable_audit=True,
                max_working_slots=8,
            )
            asyncio.run(plane.init())
            plane.commit_sync("wm_hot_low", {"k": 1}, memory_type=MemoryType.WORKING, importance=0.2)

            for _ in range(20):
                plane.working_memory.get("wm_hot_low")

            promoted = asyncio.run(plane.consolidate())
            assert promoted >= 1

            stored = asyncio.run(plane.backend.load("wm_hot_low"))
            assert stored is not None
            assert stored.memory_type == MemoryType.EPISODIC
            assert plane.working_memory.get("wm_hot_low") is None

    def test_auto_consolidate_on_hot_and_high_usage(self):
        """Hot entries should auto-consolidate when working memory usage is high."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "phase3_auto_consolidate.db")
            import asyncio

            plane = StatePlane(
                backend=SQLiteBackend(db_path=db_path),
                enable_verification=False,
                enable_audit=True,
                max_working_slots=2,
            )
            asyncio.run(plane.init())
            plane.commit_sync("wm_hot", "a", memory_type=MemoryType.WORKING, importance=0.2)
            for _ in range(20):
                plane.working_memory.get("wm_hot")

            plane.commit_sync("wm_other", "b", memory_type=MemoryType.WORKING, importance=0.1)

            stored = asyncio.run(plane.backend.load("wm_hot"))
            assert stored is not None
            assert stored.memory_type == MemoryType.EPISODIC

    def test_intelligent_recall_multi_signal_fusion(self):
        """Intelligent recall should fuse lexical/hybrid/entity signals."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "phase4_intelligent_recall.db")
            import asyncio

            plane = StatePlane(
                backend=SQLiteBackend(db_path=db_path),
                enable_verification=False,
                enable_audit=True,
            )
            plane.init_agm()
            plane.init_knowledge_graph()
            asyncio.run(plane.init())

            asyncio.run(
                plane.commit_with_agm_async(
                    key="rearc_infra",
                    value="ReARCLabs runs Bilinc on Kubernetes with PostgreSQL.",
                    memory_type="semantic",
                    importance=0.9,
                )
            )
            asyncio.run(
                plane.commit_with_agm_async(
                    key="random_note",
                    value="The weather is sunny today.",
                    memory_type="semantic",
                    importance=0.2,
                )
            )

            results = asyncio.run(plane.recall_intelligent("ReARCLabs Bilinc Kubernetes", limit=5))
            assert len(results) >= 1
            assert results[0]["key"] == "rearc_infra"
            assert results[0]["signals"]["entity"] > 0.0
            assert results[0]["signals"]["hybrid"] >= 0.0
            assert results[0]["score"] > 0.0

    def test_intelligent_recall_fallback_without_kg(self):
        """Intelligent recall should still work without knowledge graph."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "phase4_recall_no_kg.db")
            import asyncio

            plane = StatePlane(
                backend=SQLiteBackend(db_path=db_path),
                enable_verification=False,
                enable_audit=True,
            )
            asyncio.run(plane.init())
            plane.commit_sync("deploy_notes", "Bilinc deployment guide", memory_type=MemoryType.SEMANTIC)

            results = asyncio.run(plane.recall_intelligent("deployment bilinc", limit=3))
            keys = [r["key"] for r in results]
            assert "deploy_notes" in keys

    def test_session_auto_summarization_creates_semantic_memory(self):
        """Episodic entries in same session should produce semantic summary."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "phase5_summary.db")
            import asyncio

            plane = StatePlane(
                backend=SQLiteBackend(db_path=db_path),
                enable_verification=False,
                enable_audit=True,
            )
            asyncio.run(plane.init())

            for i in range(6):
                plane.commit_sync(
                    key=f"ep_{i}",
                    value=f"User discussed deployment step {i} for Bilinc on Kubernetes.",
                    memory_type=MemoryType.EPISODIC,
                    metadata={"session_id": "sess-1"},
                )

            summaries = asyncio.run(plane.summarize_episodic_sessions())
            assert len(summaries) >= 1
            summary = summaries[0]
            assert summary.memory_type == MemoryType.SEMANTIC
            assert summary.metadata.get("is_session_summary") is True
            assert summary.metadata.get("session_id") == "sess-1"
            assert summary.metadata.get("entry_count") >= 6

    def test_session_auto_summarization_respects_threshold(self):
        """Summary should not be created below entry/token thresholds."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "phase5_summary_threshold.db")
            import asyncio

            plane = StatePlane(
                backend=SQLiteBackend(db_path=db_path),
                enable_verification=False,
                enable_audit=True,
            )
            asyncio.run(plane.init())

            for i in range(3):
                plane.commit_sync(
                    key=f"short_ep_{i}",
                    value="tiny note",
                    memory_type=MemoryType.EPISODIC,
                    metadata={"session_id": "sess-2"},
                )

            summaries = asyncio.run(plane.summarize_episodic_sessions())
            assert summaries == []

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
