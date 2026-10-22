"""Local MCP tools on a file shared by several agent processes, and revise side effects."""
from __future__ import annotations

import json
import uuid

import pytest

from bilinc.core.stateplane import StatePlane
from bilinc.mcp_server.server_v2 import _handle_forget, _handle_recall, _handle_revise, _handle_verify
from bilinc.storage.sqlite import SQLiteBackend


async def _agent(path) -> StatePlane:
    plane = StatePlane(backend=SQLiteBackend(str(path)), enable_verification=False, enable_audit=True)
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()
    plane.agm_engine.load_beliefs_from_entries(await plane.backend.list_all())
    return plane


def _json(result):
    return json.loads(result[0].text)


@pytest.mark.asyncio
async def test_recall_and_verify_follow_another_process(tmp_path):
    path = tmp_path / "shared.sqlite"
    writer = await _agent(path)
    await writer.commit_with_agm_async(key="status", value="old", importance=0.9)
    reader = await _agent(path)  # caches "old" as a belief at startup

    await _handle_revise(writer, {"key": "status", "value": "new", "importance": 0.9})
    recalled = _json(await _handle_recall(reader, {"key": "status"}))
    assert [e["value"] for e in recalled["entries"]] == ["new"]
    assert reader.agm_engine.belief_state.get_belief("status").value == "new"

    await _handle_forget(writer, {"key": "status", "reason": "done"})
    assert _json(await _handle_recall(reader, {"key": "status"}))["entries"] == []
    assert _json(await _handle_verify(reader, {"key": "status"}))["exists"] is False
    assert reader.agm_engine.belief_state.get_belief("status") is None


@pytest.mark.asyncio
async def test_revise_tool_reprojects_entities_and_records_an_event(tmp_path):
    plane = await _agent(tmp_path / "revise.sqlite")
    await plane.commit_with_agm_async(key="team", value="Alice works at Acme", importance=0.9)

    await _handle_revise(plane, {"key": "team", "value": "Bob works at Globex", "importance": 0.9})

    conn = plane.backend._conn
    mentions = {row[0] for row in conn.execute("SELECT mention_text FROM entity_mentions WHERE memory_key = 'team'")}
    assert "Alice" not in mentions and "Acme" not in mentions
    assert {"Bob", "Globex"} <= mentions
    assert set(plane.knowledge_graph.memory_entities("team")) >= {"Bob", "Globex"}
    assert "Alice" not in plane.knowledge_graph.memory_entities("team")
    operations = [row[0] for row in conn.execute("SELECT operation FROM memory_events WHERE memory_key = 'team'")]
    assert operations == ["commit", "revise"]


def test_hosted_revise_reprojects_entities_and_records_an_event(tmp_path):
    import asyncio
    from bilinc.cloud.runtime import ProjectRuntimeManager

    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid.uuid4())

    async def scenario():
        await manager.commit(project, key="team", value="Alice works at Acme", importance=0.9)
        await manager.revise(project, key="team", value="Bob works at Globex", importance=0.9, reason="fix")
        plane = await manager.get_plane(project)
        conn = plane.backend._conn
        mentions = {row[0] for row in conn.execute("SELECT mention_text FROM entity_mentions WHERE memory_key = 'team'")}
        assert "Alice" not in mentions and "Globex" in mentions
        operations = [row[0] for row in conn.execute("SELECT operation FROM memory_events WHERE memory_key = 'team'")]
        assert operations[-1] == "revise"
        await manager.close()

    asyncio.new_event_loop().run_until_complete(scenario())
