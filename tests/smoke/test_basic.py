"""Smoke tests for Bilinc alpha release.

These tests verify the most basic user flows:
- Import works without heavy deps at module load
- StatePlane can be created with default settings
- commit_sync writes to working memory
- recall retrieves from working memory
- Knowledge graph can be initialized
"""
import pytest
from bilinc.core.stateplane import StatePlane
from bilinc.core.models import MemoryType


class TestBasicFlow:
    def test_import_works(self):
        """import bilinc should succeed."""
        import bilinc
        assert hasattr(bilinc, '__version__')
        assert bilinc.__version__.startswith('1.')

    def test_create_stateplane_safe(self):
        """Default StatePlane() should not crash."""
        plane = StatePlane()
        assert plane.working_memory is not None
        assert plane.metrics is not None
        assert plane.health is not None

    def test_commit_and_recall_in_memory(self):
        """Commit to working memory and recall immediately."""
        plane = StatePlane(enable_verification=False, enable_audit=False)
        
        entry = plane.commit_sync(
            key="user_pref",
            value={"theme": "dark"},
            memory_type=MemoryType.WORKING,
        )
        assert entry.key == "user_pref"
        assert entry.value == {"theme": "dark"}

        # Immediately recall from working memory
        found = plane.working_memory.get("user_pref")
        assert found is not None
        assert found.value["theme"] == "dark"

    def test_knowledge_graph_init(self):
        """Knowledge graph should be init-able without crashing."""
        plane = StatePlane(enable_verification=False, enable_audit=False)
        plane.init_knowledge_graph()
        assert plane.knowledge_graph is not None
        assert plane.knowledge_graph.stats["nodes"] == 0

    def test_agm_init_and_revise(self):
        """AGM engine should work with basic revise flow."""
        plane = StatePlane(enable_verification=False, enable_audit=False)
        plane.init_agm()
    
        result1 = plane.commit_with_agm("pref", {"val": 1}, importance=0.5)
        assert result1.success is True
    
        result2 = plane.commit_with_agm("pref", {"val": 2}, importance=0.8)
        assert result2.success is True

    def test_forget_removes(self):
        """Forget should remove the entry from working memory."""
        plane = StatePlane(enable_verification=False, enable_audit=False)
        plane.commit_sync(key="temp", value="x", memory_type=MemoryType.WORKING)
        assert plane.working_memory.count >= 1
    
        result = plane.working_memory.remove("temp")
        assert result is not None
        assert plane.working_memory.get("temp") is None
