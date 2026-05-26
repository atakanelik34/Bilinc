"""
Tests for StatePlane Phase 3 Integration (Step 3.4).

Covering:
1. StatePlane + AGM integration — Commit → AGM revision auto-applied
2. StatePlane + KG integration — Semantic commit → KG populated
3. StatePlane + Belief Sync — Full sync cycle
4. End-to-end Phase 3 flow
"""

import pytest
from bilinc.core.stateplane import StatePlane
from bilinc.core.models import MemoryType
from bilinc.adaptive.agm_engine import AGMEngine, ConflictStrategy
from bilinc.core.knowledge_graph import KnowledgeGraph, EdgeType
from bilinc.core.belief_sync import BeliefSyncEngine


@pytest.fixture
def plane():
    """StatePlane with no backend (in-memory only, no async needed)."""
    return StatePlane(backend=None, enable_verification=False, enable_audit=False)


@pytest.fixture
def plane_phase3(plane: StatePlane):
    """StatePlane fully equipped with Phase 3 components."""
    plane.init_agm()
    plane.init_knowledge_graph()
    plane.init_belief_sync()
    return plane


# ── Test 1: AGM Integration ──────────────────────────────────

class TestStatePlaneAGMIntegration:
    def test_stateplane_agm_commit_and_revise(self, plane_phase3: StatePlane):
        """Commit a belief, then commit a conflicting one → AGM should resolve."""
        # First commit
        result1 = plane_phase3.commit_with_agm("db_host", "localhost", importance=0.3)
        assert result1.success is True

        # Conflicting commit
        result2 = plane_phase3.commit_with_agm("db_host", "prod.internal", importance=0.8)
        assert result2.success is True  # New is more important, should replace

        # AGM should have resolved the conflict
        stored = plane_phase3.agm_engine.belief_state.get_belief("db_host")
        assert stored is not None
        assert stored.value == "prod.internal"

    def test_stateplane_agm_reject_low_importance(self, plane_phase3: StatePlane):
        """Low importance revision should be rejected when existing is strong."""
        plane_phase3.commit_with_agm("api_key", "secure_key_v1", importance=0.9)
        result = plane_phase3.commit_with_agm("api_key", "insecure_key", importance=0.1)

        assert result.success is False  # Should be rejected

    def test_stateplane_agm_fallback_no_engine(self, plane: StatePlane):
        """Without AGM engine, commit_with_agm should return entry directly."""
        result = plane.commit_with_agm("k", "v")
        # Returns MemoryEntry directly, not AGMResult
        assert result.key == "k"
        assert result.value == "v"


# ── Test 2: KG Integration ───────────────────────────────────

class TestStatePlaneKGIntegration:
    def test_stateplane_kg_semantic_commit(self, plane_phase3: StatePlane):
        """Semantic commit should auto-populate the knowledge graph."""
        plane_phase3.commit_with_agm(
            "server_info",
            "host=prod.db port=5432 Database=PostgreSQL Engine=Python",
            memory_type="semantic",
        )

        # KG should have extracted entities
        kg_stats = plane_phase3.knowledge_graph.stats
        assert kg_stats["nodes"] >= 1

        # Main key should exist as a FACT
        node = plane_phase3.query_graph("server_info")
        assert len(node["nodes"]) >= 1

    def test_stateplane_query_graph(self, plane_phase3: StatePlane):
        """Query should traverse the knowledge graph."""
        plane_phase3.commit_with_agm(
            "company",
            "ReARC Labs builds AI trust infrastructure in San Francisco",
            memory_type="semantic",
        )

        result = plane_phase3.query_graph("company", max_depth=2)
        assert len(result["nodes"]) >= 1

    def test_stateplane_query_graph_no_kg(self, plane: StatePlane):
        """Query without KG should return error dict."""
        result = plane.query_graph("anything")
        assert "error" in result

    def test_stateplane_get_contradictions(self, plane_phase3: StatePlane):
        """Contradiction detection through StatePlane."""
        kg = plane_phase3.knowledge_graph
        kg.add_relation("A", "B", relation_type=EdgeType.RELATED_TO)
        # No contradictions in simple graph
        contradictions = plane_phase3.get_contradictions()
        assert isinstance(contradictions, list)


# ── Test 3: Belief Sync Integration ──────────────────────────

class TestStatePlaneBeliefSync:
    def test_stateplane_sync_init(self, plane_phase3: StatePlane):
        """Belief sync should be initialized on the StatePlane."""
        sync = plane_phase3.belief_sync
        assert isinstance(sync, BeliefSyncEngine)

        # Register agents and sync
        sync.init_sync("agent_1", reliability=0.9)
        sync.init_sync("agent_2", reliability=0.7)

        from bilinc.core.models import MemoryEntry
        sync.push_beliefs("agent_1", [
            MemoryEntry(key="pref_theme", value="dark", memory_type=MemoryType.SEMANTIC),
        ])

        result = sync.pull_updates("agent_2")
        assert result.beliefs_pulled >= 1

    def test_stateplane_phase3_stats(self, plane_phase3: StatePlane):
        """Phase 3 stats should report all components."""
        # Add some data
        plane_phase3.commit_with_agm("key1", "val1", importance=0.5)
        plane_phase3.knowledge_graph.add_entity("TestEntity")
        plane_phase3.belief_sync.init_sync("test_agent")

        stats = plane_phase3.phase3_stats()
        assert "agm" in stats
        assert "knowledge_graph" in stats
        assert "belief_sync" in stats
        assert stats["agm"]["beliefs"] >= 1
        assert stats["knowledge_graph"]["nodes"] >= 1
        assert "agents" in stats["belief_sync"]


# ── Test 4: End-to-End Phase 3 Flow ──────────────────────────

class TestPhase3CompleteFlow:
    def test_phase3_e2e(self):
        """
        Full end-to-end test:
        1. Create StatePlane with all Phase 3 components
        2. Commit beliefs via AGM
        3. Verify KG populates
        4. Sync across two agents
        5. Check contradictions
        """
        # 1. Setup
        plane = StatePlane(backend=None, enable_verification=False, enable_audit=False)
        agm = AGMEngine(default_strategy=ConflictStrategy.ENTRENCHMENT)
        plane.init_agm(agm)
        plane.init_knowledge_graph()
        sync = plane.init_belief_sync()

        # 2. Commit beliefs
        r1 = plane.commit_with_agm("db_url", "localhost:5432", importance=0.5)
        assert r1.success is True

        r2 = plane.commit_with_agm("db_url", "prod.internal:5432", importance=0.9)
        assert r2.success is True  # Upgrade should succeed

        # 3. Verify KG
        kg_stats = plane.knowledge_graph.stats
        assert kg_stats["nodes"] >= 1

        # 4. Sync with another agent
        sync.init_sync("agent_alpha", reliability=0.8)
        sync.init_sync("agent_beta", reliability=0.6)

        from bilinc.core.models import MemoryEntry
        sync.push_beliefs("agent_alpha", [
            MemoryEntry(key="config_mode", value="production", memory_type=MemoryType.SEMANTIC),
        ])
        pull_result = sync.pull_updates("agent_beta")
        assert pull_result.beliefs_pulled >= 1

        # 5. Check contradictions
        contradictions = plane.get_contradictions()
        assert isinstance(contradictions, list)

        # 6. Stats should reflect all activity
        stats = plane.phase3_stats()
        assert stats["agm"]["operations"] >= 2
        assert stats["agm"]["beliefs"] >= 1
        assert stats["knowledge_graph"]["nodes"] >= 1
        assert stats["belief_sync"]["agents"] >= 2
