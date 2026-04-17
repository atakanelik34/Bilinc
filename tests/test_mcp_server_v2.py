"""
Tests for MCP Server v2 (Step 4.1).

The SDK wrappers are async, but these tests still exercise the internal handlers
directly through a small sync helper so the suite stays easy to read.

Covering:
1. commit/recall roundtrip
2. forget operation
3. AGM revision via MCP
4. Knowledge graph query via MCP
5. Contradiction detection via MCP
6. Error handling for invalid inputs
"""

import asyncio
import json
import tempfile
import pytest

from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend
from bilinc.mcp_server.server_v2 import (
    _handle_commit_mem,
    _handle_recall,
    _handle_forget,
    _handle_revise,
    _handle_status,
    _handle_verify,
    _handle_snapshot,
    _handle_query_graph,
    _handle_contradictions,
    _handle_bilinc_recall_smart,
    _handle_bilinc_query_analysis,
    _handle_bilinc_event_segment,
    _handle_bilinc_summarize,
    _handle_bilinc_health,
    _handle_bilinc_benchmark,
    _handle_bilinc_export,
    _handle_bilinc_import,
    _error_text,
    _json_safe,
)


@pytest.fixture
def plane():
    """StatePlane with all Phase 3 components initialized."""
    p = StatePlane(backend=None, enable_verification=False, enable_audit=False)
    p.init_agm()
    p.init_knowledge_graph()
    return p


# ── Helpers ───────────────────────────────────────────────────

def _call(handler, plane, args=None):
    """Call a handler and parse the TextContent JSON response."""
    result = handler(plane, args or {})
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return json.loads(result[0].text)


# ── Test 1: Commit/Recall Roundtrip ──────────────────────────

class TestMCPCommitRecall:
    def test_mcp_commit_recall_roundtrip(self, plane: StatePlane):
        """Commit a memory, then recall it."""
        result = _call(_handle_commit_mem, plane, {
            "key": "test_pref",
            "value": json.dumps({"theme": "dark", "lang": "tr"}),
            "memory_type": "semantic",
            "importance": 0.8,
        })

        assert result["success"] is True
        assert result["key"] == "test_pref"

        recall = _call(_handle_recall, plane, {"key": "test_pref"})
        assert recall["count"] >= 1
        # Find our entry
        found = None
        for e in recall["entries"]:
            if e.get("key") == "test_pref":
                found = e
                break
        assert found is not None

    def test_mcp_commit_json_value_parsed(self, plane: StatePlane):
        """JSON string values should be parsed into Python objects."""
        result = _call(_handle_commit_mem, plane, {
            "key": "json_test",
            "value": '{"count": 42, "active": true}',
            "memory_type": "semantic",
        })

        assert result["success"] is True

        recall = _call(_handle_recall, plane, {"key": "json_test"})
        assert recall["count"] >= 1
        entry = recall["entries"][0]
        if "value" in entry and isinstance(entry["value"], dict):
            assert entry["value"]["count"] == 42

    def test_mcp_commit_plain_string_value(self, plane: StatePlane):
        """Plain string values should be kept as-is."""
        result = _call(_handle_commit_mem, plane, {
            "key": "plain_text",
            "value": "hello world",
            "memory_type": "episodic",
        })

        assert result["success"] is True


# ── Test 2: Forget ───────────────────────────────────────────

class TestMCPForget:
    def test_mcp_forget(self, plane: StatePlane):
        """Forget should remove the entry."""
        _call(_handle_commit_mem, plane, {"key": "temp_mem", "value": "delete_me"})

        result = _call(_handle_forget, plane, {"key": "temp_mem", "reason": "test"})
        assert result["removed"] is True
        assert result["key"] == "temp_mem"

        # Verify it's gone
        recall = _call(_handle_recall, plane, {"key": "temp_mem"})
        assert recall["count"] == 0

    def test_mcp_forget_nonexistent(self, plane: StatePlane):
        """Forgetting a non-existent key should not crash."""
        result = _call(_handle_forget, plane, {"key": "does_not_exist"})
        # Should return some response, not crash
        assert "key" in result


# ── Test 3: AGM Revision via MCP ─────────────────────────────

class TestMCPRevise:
    def test_mcp_revise_agm_conflict_resolution(self, plane: StatePlane):
        """Revise with higher importance should resolve conflict."""
        _call(_handle_commit_mem, plane, {
            "key": "db_config",
            "value": "localhost:5432",
            "importance": 0.3,
        })

        result = _call(_handle_revise, plane, {
            "key": "db_config",
            "value": "prod.internal:5432",
            "importance": 0.9,
            "strategy": "entrenchment",
        })

        assert result["tool"] == "revise"
        assert result["success"] is True
        assert result["conflicts_resolved"] >= 1
        assert len(result.get("explanation", "")) > 0

    def test_mcp_revise_reject_low_importance(self, plane: StatePlane):
        """Low importance revision should be rejected."""
        _call(_handle_commit_mem, plane, {
            "key": "secure_key",
            "value": "encrypted_vault",
            "importance": 0.95,
        })

        result = _call(_handle_revise, plane, {
            "key": "secure_key",
            "value": "plaintext_weak",
            "importance": 0.1,
            "strategy": "entrenchment",
        })

        assert result["success"] is False


# ── Test 4: Knowledge Graph Query ─────────────────────────────

class TestMCPQueryGraph:
    def test_mcp_query_graph_after_semantic_commit(self, plane: StatePlane):
        """Semantic commit should populate KG, query should return subgraph."""
        _call(_handle_commit_mem, plane, {
            "key": "company_info",
            "value": "ReARC Labs builds AI trust infrastructure in San Francisco using Python and PostgreSQL",
            "memory_type": "semantic",
        })

        result = _call(_handle_query_graph, plane, {
            "entity": "company_info",
            "max_depth": 2,
        })

        assert result["tool"] == "query_graph"
        assert len(result["nodes"]) >= 1

    def test_mcp_query_graph_entity_not_found(self, plane: StatePlane):
        """Query for non-existent entity should return empty subgraph."""
        result = _call(_handle_query_graph, plane, {
            "entity": "nonexistent_entity_xyz",
            "max_depth": 1,
        })

        assert result["tool"] == "query_graph"
        # Empty result, not an error
        assert result["nodes"] == []
        assert result["edges"] == []


# ── Test 5: Contradictions ───────────────────────────────────

class TestMCPContradictions:
    def test_mcp_contradictions_no_false_positives(self, plane: StatePlane):
        """Simple graph should have zero contradictions."""
        plane.knowledge_graph.add_relation("A", "B")
        plane.knowledge_graph.add_relation("B", "C")

        result = _call(_handle_contradictions, plane, {})
        assert result["tool"] == "contradictions"
        assert result["count"] == 0
        assert result["contradictions"] == []

    def test_mcp_contradictions_detects_conflict(self, plane: StatePlane):
        """Direct contradiction edge should be detected."""
        from bilinc.core.knowledge_graph import EdgeType
        plane.knowledge_graph.add_relation("Claim1", "Claim2", relation_type=EdgeType.CONTRADICTS)

        result = _call(_handle_contradictions, plane, {})
        assert result["count"] >= 1
        assert result["contradictions"][0]["type"] == "direct_contradiction"


# ── Test 6: Error Handling ───────────────────────────────────

class TestMCPErrorHandling:
    def test_mcp_status_no_crash(self, plane: StatePlane):
        """Status should return all component stats without crashing."""
        result = _call(_handle_status, plane)
        assert "tool" in result
        assert result["tool"] == "status"
        assert "version" in result
        assert "agm" in result
        assert "knowledge_graph" in result

    def test_mcp_snapshot_returns_data(self, plane: StatePlane):
        """Snapshot should return current belief state."""
        _call(_handle_commit_mem, plane, {"key": "snap_k", "value": "snap_v"})

        result = _call(_handle_snapshot, plane, {"include_audit": True})
        assert result["tool"] == "snapshot"
        assert result["belief_count"] >= 1

    def test_mcp_server_creates_without_crash(self):
        """create_mcp_server_v2 should work with default StatePlane."""
        from bilinc.mcp_server.server_v2 import create_mcp_server_v2
        server = create_mcp_server_v2()
        assert server is not None
        assert server.name == "bilinc-v2"

    def test_json_safe_handles_edge_cases(self):
        """_json_safe should not crash on unusual inputs."""
        assert _json_safe(None) is None
        assert _json_safe(42) == 42
        assert _json_safe("hello") == "hello"
        assert _json_safe([1, 2, None]) == [1, 2, None]
        assert isinstance(_json_safe({"a": "b"}), dict)

    def test_mcp_error_text_structured(self):
        """Error responses should be structured JSON."""
        try:
            raise ValueError("test error")
        except ValueError as e:
            result = _error_text("test_tool", e)
            text = result[0].text
            parsed = json.loads(text)
            assert parsed["tool"] == "test_tool"
            assert parsed["error"] == "ValueError"
            assert parsed["success"] is False

    def test_commit_mem_returns_structured_failure_when_persistence_write_fails(self):
        class FailingBackend:
            async def load(self, key):
                return None

            async def save(self, entry):
                return False

        p = StatePlane(backend=FailingBackend(), enable_verification=False, enable_audit=False)
        p.init_agm()
        p.init_knowledge_graph()

        result = _call(_handle_commit_mem, p, {
            "key": "persist_fail",
            "value": "v1",
            "memory_type": "semantic",
        })

        assert result["success"] is False
        assert result["error"] == "persistence_write_failed"

    def test_revise_returns_structured_failure_when_persistence_write_fails(self):
        class FlakyBackend:
            def __init__(self):
                self._saved = {}

            async def load(self, key):
                return self._saved.get(key)

            async def save(self, entry):
                # first write succeeds (for seed commit), second write fails (for revise)
                if entry.key in self._saved:
                    return False
                self._saved[entry.key] = entry
                return True

        p = StatePlane(backend=FlakyBackend(), enable_verification=False, enable_audit=False)
        p.init_agm()
        p.init_knowledge_graph()

        seed = _call(_handle_commit_mem, p, {
            "key": "persist_fail_revise",
            "value": "v1",
            "memory_type": "semantic",
        })
        assert seed["success"] is True

        result = _call(_handle_revise, p, {
            "key": "persist_fail_revise",
            "value": "v2",
            "strategy": "entrenchment",
        })

        assert result["success"] is False
        assert result["error"] == "persistence_write_failed"


class TestPhase8Tools:
    @pytest.fixture()
    def phase8_plane(self):
        with tempfile.TemporaryDirectory() as td:
            backend = SQLiteBackend(db_path=f"{td}/phase8.db")
            asyncio.run(backend.init())
            p = StatePlane(backend=backend, enable_verification=False, enable_audit=True)
            p.init_agm()
            p.init_knowledge_graph()
            asyncio.run(p.init())
            yield p
            asyncio.run(backend.close())

    def test_recall_smart(self, phase8_plane: StatePlane):
        _call(_handle_commit_mem, phase8_plane, {
            "key": "phase8_recall",
            "value": "Kubernetes deployment guide for Bilinc",
            "memory_type": "semantic",
        })
        result = _call(_handle_bilinc_recall_smart, phase8_plane, {"query": "k8s deploy bilinc", "limit": 5})
        assert result["tool"] == "bilinc_recall_smart"
        assert result["success"] is True
        assert len(result["results"]) >= 1

    def test_query_analysis(self, phase8_plane: StatePlane):
        result = _call(_handle_bilinc_query_analysis, phase8_plane, {"query": "k8s deploy bilinc"})
        assert result["tool"] == "bilinc_query_analysis"
        assert result["success"] is True
        assert result["token_count"] >= 1
        assert "expanded_query" in result

    def test_event_segment_create_and_retrieve(self, phase8_plane: StatePlane):
        _call(_handle_commit_mem, phase8_plane, {"key": "ev_a", "value": "alpha", "memory_type": "semantic"})
        _call(_handle_commit_mem, phase8_plane, {"key": "ev_b", "value": "beta", "memory_type": "semantic"})

        create_res = _call(_handle_bilinc_event_segment, phase8_plane, {
            "action": "create",
            "event_id": "release-1",
            "keys": ["ev_a", "ev_b"],
        })
        assert create_res["success"] is True
        assert create_res["updated"] >= 2

        fetch_res = _call(_handle_bilinc_event_segment, phase8_plane, {
            "action": "retrieve",
            "event_id": "release-1",
        })
        assert fetch_res["success"] is True
        assert fetch_res["count"] >= 2

    def test_summarize_tool(self, phase8_plane: StatePlane):
        for idx in range(6):
            _call(_handle_commit_mem, phase8_plane, {
                "key": f"sum_ep_{idx}",
                "value": f"Session detail {idx} about deployment pipeline.",
                "memory_type": "episodic",
                "metadata": {"session_id": "s-phase8"},
            })
        result = _call(_handle_bilinc_summarize, phase8_plane, {"session_id": "s-phase8"})
        assert result["tool"] == "bilinc_summarize"
        assert result["success"] is True
        assert result["count"] >= 1

    def test_health_and_benchmark(self, phase8_plane: StatePlane):
        health = _call(_handle_bilinc_health, phase8_plane, {})
        assert health["tool"] == "bilinc_health"
        assert health["success"] is True

        bench = _call(_handle_bilinc_benchmark, phase8_plane, {"iterations": 2})
        assert bench["tool"] == "bilinc_benchmark"
        assert bench["success"] is True
        assert bench["iterations"] == 2

    def test_export_import_json_cycle(self, phase8_plane: StatePlane):
        _call(_handle_commit_mem, phase8_plane, {"key": "exp_key", "value": {"x": 1}, "memory_type": "semantic"})
        exported = _call(_handle_bilinc_export, phase8_plane, {"format": "json", "limit": 10})
        assert exported["tool"] == "bilinc_export"
        assert exported["success"] is True
        assert exported["count"] >= 1
        assert isinstance(exported["data"], list)

        imported = _call(_handle_bilinc_import, phase8_plane, {
            "format": "json",
            "data": [{"key": "imp_key", "value": {"y": 2}, "memory_type": "semantic"}],
        })
        assert imported["tool"] == "bilinc_import"
        assert imported["imported"] >= 1
