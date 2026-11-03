"""The AGM revision log is cleared by a hosted purge and bounded in size (item A8c).

Hosted runtime on SQLite; the Postgres variants run only when BILINC_TEST_POSTGRES_DSN is set.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from bilinc.adaptive.agm_engine import AGMEngine, redact_operation_log
from bilinc.core.models import MemoryEntry, MemoryType

DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
KINDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set"))]
FIRST = "Quartz harbor plan: call Dana Whitfield"
SECOND = "Quartz harbor plan: call Dana Whitfield (revised)"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _entry(key, value, importance=0.9):
    return MemoryEntry(key=key, value=value, memory_type=MemoryType.SEMANTIC, importance=importance)


async def _manager(kind, tmp_path, monkeypatch):
    from bilinc.cloud.runtime import ProjectRuntimeManager

    if kind == "postgres":
        monkeypatch.setenv("BILINC_STORAGE_BACKEND", "postgres")
        monkeypatch.setenv("BILINC_POSTGRES_DSN", DSN)
    return ProjectRuntimeManager(tmp_path)


@pytest.mark.parametrize("kind", KINDS)
def test_a_hosted_purge_clears_the_revision_log_of_the_key(kind, tmp_path, monkeypatch):
    async def go():
        manager = await _manager(kind, tmp_path, monkeypatch)
        project = str(uuid.uuid4())
        await manager.commit(project, key="plan", value=FIRST, importance=1.0)
        await manager.commit(project, key="plan", value=SECOND, importance=1.0)
        await manager.commit(project, key="other", value="other value", importance=1.0)
        plane = await manager.get_plane(project)
        before = repr(plane.agm_engine.operation_log)
        await manager.forget(project, key="plan", reason="erasure", purge=True)
        log = plane.agm_engine.operation_log
        after = repr(log)
        names = [key for result in log for key in (result.affected_keys or [])]
        await manager.close()
        return before, after, names

    before, after, names = _run(go())
    assert "Dana Whitfield" in before  # the log really held the text
    assert "Dana Whitfield" not in after and "plan" not in names
    assert "other" in names  # records of other keys survive


@pytest.mark.parametrize("kind", KINDS)
def test_the_log_is_already_clean_when_a_later_purge_step_fails(kind, tmp_path, monkeypatch):
    async def go():
        manager = await _manager(kind, tmp_path, monkeypatch)
        project = str(uuid.uuid4())
        await manager.commit(project, key="plan", value=FIRST, importance=1.0)
        await manager.commit(project, key="plan", value=SECOND, importance=1.0)
        plane = await manager.get_plane(project)

        def broken(*args, **kwargs):
            raise RuntimeError("disk trouble")

        plane.audit.purge_key = broken
        with pytest.raises(RuntimeError):
            await manager.forget(project, key="plan", reason="erasure", purge=True)
        text = repr(plane.agm_engine.operation_log)
        await manager.close()
        return text

    assert "Dana Whitfield" not in _run(go())


def test_the_log_keeps_the_newest_records_and_the_total_counts_all():
    engine = AGMEngine(max_operation_log=5)
    for n in range(12):
        engine.revise(_entry(f"k{n}", f"value {n}"))
    assert len(engine.operation_log) == 5
    assert [r.affected_keys[0] for r in engine.operation_log] == ["k7", "k8", "k9", "k10", "k11"]
    assert engine.operations_total == 12


def test_redaction_does_not_reduce_the_total():
    engine = AGMEngine()
    engine.revise(_entry("a", "x"))
    engine.revise(_entry("b", "y"))
    assert redact_operation_log(engine, "a") == 1
    assert len(engine.operation_log) == 1 and engine.operations_total == 2


def test_default_cap_and_the_bounds_of_the_setting():
    engine = AGMEngine()
    for n in range(1005):
        engine.revise(_entry(f"k{n}", f"value {n}"))
    assert len(engine.operation_log) == 1000 and engine.operations_total == 1005

    unbounded = AGMEngine(max_operation_log=None)
    for n in range(1005):
        unbounded.revise(_entry(f"k{n}", f"value {n}"))
    assert len(unbounded.operation_log) == 1005

    for bad in (0, -1):
        with pytest.raises(ValueError):
            AGMEngine(max_operation_log=bad)


def test_status_figures_report_the_total_not_the_trimmed_length():
    from bilinc.core.stateplane import StatePlane
    from bilinc.storage.sqlite import SQLiteBackend

    plane = StatePlane(backend=SQLiteBackend(":memory:"), enable_verification=False, enable_audit=False)
    plane.init_agm()
    plane.agm_engine.max_operation_log = 3
    for n in range(10):
        plane.agm_engine.revise(_entry(f"k{n}", f"v{n}"))
    assert len(plane.agm_engine.operation_log) == 3
    assert plane.phase3_stats()["agm"]["operations"] == 10


def test_a_purge_of_a_key_without_records_is_harmless():
    engine = AGMEngine()
    engine.revise(_entry("a", "x"))
    assert redact_operation_log(engine, "never-written") == 0
    assert len(engine.operation_log) == 1
