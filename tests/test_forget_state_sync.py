"""Forget, purge and rollback keep the in-process belief set, graph and ledger in line with storage.

Hosted runtime on SQLite; the Postgres variant runs only when BILINC_TEST_POSTGRES_DSN is set.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import uuid

import pytest

from bilinc.core.stateplane import StatePlane
from bilinc.mcp_server.server_v2 import _handle_forget
from bilinc.storage.sqlite import SQLiteBackend

DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
needs_postgres = pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set")
SECRET = "Quartz harbor plan: call Dana on her private line"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _manager(tmp_path):
    from bilinc.cloud.runtime import ProjectRuntimeManager

    return ProjectRuntimeManager(tmp_path)


def _sqlite_text(path) -> str:
    conn = sqlite3.connect(path)
    texts = []
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
        for row in conn.execute(f'SELECT * FROM "{name}"'):
            texts.append(" ".join(value.decode("latin-1") if isinstance(value, bytes) else str(value) for value in row))
    conn.close()
    return "\n".join(texts)


def _project_text(manager, project) -> str:
    texts = [_sqlite_text(manager.db_path(project))]
    for path in manager.project_dir(project).rglob("*.json"):
        texts.append(path.read_text(encoding="utf-8"))
    return "\n".join(texts)


def test_recommit_after_purge_does_not_bring_the_purged_value_back(tmp_path):
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())

    async def scenario():
        await manager.commit(project, key="plan", value=SECRET, importance=1.0)
        await manager.commit(project, key="plan", value=SECRET + " (revised)", importance=1.0)
        result = await manager.forget(project, key="plan", reason="erasure request", purge=True)
        assert result["purged"]["events"] >= 1

        recommit = await manager.commit(project, key="plan", value="a fresh plan", importance=1.0)
        assert recommit["success"] is True
        plane = await manager.get_plane(project)
        stored = await plane.backend.load("plan")
        assert "previous_value" not in stored.metadata
        assert "previous_value_sha256" not in stored.metadata  # a new belief, not a revision of the purged one
        await manager.create_snapshot(project, label="after")
        await manager.close()
        text = _project_text(manager, project)
        assert "Quartz" not in text and "harbor" not in text.lower()
        for suffix in ("", "-wal"):  # the raw file and its write-ahead log, not just query results
            path = manager.db_path(project).with_name(manager.db_path(project).name + suffix)
            if path.exists():
                assert b"Quartz" not in path.read_bytes()

    _run(scenario())


def test_recommit_with_lower_importance_after_forget_is_accepted(tmp_path):
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())

    async def scenario():
        await manager.commit(project, key="plan", value="old plan", importance=1.0)
        await manager.forget(project, key="plan", reason="done")
        result = await manager.commit(project, key="plan", value="new plan", importance=0.3)
        assert result["success"] is True
        plane = await manager.get_plane(project)
        assert (await plane.backend.load("plan")).value == "new plan"
        await manager.close()

    _run(scenario())


def test_revision_keeps_only_a_fingerprint_of_the_replaced_value(tmp_path):
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())

    async def scenario():
        await manager.commit(project, key="note", value=SECRET, importance=1.0)
        await manager.commit(project, key="note", value="replacement", importance=1.0)
        plane = await manager.get_plane(project)
        metadata = (await plane.backend.load("note")).metadata
        assert "previous_value" not in metadata and "supersedes" not in metadata and "superseded_by" not in metadata
        assert len(metadata["previous_value_sha256"]) == 64
        await manager.close()
        events = sqlite3.connect(manager.db_path(project)).execute("SELECT payload_json FROM memory_events").fetchall()
        assert all("Quartz" not in payload for (payload,) in events)

    _run(scenario())


def test_rollback_refreshes_the_belief_cache(tmp_path):
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())

    async def scenario():
        await manager.commit(project, key="kept", value="v1", importance=0.5)
        snapshot = await manager.create_snapshot(project, label="base")
        await manager.commit(project, key="kept", value="v2", importance=1.0)
        await manager.commit(project, key="later", value="added after the snapshot", importance=1.0)
        await manager.rollback_execute(project, snapshot_id=snapshot.id, reason="undo", expected_current_root=None)

        plane = await manager.get_plane(project)
        assert plane.agm_engine.belief_state.get_belief("later") is None
        assert plane.agm_engine.belief_state.get_belief("kept").value == "v1"
        # A key the rollback removed takes a fresh write at any importance.
        assert (await manager.commit(project, key="later", value="again", importance=0.2))["success"] is True
        await manager.close()

    _run(scenario())


def test_local_forget_tool_clears_belief_graph_and_writes_an_event(tmp_path):
    async def scenario():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "local.sqlite")), enable_verification=False, enable_audit=True)
        await plane.init()
        plane.init_agm()
        plane.init_knowledge_graph()
        await plane.commit_with_agm_async(key="team", value="Alice works at Acme", importance=0.9)
        assert plane.knowledge_graph.memory_entities("team")

        payload = json.loads((await _handle_forget(plane, {"key": "team", "reason": "cleanup"}))[0].text)
        assert payload["removed"] is True and payload["backend_removed"] is True
        assert plane.agm_engine.belief_state.get_belief("team") is None
        assert plane.knowledge_graph.memory_entities("team") == []
        operations = [row[0] for row in plane.backend._conn.execute(
            "SELECT operation FROM memory_events WHERE memory_key = 'team'")]
        assert operations[-1] == "forget"

        unknown = json.loads((await _handle_forget(plane, {"key": "never-written"}))[0].text)
        assert unknown["removed"] is False
        assert plane.backend._conn.execute(
            "SELECT count(*) FROM audit_log WHERE key = 'never-written'").fetchone()[0] == 0

    _run(scenario())


@needs_postgres
def test_postgres_forget_drops_entity_mentions_and_purge_scrubs_events(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("BILINC_POSTGRES_DSN", DSN)
    from bilinc.storage.postgres_tenancy import project_schema

    manager = _manager(tmp_path)
    project = str(uuid.uuid4())

    async def scenario():
        import asyncpg

        await manager.commit(project, key="team", value="Alice works at Acme", importance=0.9)
        await manager.forget(project, key="team", reason="cleanup")
        await manager.commit(project, key="plan", value=SECRET, importance=1.0)
        await manager.commit(project, key="plan", value="replacement", importance=1.0)
        result = await manager.forget(project, key="plan", reason="erasure", purge=True)
        assert result["purged"]["events"] >= 1
        assert (await manager.commit(project, key="plan", value="fresh", importance=0.2))["success"] is True

        conn = await asyncpg.connect(DSN)
        schema = project_schema(project)
        try:
            assert await conn.fetchval(f'SELECT count(*) FROM "{schema}".entity_mentions WHERE memory_key = $1', "team") == 0
            payloads = await conn.fetchval(f'SELECT string_agg(payload_json::text, \' \') FROM "{schema}".memory_events')
            assert "Quartz" not in (payloads or "")
        finally:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            await conn.close()
        await manager.close()

    _run(scenario())
