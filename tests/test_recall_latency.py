"""Latency regressions for recall hot paths (2026-11 recall-latency work)."""

import os
import time
import uuid

import pytest

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend


def _entries(n: int) -> dict:
    now = time.time()
    entries = {}
    for i in range(n):
        entries[f"note-{i}"] = MemoryEntry(
            key=f"note-{i}",
            value=f"Team update {i}: plan item {i} owner{i % 37} budget {i * 3} region r{i % 11} status open",
            memory_type=MemoryType.EPISODIC,
            created_at=now - (n - i),
            updated_at=now - (n - i),
        )
    entries["note-editor-old"] = MemoryEntry(key="note-editor-old", value="The editor is vim",
                                             memory_type=MemoryType.SEMANTIC, created_at=now - 10_000, updated_at=now - 10_000)
    entries["note-editor-new"] = MemoryEntry(key="note-editor-new", value="The editor is helix",
                                             memory_type=MemoryType.SEMANTIC, created_at=now, updated_at=now)
    return entries


def test_current_state_collapse_keeps_its_result_and_scales_to_thousands():
    """The token document frequency used to be counted in O(N^2 * T): 5K candidates took minutes."""
    plane = StatePlane()
    candidates = _entries(50)
    collapsed = plane._collapse_current_state_candidates("what is the current editor", candidates)
    assert set(collapsed) == set(candidates) - {"note-editor-old"}
    large = _entries(5000)
    started = time.perf_counter()
    collapsed = plane._collapse_current_state_candidates("what is the current editor", large)
    elapsed = time.perf_counter() - started
    assert set(collapsed) == set(large) - {"note-editor-old"}
    # Generous on purpose (it takes well under a second); the quadratic count took minutes here.
    assert elapsed < 30, f"collapse of 5K candidates took {elapsed:.1f}s"


def test_entry_columns_cover_everything_row_to_entry_reads():
    """list_all, list_page, load and load_many select _ENTRY_COLUMNS; a field read but not selected
    would silently fall back to its default, so reading any other key must fail here."""
    from bilinc.storage import postgres

    selected = [name.strip() for name in postgres._ENTRY_COLUMNS.split(",")]

    class SelectedRow(dict):
        def __getitem__(self, key):
            if key not in selected:
                raise AssertionError(f"_row_to_entry reads {key!r}, which _ENTRY_COLUMNS does not select")
            return super().__getitem__(key)

        def get(self, key, default=None):
            if key not in selected:
                raise AssertionError(f"_row_to_entry reads {key!r}, which _ENTRY_COLUMNS does not select")
            return super().get(key, default)

    sample = {name: 0 for name in selected}
    sample.update(id="i", key="k", memory_type="semantic", value='"v"', metadata="{}", ccs_dimensions="{}",
                  source="", session_id="", verification_method="", is_verified=False, valid_at=None,
                  invalid_at=None, ttl=None, conflict_id=None, superseded_by=None)
    entry = postgres.PostgresBackend.__new__(postgres.PostgresBackend)._row_to_entry(SelectedRow(sample))
    assert entry.key == "k"


_DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")


async def _check_load_many(backend):
    for key, value in (("a", "alpha"), ("b", "beta"), ("c", "gamma")):
        await backend.save(MemoryEntry(key=key, value=value, memory_type=MemoryType.SEMANTIC))
    found = await backend.load_many(["c", "a", "missing", "a"])
    assert set(found) == {"a", "c"}
    assert found["a"].value == "alpha" and found["c"].value == "gamma"
    assert await backend.load_many([]) == {}


@pytest.mark.asyncio
async def test_sqlite_load_many(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "m.db"))
    await backend.init()
    await _check_load_many(backend)


@pytest.mark.asyncio
@pytest.mark.skipif(not _DSN, reason="BILINC_TEST_POSTGRES_DSN not set")
async def test_postgres_load_many():
    import asyncpg

    from bilinc.storage.postgres import PostgresBackend

    schema = "bilinc_p_" + uuid.uuid4().hex
    backend = PostgresBackend(_DSN, schema=schema)
    try:
        await backend.init()
        await _check_load_many(backend)
    finally:
        await backend.close()
        conn = await asyncpg.connect(_DSN)
        try:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            await conn.close()




def test_audit_trail_uses_the_same_sqlite_build_as_the_backend():
    """Two SQLite libraries in one process do not see each other's locks on the same file."""
    from bilinc.core import audit
    from bilinc.storage import sqlite as backend_module

    assert audit.sqlite3 is backend_module.sqlite3


def test_stage_timing_records_in_synchronous_code_and_not_in_other_tasks():
    import asyncio

    from bilinc.observability import stage_timing

    with stage_timing.collect() as timings:
        stage_timing.Stopwatch().lap("sync")
    assert "sync" in timings

    async def main():
        with stage_timing.collect() as scoped:
            stage_timing.Stopwatch().lap("own")
            await asyncio.create_task(_lap_elsewhere())
        return scoped

    async def _lap_elsewhere():
        stage_timing.Stopwatch().lap("other")

    scoped = asyncio.run(main())
    assert "own" in scoped and "other" not in scoped
