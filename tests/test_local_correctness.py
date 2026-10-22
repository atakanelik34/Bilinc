"""Local store correctness: consolidation keeps long-term types, timestamps, TTL and upserts."""
from __future__ import annotations

import time

import pytest

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend


async def _plane(tmp_path, name="local.sqlite") -> StatePlane:
    plane = StatePlane(backend=SQLiteBackend(str(tmp_path / name)), enable_verification=False, enable_audit=True)
    await plane.init()
    return plane


@pytest.mark.asyncio
async def test_consolidation_does_not_rewrite_a_warmed_semantic_memory_as_episodic(tmp_path):
    seed = SQLiteBackend(str(tmp_path / "local.sqlite"))
    await seed.init()
    await seed.restore(MemoryEntry(key="pref:editor", value="uses vim", memory_type=MemoryType.SEMANTIC,
                                   importance=0.9, access_count=5))
    await seed.restore(MemoryEntry(key="scratch", value="draft note", memory_type=MemoryType.WORKING, importance=0.9))
    await seed.close()

    plane = await _plane(tmp_path)  # startup warms the semantic memory into working memory
    assert plane.working_memory.get("pref:editor") is not None
    consolidated = await plane.consolidate()

    assert (await plane.backend.load("pref:editor")).memory_type == MemoryType.SEMANTIC
    assert (await plane.backend.load("scratch")).memory_type == MemoryType.EPISODIC
    assert consolidated == 1


@pytest.mark.asyncio
async def test_iso_text_timestamps_are_read_as_epoch_seconds(tmp_path):
    plane = await _plane(tmp_path)
    conn = plane.backend._conn
    conn.execute(
        "INSERT INTO memories (id, key, memory_type, value, created_at, updated_at) "
        "VALUES ('1', 'iso', 'semantic', '\"text\"', '2026-08-03T09:37:25.000Z', '2026-08-03T09:37:25Z')"
    )
    conn.commit()
    entry = await plane.backend.load("iso")
    assert isinstance(entry.created_at, float) and isinstance(entry.updated_at, float)
    assert entry.created_at == pytest.approx(1785749845.0)
    assert [e.key for e in await plane.backend.list_all()] == ["iso"]


@pytest.mark.asyncio
async def test_a_later_write_updates_provenance_and_ttl(tmp_path):
    plane = await _plane(tmp_path)
    backend = plane.backend
    first = MemoryEntry(key="note", value="first", source="claude", session_id="s1")
    await backend.save(first)
    second = MemoryEntry(key="note", value="second", source="codex", session_id="s2", ttl=60.0,
                         invalid_at=time.time() + 60.0)
    await backend.save(second)

    stored = await backend.load("note")
    assert (stored.source, stored.session_id, stored.ttl) == ("codex", "s2", 60.0)
    assert stored.invalid_at is not None
    assert stored.id == first.id  # the row keeps its identity


def test_a_ttl_set_on_a_later_write_counts_from_that_write():
    plane = StatePlane()
    now = time.time()
    old_row = MemoryEntry(key="old", value="kept", created_at=now - 3600, ttl=60.0, invalid_at=now + 60.0)
    assert plane._is_recallable_entry(old_row, now=now) is True
    expired = MemoryEntry(key="gone", value="x", created_at=now - 3600, ttl=60.0, invalid_at=now - 1)
    assert plane._is_recallable_entry(expired, now=now) is False
    legacy = MemoryEntry(key="legacy", value="x", created_at=now - 3600, ttl=60.0)
    assert plane._is_recallable_entry(legacy, now=now) is False
