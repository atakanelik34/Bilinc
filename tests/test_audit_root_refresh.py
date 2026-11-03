"""A8d: the root hash that the rollback check binds to and compares against is read from the store, not a cache.

Two writers (two audit trails, or two runtime managers) stand in for two workers on one project.
"""
from __future__ import annotations

import os
import uuid

import pytest

from bilinc.cloud import runtime as runtime_module
from bilinc.cloud.runtime import ProjectRuntimeManager
from bilinc.core.audit import AuditTrail, OpType

GENESIS = "0" * 64


# ---- trail level ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sqlite_trail_refresh_reads_the_other_writers_head(tmp_path):
    path = str(tmp_path / "audit.db")
    first, second = AuditTrail(path), AuditTrail(path)
    await first.init()
    await second.init()
    try:
        assert first.refresh_root_hash() == GENESIS            # empty log
        first.log(OpType.CREATE, "a", None, {"n": 1})
        head = second.log(OpType.CREATE, "b", None, {"n": 2}).root_hash
        assert first.get_root_hash() != head                   # the cache is stale: this is the gap
        assert first.refresh_root_hash() == head
        assert first.get_root_hash() == head                   # the cache is right again
    finally:
        await first.close()
        await second.close()


_DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
needs_postgres = pytest.mark.skipif(not _DSN, reason="BILINC_TEST_POSTGRES_DSN not set")


@needs_postgres
@pytest.mark.asyncio
async def test_postgres_trail_refresh_reads_the_other_writers_head():
    from bilinc.core.postgres_audit_sync import SyncPostgresAuditTrail

    schema = "bilinc_p_" + uuid.uuid4().hex
    first, second = SyncPostgresAuditTrail(_DSN, schema=schema), SyncPostgresAuditTrail(_DSN, schema=schema)
    await first.init()
    await second.init()
    try:
        assert first.refresh_root_hash() == GENESIS
        first.log(OpType.CREATE, "a", None, {"n": 1})
        head = second.log(OpType.CREATE, "b", None, {"n": 2}).root_hash
        assert first.get_root_hash() != head
        assert first.refresh_root_hash() == head and first.get_root_hash() == head
    finally:
        await first.close()
        await second.close()


# ---- runtime level: two workers ------------------------------------------------------------------

async def _two_workers(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("BILINC_STORAGE_BACKEND", backend)
    monkeypatch.delenv("BILINC_CLOUD_EMBEDDINGS", raising=False)
    if backend == "postgres":
        monkeypatch.setenv("BILINC_POSTGRES_DSN", _DSN)
    return ProjectRuntimeManager(tmp_path), ProjectRuntimeManager(tmp_path)


async def _stale_root_scenario(tmp_path, monkeypatch, backend, site):
    """Each site runs first after the other worker's write, so nothing has refreshed this worker's cache yet."""
    a, b = await _two_workers(tmp_path, monkeypatch, backend)
    project = str(uuid.uuid4())
    try:
        await a.commit(project, key="base", value="1")
        snapshot = await a.create_snapshot(project, label="before")
        stale = (await a.rollback_preview(project, snapshot_id=snapshot.id))["current_root_hash"]
        head = (await b.commit(project, key="intruder", value="2"))["state_version"]   # another worker writes
        assert head != stale

        if site == "preview":
            assert (await a.rollback_preview(project, snapshot_id=snapshot.id))["current_root_hash"] == head
        elif site == "diff":
            assert (await a.diff(project, from_snapshot_id=snapshot.id))["to_root_hash"] == head
        else:
            # an execute bound to the stale root is refused and changes nothing
            with pytest.raises(ValueError, match="state_changed_since_preview"):
                await a.rollback_execute(project, snapshot_id=snapshot.id, reason="test", expected_current_root=stale)
            assert await (await b.get_plane(project)).backend.load("intruder") is not None
            # an execute bound to the fresh root goes through
            await a.rollback_execute(project, snapshot_id=snapshot.id, reason="test", expected_current_root=head)
            assert await (await a.get_plane(project)).backend.load("intruder") is None
    finally:
        await a.close()
        await b.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("site", ["preview", "diff", "execute"])
async def test_sqlite_two_workers_rollback_check_sees_the_other_writer(tmp_path, monkeypatch, site):
    await _stale_root_scenario(tmp_path, monkeypatch, "sqlite", site)


@needs_postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("site", ["preview", "diff", "execute"])
async def test_postgres_two_workers_rollback_check_sees_the_other_writer(tmp_path, monkeypatch, site):
    await _stale_root_scenario(tmp_path, monkeypatch, "postgres", site)


@pytest.mark.asyncio
async def test_a_failed_head_read_fails_the_call_and_changes_nothing(tmp_path, monkeypatch):
    manager, _other = await _two_workers(tmp_path, monkeypatch, "sqlite")
    project = str(uuid.uuid4())
    try:
        await manager.commit(project, key="base", value="1")
        snapshot = await manager.create_snapshot(project, label="before")
        await manager.commit(project, key="later", value="2")
        plane = await manager.get_plane(project)

        def broken():
            raise RuntimeError("store unreachable")

        monkeypatch.setattr(plane.audit, "refresh_root_hash", broken)
        with pytest.raises(RuntimeError, match="store unreachable"):
            await manager.rollback_preview(project, snapshot_id=snapshot.id)
        with pytest.raises(RuntimeError, match="store unreachable"):
            await manager.diff(project, from_snapshot_id=snapshot.id)
        with pytest.raises(RuntimeError, match="store unreachable"):
            await manager.rollback_execute(project, snapshot_id=snapshot.id, reason="t",
                                           expected_current_root=plane.audit.get_root_hash())
        assert await plane.backend.load("later") is not None      # nothing was restored
    finally:
        await manager.close()
        await _other.close()


@pytest.mark.asyncio
async def test_preview_reads_the_head_before_the_state(tmp_path, monkeypatch):
    manager, _other = await _two_workers(tmp_path, monkeypatch, "sqlite")
    project = str(uuid.uuid4())
    try:
        await manager.commit(project, key="base", value="1")
        snapshot = await manager.create_snapshot(project, label="before")
        plane = await manager.get_plane(project)
        order = []
        real_refresh, real_state = plane.audit.refresh_root_hash, plane._persistent_state

        def refresh():
            order.append("head")
            return real_refresh()

        async def state():
            order.append("state")
            return await real_state()

        monkeypatch.setattr(plane.audit, "refresh_root_hash", refresh)
        monkeypatch.setattr(plane, "_persistent_state", state)
        await manager.rollback_preview(project, snapshot_id=snapshot.id)
        assert order == ["head", "state"]
    finally:
        await manager.close()
        await _other.close()


@pytest.mark.asyncio
async def test_single_writer_responses_keep_the_root_their_own_write_produced(tmp_path, monkeypatch):
    manager, _other = await _two_workers(tmp_path, monkeypatch, "sqlite")
    project = str(uuid.uuid4())
    try:
        response = await manager.commit(project, key="base", value="1")
        plane = await manager.get_plane(project)
        assert response["state_version"] == plane.audit.get_root_hash()
        assert runtime_module.fresh_state_version(plane) == response["state_version"]
    finally:
        await manager.close()
        await _other.close()


def test_fresh_state_version_is_none_without_audit():
    class NoAudit:
        enable_audit = False
        audit = None

    assert runtime_module.fresh_state_version(NoAudit()) is None


