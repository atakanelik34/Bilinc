import asyncio
import json

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

from bilinc.core import MemoryType, StatePlane
from bilinc.mcp_server.server_v2 import (
    _handle_bilinc_workspace_preview,
    _handle_bilinc_workspace_replay_session,
    _handle_bilinc_workspace_status,
    create_mcp_server_v2,
)
from bilinc.storage.memory import MemoryBackend


def _payload(result):
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return json.loads(result[0].text)


async def _persistent_plane():
    backend = MemoryBackend()
    await backend.init()
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    plane.init_agm()
    plane.init_knowledge_graph()
    await plane.init()
    return plane


@pytest.mark.asyncio
async def test_workspace_preview_is_admin_debug_only_and_read_only():
    plane = await _persistent_plane()
    await plane.commit(
        "mcp:preview:fact",
        "Workspace preview should expose the assembled context for debugging only.",
        memory_type=MemoryType.SEMANTIC,
        importance=0.9,
    )

    before = len(await plane.backend.list_all())
    payload = _payload(await _handle_bilinc_workspace_preview(plane, {
        "session_id": "mcp-preview-session",
        "user_input": "What should workspace preview expose?",
        "budget_tokens": 700,
        "limit": 5,
    }))
    after = len(await plane.backend.list_all())

    assert payload["tool"] == "bilinc_workspace_preview"
    assert payload["success"] is True
    assert payload["admin_debug_only"] is True
    assert payload["primary_runtime_path"] == "sdk_runtime"
    assert payload["session_id"] == "mcp-preview-session"
    assert "mcp:preview:fact" in payload["selected_memory_keys"]
    assert "Bilinc Context Packet" in payload["context"]["prompt_block"]
    assert "mcp_bilinc" not in payload["context"]["prompt_block"]
    assert "recall_smart" not in payload["context"]["prompt_block"]
    assert after == before


@pytest.mark.asyncio
async def test_workspace_status_reports_availability_without_requiring_runtime_state():
    plane = await _persistent_plane()
    await plane.commit("mcp:status:semantic", "semantic fact", MemoryType.SEMANTIC)
    await plane.commit("mcp:status:working", "working note", MemoryType.WORKING)

    payload = _payload(await _handle_bilinc_workspace_status(plane, {}))

    assert payload["tool"] == "bilinc_workspace_status"
    assert payload["success"] is True
    assert payload["admin_debug_only"] is True
    assert payload["runtime"]["workspace_available"] is True
    assert payload["runtime"]["agent_runtime_available"] is True
    assert payload["storage"]["backend"] == "MemoryBackend"
    assert payload["storage"]["memory_type_counts"]["semantic"] >= 1
    assert payload["storage"]["memory_type_counts"]["working"] >= 1


@pytest.mark.asyncio
async def test_workspace_replay_session_is_read_only_and_redacts_secret_like_values():
    plane = await _persistent_plane()
    await plane.commit(
        "mcp:replay:user",
        {"session_id": "mcp-replay", "role": "user", "content": "Remember the safe bit", "token": "secret-token"},
        MemoryType.WORKING,
        metadata={"session_id": "mcp-replay", "created_by": "bilinc.cognitive_workspace"},
    )
    await plane.commit(
        "mcp:replay:other",
        {"session_id": "other", "role": "user", "content": "do not include"},
        MemoryType.WORKING,
        metadata={"session_id": "other", "created_by": "bilinc.cognitive_workspace"},
    )
    before = len(await plane.backend.list_all())

    payload = _payload(await _handle_bilinc_workspace_replay_session(plane, {"session_id": "mcp-replay", "limit": 10}))
    after = len(await plane.backend.list_all())

    dumped = json.dumps(payload, sort_keys=True)
    assert payload["tool"] == "bilinc_workspace_replay_session"
    assert payload["success"] is True
    assert payload["admin_debug_only"] is True
    assert payload["session_id"] == "mcp-replay"
    assert payload["event_count"] == 1
    assert payload["events"][0]["key"] == "mcp:replay:user"
    assert "do not include" not in dumped
    assert "secret-token" not in dumped
    assert "[REDACTED]" in dumped
    assert after == before


@pytest.mark.asyncio
async def test_workspace_admin_tools_are_registered_and_dispatched():
    plane = await _persistent_plane()
    server = create_mcp_server_v2(plane)
    list_handler = server.request_handlers[ListToolsRequest]
    tools_response = await list_handler(ListToolsRequest())
    tool_names = {tool.name for tool in tools_response.root.tools}

    assert "bilinc_workspace_preview" in tool_names
    assert "bilinc_workspace_status" in tool_names
    assert "bilinc_workspace_replay_session" in tool_names

    call_handler = server.request_handlers[CallToolRequest]
    response = await call_handler(CallToolRequest(params=CallToolRequestParams(name="bilinc_workspace_status", arguments={})))
    dispatched = json.loads(response.root.content[0].text)
    assert dispatched["tool"] == "bilinc_workspace_status"
    assert dispatched["success"] is True
