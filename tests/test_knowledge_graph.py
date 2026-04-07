"""
Tests for the Knowledge Graph Layer (Step 3.2).

Covering:
1. Basic operations — add/query/traverse
2. Contradiction detection
3. Semantic memory integration
4. Export/import roundtrip
"""

import pytest
import json
import time
from bilinc.core.models import MemoryType, MemoryEntry
from bilinc.core.knowledge_graph import (
    KnowledgeGraph,
    KGNode,
    KGEdge,
    NodeType,
    EdgeType,
)


@pytest.fixture
def kg():
    return KnowledgeGraph()


# ── Test 1: Basic Operations ──────────────────────────────────

class TestKGBasicOps:
    def test_kg_add_entity(self, kg: KnowledgeGraph):
        """Add a node and query it back."""
        node = kg.add_entity("Python", NodeType.ENTITY, {"version": "3.10"})
        assert node.name == "Python"
        assert node.node_type == NodeType.ENTITY
        assert node.properties["version"] == "3.10"

        result = kg.query_entity("Python")
        assert result is not None
        assert result.name == "Python"

    def test_kg_add_query_entity(self, kg: KnowledgeGraph):
        """Query a non-existent entity should return None."""
        assert kg.query_entity("nonexistent") is None

    def test_kg_add_relation(self, kg: KnowledgeGraph):
        """Add a relation between two entities."""
        kg.add_entity("Python", NodeType.ENTITY)
        kg.add_entity("Django", NodeType.ENTITY)

        edge = kg.add_relation("Django", "Python", EdgeType.RELATED_TO, weight=0.9)
        assert edge.source == "Django"
        assert edge.target == "Python"
        assert edge.relation_type == EdgeType.RELATED_TO
        assert edge.weight == 0.9

    def test_kg_add_relation_auto_create_nodes(self, kg: KnowledgeGraph):
        """add_relation should auto-create nodes if missing."""
        edge = kg.add_relation("A", "B", EdgeType.CAUSES)
        assert kg.query_entity("A") is not None
        assert kg.query_entity("B") is not None

    def test_kg_remove_entity(self, kg: KnowledgeGraph):
        """Remove a node and its edges."""
        kg.add_entity("X")
        kg.add_entity("Y")
        kg.add_relation("X", "Y", EdgeType.RELATED_TO)

        removed = kg.remove_entity("X")
        assert removed is True
        assert kg.query_entity("X") is None
        # Edge should also be removed
        rels = kg.get_relations("X")
        assert len(rels) == 0

    def test_kg_remove_nonexistent_entity(self, kg: KnowledgeGraph):
        assert kg.remove_entity("nonexistent") is False

    def test_kg_traverse(self, kg: KnowledgeGraph):
        """Traverse from a starting node up to depth N."""
        kg.add_entity("Root")
        kg.add_entity("Child1")
        kg.add_entity("Child2")
        kg.add_entity("Grandchild")

        kg.add_relation("Root", "Child1", EdgeType.RELATED_TO)
        kg.add_relation("Root", "Child2", EdgeType.RELATED_TO)
        kg.add_relation("Child1", "Grandchild", EdgeType.CAUSES)

        subgraph = kg.traverse("Root", max_depth=2)

        assert subgraph["start"] == "Root"
        assert subgraph["depth"] == 2
        node_names = [n["name"] for n in subgraph["nodes"]]
        assert "Root" in node_names
        assert "Child1" in node_names
        assert "Grandchild" in node_names
        assert len(subgraph["edges"]) >= 2

    def test_kg_traverse_nonexistent(self, kg: KnowledgeGraph):
        result = kg.traverse("nonexistent_key")
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_kg_relation_filter(self, kg: KnowledgeGraph):
        """Filter traversal by relation type."""
        kg.add_entity("A")
        kg.add_entity("B")
        kg.add_entity("C")
        kg.add_relation("A", "B", EdgeType.CAUSES)
        kg.add_relation("A", "C", EdgeType.CONTRADICTS)

        # Only get CAUSES relations
        causes_only = kg.traverse("A", max_depth=1, relation_filter=[EdgeType.CAUSES])
        edge_types = [e.get("relation_type") for e in causes_only["edges"]]
        assert "causes" in edge_types
        assert "contradicts" not in edge_types

    def test_kg_get_relations(self, kg: KnowledgeGraph):
        """Get all outgoing relations for a node."""
        kg.add_relation("X", "Y", EdgeType.RELATED_TO)
        kg.add_relation("X", "Z", EdgeType.CAUSES)

        rels = kg.get_relations("X")
        assert len(rels) >= 2

    def test_kg_stats(self, kg: KnowledgeGraph):
        """Check basic stats."""
        kg.add_entity("A")
        kg.add_entity("B")
        kg.add_relation("A", "B")

        s = kg.stats
        assert s["nodes"] >= 2
        assert s["edges"] >= 1


# ── Test 2: Contradiction Detection ───────────────────────────

class TestKGContradictions:
    def test_kg_detect_direct_contradiction(self, kg: KnowledgeGraph):
        """A → B with contradicts edge should be detected."""
        kg.add_entity("A")
        kg.add_entity("B")
        kg.add_relation("A", "B", EdgeType.CONTRADICTS)

        contradictions = kg.find_contradictions()
        assert len(contradictions) >= 1
        assert contradictions[0]["type"] == "direct_contradiction"

    def test_kg_detect_support_vs_contradiction(self, kg: KnowledgeGraph):
        """Same pair with both supports and contradicts → conflict."""
        kg.add_entity("Claim1")
        kg.add_entity("Claim2")
        kg.add_relation("Claim1", "Claim2", EdgeType.SUPPORTS)
        kg.add_relation("Claim1", "Claim2", EdgeType.CONTRADICTS)

        contradictions = kg.find_contradictions()
        assert len(contradictions) >= 1
        assert contradictions[0]["type"] == "relation_conflict"

    def test_kg_no_contradictions(self, kg: KnowledgeGraph):
        """Graph with only friendly relations should have no contradictions."""
        kg.add_relation("A", "B", EdgeType.RELATED_TO)
        kg.add_relation("A", "C", EdgeType.SUPPORTS)
        kg.add_relation("B", "C", EdgeType.CAUSES)

        contradictions = kg.find_contradictions()
        assert len(contradictions) == 0


# ── Test 3: Semantic Memory Integration ───────────────────────

class TestKGSemanticIntegration:
    def test_kg_ingest_semantic_entry(self, kg: KnowledgeGraph):
        """Auto-extract entities and relations from a semantic MemoryEntry."""
        entry = MemoryEntry(
            key="server_config",
            value="host=prod.db.internal port=5432 Database=PostgreSQL",
            memory_type=MemoryType.SEMANTIC,
            importance=0.8,
            is_verified=True,
        )

        result = kg.ingest_memory_entry(entry)

        assert result["entities_created"] >= 1
        assert result["relations_created"] >= 1

        # Main key should be a FACT entity
        node = kg.query_entity("server_config")
        assert node is not None
        assert node.node_type == NodeType.FACT

    def test_kg_ingest_capitalized_words(self, kg: KnowledgeGraph):
        """Capitalized words in value should become entities."""
        entry = MemoryEntry(
            key="company_info",
            value="Python and Django are built at Google and Microsoft by Engineers.",
            memory_type=MemoryType.SEMANTIC,
        )

        kg.ingest_memory_entry(entry)

        # Check that some capitalized words became entities
        # Python, Django, Google, Microsoft, Engineers should be candidates
        # Common words like "The", "And" should be filtered
        entities = list(kg._nodes.keys())
        company_names = [e for e in entities if e.lower() in ("google", "microsoft", "django", "python")]
        assert len(company_names) >= 1  # At least some should be captured

    def test_kg_ingest_non_semantic_ignored(self, kg: KnowledgeGraph):
        """Non-SEMANTIC entries should not create much in the graph."""
        entry = MemoryEntry(
            key="session_log",
            value="random procedural memory",
            memory_type=MemoryType.PROCEDURAL,
        )

        result = kg.ingest_memory_entry(entry)
        # Non-semantic types produce nothing
        assert result["entities_created"] == 0
        assert result["relations_created"] == 0


# ── Test 4: Serialization ─────────────────────────────────────

class TestKGSerialization:
    def test_kg_export_basic(self, kg: KnowledgeGraph):
        """Export should return a serializable dict."""
        kg.add_entity("A", NodeType.ENTITY, {"foo": "bar"})
        kg.add_entity("B")
        kg.add_relation("A", "B", EdgeType.CAUSES, weight=0.8)

        exported = kg.export_to_json()

        assert "nodes" in exported
        assert "edges" in exported
        assert "stats" in exported
        assert exported["stats"]["node_count"] >= 2
        assert exported["stats"]["edge_count"] >= 1

        # Must be JSON serializable
        json_str = json.dumps(exported)
        assert len(json_str) > 0

    def test_kg_import_roundtrip(self, kg: KnowledgeGraph):
        """Export → Import should recreate the graph."""
        kg.add_entity("X", NodeType.FACT, {"data": 123})
        kg.add_entity("Y", NodeType.ENTITY)
        kg.add_relation("X", "Y", EdgeType.SUPPORTS, weight=0.7, metadata={"source": "test"})

        exported = kg.export_to_json()

        # Create a fresh graph and import
        kg2 = KnowledgeGraph()
        kg2.import_from_json(exported)

        # Check nodes
        assert kg2.query_entity("X") is not None
        assert kg2.query_entity("Y") is not None
        assert kg2.query_entity("X").node_type == NodeType.FACT
        assert kg2.query_entity("X").properties["data"] == 123

        # Check edges
        rels = kg2.get_relations("X")
        assert len(rels) >= 1

    def test_kg_import_empty(self, kg: KnowledgeGraph):
        """Import empty data should not crash."""
        kg2 = KnowledgeGraph()
        kg2.import_from_json({"nodes": [], "edges": []})
        assert kg2.stats["nodes"] == 0
        assert kg2.stats["edges"] == 0
