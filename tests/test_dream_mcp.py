"""Stdio MCP tools for the dream pass, and their place in the public truth contract."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DREAM_TOOLS = ["dream_start", "dream_apply", "dream_undo"]


def _tools():
    from bilinc.cloud_mcp import build_server

    return {tool.name: tool for tool in asyncio.run(build_server().list_tools())}


def _call(name, arguments):
    from bilinc.cloud_mcp import build_server

    return asyncio.run(build_server().call_tool(name, arguments))


def _validator():
    spec = importlib.util.spec_from_file_location("validate_public_truth", ROOT / "scripts" / "validate_public_truth.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    calls: list = []

    def dream_start(self, **kwargs):
        FakeClient.calls.append(("start", kwargs))
        return {"dream_id": "drm_1", "candidates": []}

    def dream_apply(self, dream_id, actions, *, report=None):
        FakeClient.calls.append(("apply", dream_id, actions, report))
        return {"dream_id": dream_id, "status": "finished", "results": []}

    def dream_undo(self, dream_id):
        FakeClient.calls.append(("undo", dream_id))
        return {"dream_id": dream_id, "status": "undone", "restored": [], "conflicts": [], "kept": []}


@pytest.fixture()
def fake_client(monkeypatch):
    from bilinc import cloud_mcp

    FakeClient.calls = []
    monkeypatch.setattr(cloud_mcp, "create_client", lambda *args, **kwargs: FakeClient())
    return FakeClient


def test_dream_tools_registered_and_in_cloud_list():
    from bilinc.cloud_mcp import CLOUD_MCP_TOOLS, LOCAL_MCP_TOOLS

    tools = _tools()
    for name in DREAM_TOOLS:
        assert name in tools
        assert name in CLOUD_MCP_TOOLS
        assert name not in LOCAL_MCP_TOOLS
    assert set(tools) == set(CLOUD_MCP_TOOLS) | set(LOCAL_MCP_TOOLS)
    # Registered right after confirm, before the local export_wiki tool.
    assert list(CLOUD_MCP_TOOLS[-4:]) == ["confirm", *DREAM_TOOLS]
    assert tools["dream_apply"].inputSchema["required"] == ["dream_id", "actions"]
    assert tools["dream_undo"].inputSchema["required"] == ["dream_id"]
    assert "required" not in tools["dream_start"].inputSchema or not tools["dream_start"].inputSchema["required"]
    assert "data" in tools["dream_start"].description


def test_dream_tool_annotations():
    tools = _tools()

    start = tools["dream_start"].annotations
    assert start.readOnlyHint is False and start.destructiveHint is False
    for name in ("dream_apply", "dream_undo"):
        hints = tools[name].annotations
        assert hints.readOnlyHint is False and hints.destructiveHint is True, name
    for name in DREAM_TOOLS:
        hints = tools[name].annotations
        assert hints.idempotentHint is False and hints.openWorldHint is False, name


def test_dream_start_tool_passes_filters(fake_client):
    _call("dream_start", {"prefix": "team.", "limit": 20})
    assert fake_client.calls == [("start", {"prefix": "team.", "since": None, "limit": 20})]


def test_dream_apply_tool_passes_report(fake_client):
    actions = [
        {
            "op": "confirm",
            "key": "team.deploy_day",
            "expected_version": "v1",
            "reason": "still accurate",
            "evidence_keys": ["team.deploy_day"],
        }
    ]
    report = {"summary": "nothing to merge"}

    _call("dream_apply", {"dream_id": "drm_1", "actions": actions, "report": report})
    _call("dream_undo", {"dream_id": "drm_1"})

    assert fake_client.calls == [("apply", "drm_1", actions, report), ("undo", "drm_1")]


def test_product_truth_has_no_hosted_connector_pending_tools():
    payload = json.loads((ROOT / "docs" / "public" / "product-truth.json").read_text())
    cloud_mcp = payload["cloud_mcp"]

    assert cloud_mcp["tools"][-4:] == ["confirm", *DREAM_TOOLS]
    # the hosted connector offers the dream tools since 2026-11-10
    assert cloud_mcp["hosted_connector_pending"] == []
    assert _validator().validate_product_truth() == []


def test_validator_rejects_pending_tool_missing_from_tools(tmp_path):
    payload = json.loads((ROOT / "docs" / "public" / "product-truth.json").read_text())
    payload["cloud_mcp"]["hosted_connector_pending"] = [*DREAM_TOOLS, "dream_show"]
    manifest = tmp_path / "product-truth.json"
    manifest.write_text(json.dumps(payload))

    errors = _validator().validate_product_truth(manifest)

    assert "hosted_connector_pending must be a subset of tools" in errors
