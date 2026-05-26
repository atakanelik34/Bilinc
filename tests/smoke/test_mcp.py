"""Smoke tests for MCP server v2 tools.

Verifies that create_mcp_server_v2() initializes and
the core tool handlers work correctly.
"""
import asyncio
import json
import pytest
from bilinc.core.stateplane import StatePlane
from bilinc.mcp_server.server_v2 import (
    create_mcp_server_v2,
    _handle_commit_mem,
    _handle_recall,
    _handle_revise,
    _handle_status,
    _handle_query_graph,
)


@pytest.fixture
def plane():
    """StatePlane with AGM + KG initialized for MCP tools."""
    p = StatePlane(enable_verification=False, enable_audit=False)
    p.init_agm()
    p.init_knowledge_graph()
    return p


def _run(result):
    """Run async handlers in sync smoke tests."""
    if asyncio.iscoroutine(result):
        return asyncio.run(result)
    return result


def _text(result):
    """Extract JSON from TextContent response."""
    result = _run(result)
    return json.loads(result[0].text)


class TestMCPServerInit:
    def test_create_server(self):
        """create_mcp_server_v2() should return a server instance."""
        plane = StatePlane(enable_verification=False, enable_audit=False)
        server = create_mcp_server_v2(plane)
        assert server is not None
        assert server.name == "bilinc-v2"

    def test_create_server_default(self):
        """Without a plane, default StatePlane should be created."""
        server = create_mcp_server_v2()
        assert server is not None


class TestMCPCommit:
    def test_commit_new_key(self, plane):
        result = _handle_commit_mem(plane, {
            "key": "test_config",
            "value": json.dumps({"theme": "dark"}),
            "memory_type": "semantic",
            "importance": 0.7,
        })
        data = _text(result)
        assert data["success"] is True
        assert data["key"] == "test_config"
        assert data["operation"] == "revise"

    def test_commit_json_value(self, plane):
        """JSON values should be parsed correctly."""
        result = _handle_commit_mem(plane, {
            "key": "json_key",
            "value": '{"count": 42, "active": true}',
        })
        data = _text(result)
        assert data["success"] is True

    def test_commit_invalid_key(self, plane):
        """Invalid keys should return error, not crash."""
        result = _handle_commit_mem(plane, {
            "key": "../../etc/passwd",
            "value": "malicious",
        })
        data = _text(result)
        assert data["success"] is False
        assert "error" in data


class TestMCPRecall:
    def test_recall_existing(self, plane):
        _run(_handle_commit_mem(plane, {"key": "recall_test", "value": "hello"}))
        result = _handle_recall(plane, {"key": "recall_test"})
        data = _text(result)
        assert data["count"] >= 1
        found = [e for e in data["entries"] if e.get("key") == "recall_test"]
        assert len(found) >= 1

    def test_recall_missing(self, plane):
        result = _handle_recall(plane, {"key": "does_not_exist_12345"})
        data = _text(result)
        assert data["count"] == 0


class TestMCPRevise:
    def test_revise_conflict(self, plane):
        _run(_handle_commit_mem(plane, {"key": "db_host", "value": "localhost", "importance": 0.3}))
        result = _handle_revise(plane, {
            "key": "db_host",
            "value": "prod.internal",
            "importance": 0.9,
            "strategy": "entrenchment",
        })
        data = _text(result)
        assert data["success"] is True
        assert data["conflicts_resolved"] >= 1


class TestMCPStatus:
    def test_status_returns_data(self, plane):
        result = _handle_status(plane)
        data = _text(result)
        assert data["tool"] == "status"
        assert "agm" in data
        assert "knowledge_graph" in data


class TestMCPQueryGraph:
    def test_query_graph_after_commit(self, plane):
        _run(_handle_commit_mem(plane, {
            "key": "entity_test",
            "value": "Company Bilinc builds AI in San Francisco",
            "memory_type": "semantic",
        }))
        result = _handle_query_graph(plane, {"entity": "entity_test", "max_depth": 1})
        data = _text(result)
        assert data["tool"] == "query_graph"
        assert len(data["nodes"]) >= 1
