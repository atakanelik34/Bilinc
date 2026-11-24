"""IMP-002: a memory saved with low importance stays writable after a restart.

Startup loads beliefs only for rows with importance >= 0.5, and the commit path put a stored row back into
the belief cache without its entrenchment, so after a restart the row was judged against the default 0.5.
Every commit writes a different value: the same value is a no-op success that never reaches the check.
"""
from __future__ import annotations

import os
import uuid

import pytest

from bilinc.cloud.runtime import ProjectRuntimeManager
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend

_DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
BACKENDS = [
    "sqlite",
    pytest.param("postgres", marks=pytest.mark.skipif(not _DSN, reason="BILINC_TEST_POSTGRES_DSN not set")),
]


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    """``hosted(backend)`` builds a manager on one folder; call it again for a restart."""
    made = []

    def make(backend):
        monkeypatch.setenv("BILINC_STORAGE_BACKEND", backend)
        monkeypatch.delenv("BILINC_CLOUD_EMBEDDINGS", raising=False)
        if backend == "postgres":
            monkeypatch.setenv("BILINC_POSTGRES_DSN", _DSN)
        made.append(ProjectRuntimeManager(tmp_path))
        return made[-1]

    return make


async def _value(manager, project, key):
    return (await (await manager.get_plane(project)).backend.load(key)).value


# 1 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_low_importance_key_stays_writable_after_a_restart(hosted, backend):
    project = str(uuid.uuid4())
    first = hosted(backend)
    assert (await first.commit(project, key="low.key", value="v1", importance=0.3))["success"] is True
    assert (await first.commit(project, key="low.key", value="v2", importance=0.3))["success"] is True
    await first.close()

    second = hosted(backend)                                  # restart: new manager, same folder
    try:
        assert (await second.commit(project, key="low.key", value="v3", importance=0.3))["success"] is True
        assert (await second.commit(project, key="low.key", value="v4", importance=0.4))["success"] is True
        assert await _value(second, project, "low.key") == "v4"
    finally:
        await second.close()


# 2 ----------------------------------------------------------------------------------------------
PAIRS = [(0.3, 0.2), (0.3, 0.3), (0.3, 0.6), (0.7, 0.6), (0.7, 0.8)]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("stored,new", PAIRS)
async def test_the_outcome_is_the_same_before_and_after_a_restart(hosted, backend, stored, new):
    same_process = str(uuid.uuid4())
    restarted = str(uuid.uuid4())
    first = hosted(backend)
    await first.commit(same_process, key="k", value="old", importance=stored)
    await first.commit(restarted, key="k", value="old", importance=stored)
    in_process = (await first.commit(same_process, key="k", value="new", importance=new))["success"]
    await first.close()

    second = hosted(backend)
    try:
        after_restart = (await second.commit(restarted, key="k", value="new", importance=new))["success"]
        assert after_restart == in_process
        assert in_process == (new >= stored)
    finally:
        await second.close()


# 3 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_local_plane_that_never_saw_the_key_can_write_it(tmp_path):
    path = str(tmp_path / "local.sqlite")
    planes = []
    for _ in range(2):
        plane = StatePlane(backend=SQLiteBackend(path), enable_verification=False, enable_audit=True)
        await plane.init()
        plane.init_agm()
        planes.append(plane)
    a, b = planes
    try:
        assert (await a.commit_with_agm_async("low.key", "from a", importance=0.3)).success is True
        assert (await b.commit_with_agm_async("low.key", "from b", importance=0.3)).success is True
        assert (await b.backend.load("low.key")).value == "from b"
        # A third plane that never saw the key still refuses a lower importance.
        c = StatePlane(backend=SQLiteBackend(path), enable_verification=False, enable_audit=True)
        await c.init()
        c.init_agm()
        planes.append(c)
        assert (await c.commit_with_agm_async("low.key", "lower", importance=0.2)).success is False
        assert (await c.backend.load("low.key")).value == "from b"
    finally:
        for plane in planes:
            await plane.backend.close()


# 4 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_lower_importance_is_still_refused_after_a_restart(hosted, backend):
    project = str(uuid.uuid4())
    first = hosted(backend)
    await first.commit(project, key="low.key", value="kept", importance=0.3)
    await first.close()

    second = hosted(backend)
    try:
        assert (await second.commit(project, key="low.key", value="lower", importance=0.2))["success"] is False
        assert await _value(second, project, "low.key") == "kept"
    finally:
        await second.close()


# 5 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_an_entrenchment_raised_in_process_is_kept(hosted, backend):
    """Regression pin (green before the fix too): no read runs between the writes."""
    project = str(uuid.uuid4())
    manager = hosted(backend)
    try:
        await manager.commit(project, key="k", value="first", importance=0.9)
        revised = await manager.revise(project, key="k", value="second", importance=0.6, strategy="recency")
        assert revised["success"] is True                     # stored row now says 0.6
        plane = await manager.get_plane(project)
        assert plane.agm_engine.get_entrenchment("k") == 0.9  # AGM keeps the higher entrenchment
        assert (await manager.commit(project, key="k", value="third", importance=0.7))["success"] is False
    finally:
        await manager.close()
