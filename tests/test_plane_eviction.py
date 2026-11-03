"""A8b: hosted planes are evicted when idle (opt-in), never while an operation is in flight."""
from __future__ import annotations

import asyncio
import itertools
import logging
import os
import time
import uuid
from types import SimpleNamespace

import pytest

from bilinc.cloud.runtime import ProjectRuntimeManager

IDLE = 100.0


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds=IDLE + 1):
        self.now += seconds


def _manager(tmp_path, monkeypatch, *, idle=IDLE, cap=None, clock=None):
    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("BILINC_CLOUD_EMBEDDINGS", raising=False)
    if idle is None:
        monkeypatch.delenv("BILINC_CLOUD_PLANE_IDLE_SECONDS", raising=False)
    else:
        monkeypatch.setenv("BILINC_CLOUD_PLANE_IDLE_SECONDS", str(idle))
    if cap is None:
        monkeypatch.delenv("BILINC_CLOUD_PLANE_MAX", raising=False)
    else:
        monkeypatch.setenv("BILINC_CLOUD_PLANE_MAX", str(cap))
    manager = ProjectRuntimeManager(tmp_path)
    manager._clock = clock or Clock()
    return manager


def _pid() -> str:
    return str(uuid.uuid4())


async def _settle(manager):
    """Wait for the background closes started by an eviction."""
    while manager._closing:
        await asyncio.wait(list(manager._closing), timeout=5)


async def _evict(manager, clock):
    clock.advance()
    victims = manager._evict_idle()
    await _settle(manager)
    return victims


# ---- idle eviction --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_idle_plane_is_evicted_closed_and_reloaded_from_storage(tmp_path, monkeypatch):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, clock=clock)
    a = _pid()
    try:
        await manager.commit(a, key="note", value="kept")
        old = manager._planes[manager.normalize_project_id(a)]
        assert manager._inflight.get(manager.normalize_project_id(a), 0) == 0
        await _evict(manager, clock)
        key = manager.normalize_project_id(a)
        assert key not in manager._planes
        assert key not in manager._inflight and key not in manager._last_used
        recalled = await manager.recall(a, query="note", profile="fast", limit=5)
        assert "note" in {item["key"] for item in recalled["results"]}
        assert manager._planes[key] is not old
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_default_is_off_and_zero_keeps_planes(tmp_path, monkeypatch):
    for idle in (None, 0):
        clock = Clock()
        manager = _manager(tmp_path / f"m{idle}", monkeypatch, idle=idle, clock=clock)
        try:
            await manager.commit(_pid(), key="k", value="v")
            clock.advance(10 ** 6)
            assert manager._evict_idle() == []
            assert len(manager._planes) == 1
            assert manager._reaper_task is None
        finally:
            await manager.close()


@pytest.mark.asyncio
async def test_garbage_settings_fall_back_to_the_defaults(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("BILINC_CLOUD_PLANE_IDLE_SECONDS", "soon")
    monkeypatch.setenv("BILINC_CLOUD_PLANE_MAX", "many")
    with caplog.at_level(logging.WARNING):
        manager = ProjectRuntimeManager(tmp_path)
    assert manager._plane_idle_seconds == 0 and manager._plane_max == 0
    assert "BILINC_CLOUD_PLANE_IDLE_SECONDS" in caplog.text and "soon" not in caplog.text


# ---- in flight ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_plane_with_an_operation_in_flight_is_not_evicted(tmp_path, monkeypatch):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, clock=clock)
    a = _pid()
    key = manager.normalize_project_id(a)
    try:
        await manager.commit(a, key="first", value="v")
        plane = manager._planes[key]
        entered, release = asyncio.Event(), asyncio.Event()
        real_save = plane.backend.save

        async def blocked_save(*args, **kwargs):
            entered.set()
            await release.wait()
            return await real_save(*args, **kwargs)

        plane.backend.save = blocked_save
        task = asyncio.create_task(manager.commit(a.upper(), key="second", value="v"))  # upper-case id on purpose
        await asyncio.wait_for(entered.wait(), 5)
        clock.advance()
        assert manager._evict_idle() == []
        assert manager._planes[key] is plane
        release.set()
        await task
        assert (await plane.backend.load("second")) is not None
        await _evict(manager, clock)
        assert key not in manager._planes
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_an_invalid_id_leaves_no_bookkeeping(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    try:
        with pytest.raises(ValueError, match="invalid_project_id"):
            await manager.commit("not-a-uuid", key="k", value="v")
        assert manager._inflight == {} and manager._last_used == {}
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_a_call_that_fails_before_a_plane_exists_leaves_no_bookkeeping(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)

    async def broken(project_id):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(manager, "get_plane", broken)
    try:
        with pytest.raises(RuntimeError):
            await manager.commit(_pid(), key="k", value="v")
        assert manager._inflight == {} and manager._last_used == {}
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_a_mutation_in_flight_and_one_after_an_eviction_share_one_lock(tmp_path, monkeypatch):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, clock=clock)
    a = _pid()
    try:
        await manager.commit(a, key="k", value="v")
        lock = await manager._project_mutation_lock(a)
        await _evict(manager, clock)
        assert await manager._project_mutation_lock(a) is lock
    finally:
        await manager.close()


# ---- cap ------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_cap_evicts_the_least_recently_used_idle_plane(tmp_path, monkeypatch):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, idle=0, cap=2, clock=clock)
    ids = [_pid() for _ in range(3)]
    try:
        for project in ids:
            await manager.commit(project, key="k", value="v")
            clock.advance(1)
        await _settle(manager)
        loaded = set(manager._planes)
        assert len(loaded) == 2
        assert manager.normalize_project_id(ids[0]) not in loaded  # the least recently used one
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_the_cap_never_evicts_the_plane_its_own_get_plane_returns(tmp_path, monkeypatch):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, idle=0, cap=1, clock=clock)
    try:
        for _ in range(2):
            plane = await manager.get_plane(_pid())
            await _settle(manager)
            assert plane in manager._planes.values()
            assert plane.backend._conn is not None
            clock.now -= 50  # the next plane looks older than this one, so only `keep` can save it
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_a_missing_last_used_counts_as_the_oldest(tmp_path, monkeypatch):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, idle=0, cap=1, clock=clock)
    try:
        a = await manager.get_plane(_pid())
        manager._last_used.clear()
        await manager.get_plane(_pid())
        await _settle(manager)
        assert a not in manager._planes.values()
    finally:
        await manager.close()


# ---- closing --------------------------------------------------------------------------------

def _hang_the_close(plane):
    terminated = []

    async def hang():
        await asyncio.Event().wait()

    plane.backend.close = hang
    plane.backend.pool = SimpleNamespace(terminate=lambda: terminated.append(True))
    return terminated


@pytest.mark.asyncio
async def test_a_hanging_close_does_not_stall_a_request_and_ends_terminated(tmp_path, monkeypatch):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, clock=clock)
    manager._close_timeout = 1.0
    a, b = _pid(), _pid()
    try:
        await manager.commit(a, key="k", value="v")
        terminated = _hang_the_close(manager._planes[manager.normalize_project_id(a)])
        clock.advance()
        manager._evict_idle()
        await manager.commit(b, key="k", value="v")          # another tenant's call
        assert manager._closing and not any(task.done() for task in manager._closing)  # the close is still hanging
        await _settle(manager)
        assert terminated == [True]
        assert manager._closing == {}
    finally:
        started = time.monotonic()
        await manager.close()
        assert time.monotonic() - started < 3


@pytest.mark.asyncio
async def test_a_close_that_raises_fails_nothing(tmp_path, monkeypatch, caplog):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, clock=clock)
    a = _pid()
    try:
        await manager.commit(a, key="k", value="v")
        plane = manager._planes[manager.normalize_project_id(a)]

        async def boom():
            raise RuntimeError("secret detail")

        plane.backend.close = boom
        with caplog.at_level(logging.WARNING):
            await _evict(manager, clock)
        assert manager.normalize_project_id(a) not in manager._planes
        assert "secret detail" not in caplog.text
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_sqlite_eviction_closes_the_audit_connection_without_errors(tmp_path, monkeypatch, caplog):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, clock=clock)
    a = _pid()
    try:
        await manager.commit(a, key="k", value="v")
        plane = manager._planes[manager.normalize_project_id(a)]
        assert plane.audit is not None and plane.audit.conn is not None
        with caplog.at_level(logging.WARNING):
            await _evict(manager, clock)
        assert plane.audit.conn is None
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_manager_close_closes_the_audit_trail_of_remaining_planes(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    await manager.commit(_pid(), key="k", value="v")
    plane = next(iter(manager._planes.values()))
    await manager.close()
    assert plane.audit.conn is None


@pytest.mark.asyncio
async def test_purge_waits_for_a_pending_close_of_the_same_project(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_PURGE_ENABLED", "1")
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, clock=clock)
    manager._close_timeout = 0.3
    a = _pid()
    try:
        await manager.commit(a, key="k", value="v")
        _hang_the_close(manager._planes[manager.normalize_project_id(a)])
        clock.advance()
        manager._evict_idle()
        started = time.monotonic()
        receipt = await manager.purge_project(a)
        assert time.monotonic() - started >= 0.25          # waited for the bound / termination
        assert receipt["purged"] is True and not manager.project_dir(a).exists()
        assert manager._closing == {}
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_the_indexer_is_told_before_and_after_the_close(tmp_path, monkeypatch):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, clock=clock)
    a = _pid()
    try:
        await manager.commit(a, key="k", value="v")
        plane = manager._planes[manager.normalize_project_id(a)]
        plane.backend.schema = "bilinc_p_stub"
        events = []
        manager._indexer = SimpleNamespace(forget_tenant=lambda schema: events.append(("forget", schema)),
                                           nudge=lambda: None)
        real_close = plane.backend.close

        async def close():
            events.append(("close", None))
            return await real_close()

        plane.backend.close = close
        await _evict(manager, clock)
        assert events == [("forget", "bilinc_p_stub"), ("close", None), ("forget", "bilinc_p_stub")]
    finally:
        manager._indexer = None
        await manager.close()


# ---- reaper ---------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_reaper_evicts_without_any_call_and_close_cancels_it(tmp_path, monkeypatch):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, clock=clock)
    manager._reap_interval = 0.02
    a = _pid()
    await manager.commit(a, key="k", value="v")
    assert manager._reaper_task is not None
    clock.advance()
    for _ in range(100):
        if not manager._planes:
            break
        await asyncio.sleep(0.02)
    assert not manager._planes
    task = manager._reaper_task
    await manager.close()
    assert task.done() and manager._reaper_task is None


@pytest.mark.asyncio
async def test_the_reaper_survives_one_failed_round(tmp_path, monkeypatch, caplog):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, clock=clock)
    manager._reap_interval = 0.02
    real = manager._evict_idle
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("secret detail")
        return real()

    manager._evict_idle = flaky
    try:
        await manager.commit(_pid(), key="k", value="v")
        clock.advance()
        for _ in range(100):
            if not manager._planes:
                break
            await asyncio.sleep(0.02)
        assert not manager._planes and calls["n"] >= 2
        assert "secret detail" not in caplog.text
    finally:
        manager._evict_idle = real
        await manager.close()


# ---- integrity and churn --------------------------------------------------------------------

async def _audit_rows(plane):
    return [(r["id"], r["prev_root"], r["root_hash"]) for r in
            plane.audit.conn.execute("SELECT id, prev_root, root_hash FROM audit_log ORDER BY id").fetchall()]


@pytest.mark.asyncio
async def test_the_audit_chain_continues_across_an_eviction(tmp_path, monkeypatch):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, clock=clock)
    a = _pid()
    key = manager.normalize_project_id(a)
    try:
        await manager.commit(a, key="one", value="1")
        before = await _audit_rows(manager._planes[key])
        await _evict(manager, clock)
        await manager.commit(a, key="two", value="2")
        await manager.forget(a, key="one", reason="test")
        plane = manager._planes[key]
        rows = await _audit_rows(plane)
        assert rows[: len(before)] == before
        assert rows[len(before)][1] == before[-1][2]          # prev_root == last root_hash before the eviction
        assert plane.audit.verify_integrity()["valid"] is True
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_a_reloaded_plane_starts_with_an_empty_knowledge_graph(tmp_path, monkeypatch):
    clock = Clock()
    manager = _manager(tmp_path, monkeypatch, clock=clock)
    a = _pid()
    try:
        await manager.commit(a, key="note", value="Bilinc is memory for agents")
        await _evict(manager, clock)
        plane = await manager.get_plane(a)
        assert plane.knowledge_graph is not None and len(plane.knowledge_graph._nodes) == 0
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_churn_every_call_succeeds_and_every_key_survives(tmp_path, monkeypatch):
    ticks = itertools.count()

    class StepClock:
        def __call__(self):
            return next(ticks) * 5.0

    manager = _manager(tmp_path, monkeypatch, idle=10, clock=StepClock())
    ids = [_pid() for _ in range(5)]

    async def op(i):
        project = ids[i % 5]
        await manager.commit(project, key=f"k{i}", value=f"v{i}")
        manager._evict_idle()
        await manager.recall(project, query=f"v{i}", profile="fast", limit=3)

    try:
        await asyncio.gather(*(op(i) for i in range(40)))
        await _settle(manager)
        manager._clock = lambda: 10 ** 9
        for i in range(40):
            plane = await manager.get_plane(ids[i % 5])
            assert (await plane.backend.load(f"k{i}")) is not None
    finally:
        await manager.close()


# ---- Postgres (gated) -----------------------------------------------------------------------

_DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")


@pytest.mark.skipif(not _DSN, reason="BILINC_TEST_POSTGRES_DSN not set")
def test_hosted_postgres_eviction_closes_pool_and_audit_and_reloads(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("BILINC_POSTGRES_DSN", _DSN)
    monkeypatch.setenv("BILINC_CLOUD_PLANE_IDLE_SECONDS", str(IDLE))
    monkeypatch.delenv("BILINC_CLOUD_EMBEDDINGS", raising=False)
    clock = Clock()
    project = _pid()

    async def scenario():
        manager = ProjectRuntimeManager(tmp_path)
        manager._clock = clock
        try:
            await manager.commit(project, key="note", value="kept")
            key = manager.normalize_project_id(project)
            old = manager._planes[key]
            rows_before = old.audit.verify_integrity()
            assert rows_before["valid"] is True
            await _evict(manager, clock)
            assert old.audit.conn is None
            assert old.backend.pool is None or old.backend.pool._closed
            await manager.commit(project, key="again", value="2")
            plane = manager._planes[key]
            assert plane is not old and plane.audit.verify_integrity()["valid"] is True
            recalled = await manager.recall(project, query="note", profile="fast", limit=5)
            assert "note" in {item["key"] for item in recalled["results"]}
        finally:
            await manager.close()

    asyncio.run(scenario())
