"""A8e: a snapshot's root hash is read from the store and only recorded when it held still during the read.

Two runtime managers stand in for two workers on one project; each plane has its own audit trail
(its own cached head) over one store. Tests marked "both" run on SQLite and on Postgres.
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

from bilinc.cloud.runtime import ProjectRuntimeManager
from bilinc.core.audit import OpType
from bilinc.core.event_ledger import EventOperation

_DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
BACKENDS = [
    "sqlite",
    pytest.param("postgres", marks=pytest.mark.skipif(not _DSN, reason="BILINC_TEST_POSTGRES_DSN not set")),
]
SNAPSHOT_KEYS = {
    "timestamp", "total_entries", "by_type", "entries", "working_memory_count", "root_hash", "integrity", "ops_count",
}


class _Workers:
    def __init__(self, tmp_path, monkeypatch, backend):
        monkeypatch.setenv("BILINC_STORAGE_BACKEND", backend)
        monkeypatch.delenv("BILINC_CLOUD_EMBEDDINGS", raising=False)
        if backend == "postgres":
            monkeypatch.setenv("BILINC_POSTGRES_DSN", _DSN)
        self.a = ProjectRuntimeManager(tmp_path)
        self.b = ProjectRuntimeManager(tmp_path)
        self.project = str(uuid.uuid4())

    async def stale_a(self):
        """A writes, then B writes: A's cached head is now stale. Returns (A's plane, B's plane, the real head)."""
        await self.a.commit(self.project, key="base", value="1")
        head = (await self.b.commit(self.project, key="intruder", value="2"))["state_version"]
        plane_a, plane_b = await self.a.get_plane(self.project), await self.b.get_plane(self.project)
        assert plane_a.audit.get_root_hash() != head          # the gap this item closes
        return plane_a, plane_b, head

    async def close(self):
        await self.a.close()
        await self.b.close()


@pytest.fixture
def workers_factory(tmp_path, monkeypatch):
    made = []

    def make(backend):
        made.append(_Workers(tmp_path, monkeypatch, backend))
        return made[-1]

    yield make


def _moving_head(monkeypatch, plane, other_plane, *, times):
    """Make the other writer append an audit row during the first ``times`` state reads of ``plane``."""
    original = plane.backend.list_all
    calls = {"n": 0}

    async def list_all(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= times:
            other_plane.audit.log(OpType.CREATE, f"during-read-{calls['n']}", None, {"n": calls["n"]})
        return await original(*args, **kwargs)

    monkeypatch.setattr(plane.backend, "list_all", list_all)
    return calls


async def _snapshot_events(plane):
    return await plane.backend.list_memory_events(operation=EventOperation.SNAPSHOT.value)


# 1 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_snapshot_records_the_store_head_not_the_stale_cache(workers_factory, backend):
    w = workers_factory(backend)
    try:
        plane_a, _plane_b, head = await w.stale_a()
        snap = await plane_a.snapshot()
        assert snap["root_hash"] == head
        assert "intruder" in snap["entries"]
        events = await _snapshot_events(plane_a)
        assert events[-1].checkpoint_root == head
    finally:
        await w.close()


# 2 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_hosted_checkpoint_diff_and_preview_show_the_fresh_head(workers_factory, backend):
    w = workers_factory(backend)
    try:
        _plane_a, _plane_b, head = await w.stale_a()
        created = await w.a.create_snapshot(w.project, label="after-intruder")
        assert created.root_hash == head
        stored = await w.a.load_snapshot(w.project, created.id)
        assert stored["root_hash"] == head and stored["snapshot"]["root_hash"] == head
        assert (await w.a.diff(w.project, from_snapshot_id=created.id))["from_root_hash"] == head
        assert (await w.a.rollback_preview(w.project, snapshot_id=created.id))["target_root_hash"] == head
    finally:
        await w.close()


# 3 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_head_moving_once_is_retried_and_the_stable_head_recorded(workers_factory, backend, monkeypatch):
    w = workers_factory(backend)
    try:
        plane_a, plane_b, _head = await w.stale_a()
        calls = _moving_head(monkeypatch, plane_a, plane_b, times=1)
        snap = await plane_a.snapshot()
        stable = plane_b.audit.refresh_root_hash()
        assert calls["n"] == 2
        assert snap["root_hash"] == stable
        assert snap["integrity"]["valid"] is True
        assert (await _snapshot_events(plane_a))[-1].checkpoint_root == stable
    finally:
        await w.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_head_that_never_holds_still_is_a_version_conflict_and_writes_nothing(
    workers_factory, backend, monkeypatch
):
    w = workers_factory(backend)
    try:
        plane_a, plane_b, _head = await w.stale_a()
        events_before = len(await _snapshot_events(plane_a))
        calls = _moving_head(monkeypatch, plane_a, plane_b, times=1000)
        with pytest.raises(ValueError, match="^version_conflict$"):
            await w.a.create_snapshot(w.project, label="never")
        assert calls["n"] == 3                                   # bounded
        assert await w.a.list_snapshots(w.project) == []         # no checkpoint file
        assert len(await _snapshot_events(plane_a)) == events_before
    finally:
        await w.close()


# 4 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_failed_head_read_fails_snapshot_stats_and_verify(workers_factory, backend, monkeypatch):
    w = workers_factory(backend)
    try:
        plane_a, _plane_b, _head = await w.stale_a()

        def broken():
            raise RuntimeError("store unreachable")

        monkeypatch.setattr(plane_a.audit, "refresh_root_hash", broken)
        with pytest.raises(RuntimeError, match="store unreachable"):
            await plane_a.snapshot()
        with pytest.raises(RuntimeError, match="store unreachable"):
            await plane_a.stats()
        with pytest.raises(RuntimeError, match="store unreachable"):
            await plane_a.verify("base")
        audit = plane_a.health.readiness()["components"]["audit"]
        assert audit["status"] == "failed"
        assert "root_hash" not in audit
    finally:
        await w.close()


# 5 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_single_writer_snapshot_reads_once_and_keeps_its_shape(workers_factory, backend, monkeypatch):
    w = workers_factory(backend)
    try:
        own = (await w.a.commit(w.project, key="only", value="1"))["state_version"]
        plane = await w.a.get_plane(w.project)
        calls = _moving_head(monkeypatch, plane, plane, times=0)
        snap = await plane.snapshot()
        assert calls["n"] == 1
        assert snap["root_hash"] == own
        assert set(snap) == SNAPSHOT_KEYS
    finally:
        await w.close()


# 6 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_without_audit_the_root_is_none(tmp_path):
    from bilinc.core.stateplane import StatePlane
    from bilinc.storage.sqlite import SQLiteBackend

    backend = SQLiteBackend(str(tmp_path / "no-audit.db"))
    await backend.init()
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    try:
        await plane.commit("k", "v")
        snap = await plane.snapshot()
        assert snap["root_hash"] is None and snap["integrity"] is None
    finally:
        await backend.close()


# 7 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_stats_verify_and_health_show_the_other_writers_head(workers_factory, backend):
    w = workers_factory(backend)
    try:
        plane_a, _plane_b, head = await w.stale_a()
        assert (await plane_a.stats())["audit"]["root_hash"] == head
        assert (await plane_a.verify("base"))["root_hash"] == head
        assert plane_a.health.readiness()["components"]["audit"]["root_hash"] == head
    finally:
        await w.close()


# 8 ----------------------------------------------------------------------------------------------
def test_service_answers_an_unstable_snapshot_with_409_version_conflict(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from bilinc.cloud.service import create_app

    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("BILINC_CLOUD_EMBEDDINGS", raising=False)
    headers = {"X-Bilinc-Sidecar-Token": "secret"}
    project = str(uuid.uuid4())
    with TestClient(create_app(runtime_dir=tmp_path, sidecar_token="secret")) as client:
        assert client.post(f"/v1/projects/{project}/commit", json={"key": "k", "value": "v"},
                           headers=headers).status_code == 200
        manager = client.app.state.runtime_manager
        plane = client.portal.call(manager.get_plane, project)
        _moving_head(monkeypatch, plane, plane, times=1000)
        response = client.post(f"/v1/projects/{project}/snapshots", json={"label": "x"}, headers=headers)
        assert response.status_code == 409
        assert response.json()["detail"] == "version_conflict"
        listed = client.get(f"/v1/projects/{project}/snapshots", headers=headers)
        assert listed.json()["snapshots"] == []


# 9 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stdio_snapshot_tool_reports_version_conflict(workers_factory, monkeypatch):
    from mcp.types import CallToolRequest, CallToolRequestParams

    from bilinc.mcp_server.server_v2 import _create_server_v2

    w = workers_factory("sqlite")
    try:
        plane_a, plane_b, _head = await w.stale_a()
        _moving_head(monkeypatch, plane_a, plane_b, times=1000)
        server = _create_server_v2(plane_a)
        handler = server.request_handlers[CallToolRequest]
        response = await handler(CallToolRequest(params=CallToolRequestParams(name="snapshot", arguments={})))
        payload = json.loads(response.root.content[0].text)
        assert payload["success"] is False
        assert payload["message"] == "version_conflict"
    finally:
        await w.close()
