"""IMP-001: a hosted revise records the memory exactly as it was stored before the edit.

``_revise_loaded`` built its entries from a shallow copy of the stored row, so metadata written into the
new version (verification flag, AGM revision fields) also appeared in the "before" state of the audit row,
the REVISE event and a rejected revision's version. Each test runs on SQLite and on Postgres.
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

from bilinc.cloud.runtime import ProjectRuntimeManager, entry_version
from bilinc.core.event_ledger import EventOperation, value_hash
from bilinc.core.models import MemoryEntry, MemoryType

_DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
BACKENDS = [
    "sqlite",
    pytest.param("postgres", marks=pytest.mark.skipif(not _DSN, reason="BILINC_TEST_POSTGRES_DSN not set")),
]


@pytest.fixture
def manager_factory(tmp_path, monkeypatch):
    made = []

    def make(backend):
        monkeypatch.setenv("BILINC_STORAGE_BACKEND", backend)
        monkeypatch.delenv("BILINC_CLOUD_EMBEDDINGS", raising=False)
        if backend == "postgres":
            monkeypatch.setenv("BILINC_POSTGRES_DSN", _DSN)
        made.append(ProjectRuntimeManager(tmp_path))
        return made[-1]

    return make


def _state(raw):
    return json.loads(raw) if isinstance(raw, str) else raw


async def _stored(plane, key):
    return (await plane.backend.load(key)).to_dict()


# 1 + 2 -------------------------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_revise_audit_and_event_hold_the_stored_previous_state(manager_factory, backend):
    manager = manager_factory(backend)
    project = str(uuid.uuid4())
    try:
        await manager.commit(project, key="deploy.target", value="staging")
        plane = await manager.get_plane(project)
        # Twice: the second time the stored row already carries a previous_value_sha256 of its own.
        for new_value in ("production", "canary"):
            before = await _stored(plane, "deploy.target")
            result = await manager.revise(project, key="deploy.target", value=new_value, reason="go live")
            assert result["success"] is True
            after = await _stored(plane, "deploy.target")

            newest = plane.audit.get_history(key="deploy.target", limit=1)[0]
            assert _state(newest.before_value) == before
            assert _state(newest.after_value) == after
            assert "previous_value_sha256" in after["metadata"]
            assert before["metadata"].get("previous_value_sha256") != after["metadata"]["previous_value_sha256"]

            events = await plane.backend.list_memory_events(
                operation=EventOperation.REVISE.value, memory_key="deploy.target"
            )
            assert events[-1].before_hash == value_hash(before)
    finally:
        await manager.close()


# 3 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_rejected_revise_returns_the_stored_rows_version(manager_factory, backend):
    manager = manager_factory(backend)
    project = str(uuid.uuid4())
    try:
        await manager.commit(project, key="seed", value="x")       # loads the plane
        plane = await manager.get_plane(project)
        # Written directly, so verification never ran: the stale flag is on the stored row.
        await plane.backend.save(MemoryEntry(
            key="flagged",
            value="a value that passes verification",
            memory_type=MemoryType.SEMANTIC,
            importance=0.9,
            metadata={"verification_failed": ["x"]},
        ))
        stored = await _stored(plane, "flagged")

        result = await manager.revise(project, key="flagged", value="lower", importance=0.3,
                                      strategy="entrenchment")
        assert result["success"] is False
        assert await _stored(plane, "flagged") == stored        # nothing was written
        assert result["entry_version"] == entry_version(stored)
    finally:
        await manager.close()


# 4 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_confirm_audit_before_state_is_the_stored_row(manager_factory, backend):
    manager = manager_factory(backend)
    project = str(uuid.uuid4())
    try:
        await manager.commit(project, key="k", value="v")
        await manager.revise(project, key="k", value="v2", reason="edit")   # metadata is not empty now
        plane = await manager.get_plane(project)
        before = await _stored(plane, "k")
        await manager.confirm(project, key="k", reason="still true")
        newest = plane.audit.get_history(key="k", limit=1)[0]
        assert _state(newest.before_value) == before
        assert _state(newest.after_value) == await _stored(plane, "k")
    finally:
        await manager.close()
