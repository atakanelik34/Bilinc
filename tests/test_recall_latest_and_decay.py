"""Regression tests for latest-intent recall and decay over text timestamps."""

import time

import pytest

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.stateplane import StatePlane, entry_epoch
from bilinc.jobs.definitions import decay_pass_job
from bilinc.storage.sqlite import SQLiteBackend


async def _plane(tmp_path, name):
    backend = SQLiteBackend(str(tmp_path / name))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    return plane, backend


async def _seed_release_history(backend):
    now = time.time()
    entries = [
        (
            "project:clawifi:status",
            "Clawifi status: live release version v0.7.0 on PyPI.",
            "2026-05-19T09:00:00+00:00",
        ),
        (
            "project:clawifi:release-1.2.0-live:2026-09-20",
            "Clawifi 1.2.0 is the live release version published to PyPI.",
            now - 86400 * 26,
        ),
        (
            "project:clawifi:release-1.3.0-live:2026-10-13",
            "Clawifi 1.3.0 shipped to PyPI and is now live.",
            now - 86400 * 3,
        ),
    ]
    for key, value, stamp in entries:
        await backend.restore(
            MemoryEntry(
                key=key,
                value=value,
                memory_type=MemoryType.SEMANTIC,
                importance=0.95,
                created_at=stamp,
                updated_at=stamp,
            )
        )
    noise = [
        ("project:clawifi:roadmap", "Clawifi roadmap lists the next release candidates."),
        ("project:docly:release-2.0.0-live", "Docly 2.0.0 live release version is out."),
        ("project:bilinc:release-2.3.9", "Bilinc release version 2.3.9 is live on PyPI."),
        ("gtm:clawifi:launch", "Clawifi launch notes and live demo plans."),
    ]
    for key, value in noise:
        await backend.restore(
            MemoryEntry(
                key=key,
                value=value,
                memory_type=MemoryType.SEMANTIC,
                created_at=now - 86400 * 40,
                updated_at=now - 86400 * 40,
            )
        )


def test_entry_epoch_accepts_floats_iso_text_and_garbage():
    assert entry_epoch(1700000000.0) == 1700000000.0
    assert entry_epoch("1700000000") == 1700000000.0
    assert entry_epoch("2026-05-19T00:00:00Z") == pytest.approx(1779148800.0)
    assert entry_epoch("2026-05-19 00:00:00") == pytest.approx(1779148800.0)
    assert entry_epoch("") is None
    assert entry_epoch(None) is None
    assert entry_epoch(0.0) is None
    assert entry_epoch("not a date") is None


@pytest.mark.asyncio
async def test_latest_query_returns_newest_release_entry(tmp_path):
    plane, backend = await _plane(tmp_path, "latest-release.sqlite")
    await _seed_release_history(backend)
    newest = "project:clawifi:release-1.3.0-live:2026-10-13"

    for query in (
        "Clawifi latest live release version",
        "Clawifi current live release version",
        "Clawifi guncel live release version",
    ):
        results = await plane.recall_intelligent(query, limit=5)
        assert results[0]["key"] == newest, (query, [r["key"] for r in results])

    smart = await plane.recall_reflective("Clawifi latest live release version", limit=5)
    assert smart["results"][0]["key"] == newest

    # Older evidence is reordered, not deleted.
    keys = {r["key"] for r in await plane.recall_intelligent("Clawifi latest live release version", limit=10)}
    assert "project:clawifi:release-1.2.0-live:2026-09-20" in keys


@pytest.mark.asyncio
async def test_non_latest_query_keeps_relevance_order(tmp_path):
    plane, backend = await _plane(tmp_path, "plain-release.sqlite")
    await _seed_release_history(backend)

    results = await plane.recall_intelligent("Clawifi 1.2.0 live release version", limit=5)

    assert results[0]["key"] == "project:clawifi:release-1.2.0-live:2026-09-20"


@pytest.mark.asyncio
async def test_latest_boost_ignores_other_products(tmp_path):
    plane, backend = await _plane(tmp_path, "other-product.sqlite")
    await _seed_release_history(backend)
    now = time.time()
    await backend.restore(
        MemoryEntry(
            key="project:docly:release-2.1.0-live:2026-10-15",
            value="Docly 2.1.0 live release version is out.",
            memory_type=MemoryType.SEMANTIC,
            created_at=now - 3600,
            updated_at=now - 3600,
        )
    )

    results = await plane.recall_intelligent("Clawifi latest live release version", limit=5)

    assert results[0]["key"] == "project:clawifi:release-1.3.0-live:2026-10-13"


@pytest.mark.asyncio
async def test_decay_pass_handles_text_updated_at_without_last_accessed(tmp_path):
    plane, backend = await _plane(tmp_path, "decay-text.sqlite")
    entry = MemoryEntry(
        key="import:text-ts",
        value="imported with ISO timestamps",
        memory_type=MemoryType.SEMANTIC,
        created_at="2026-05-19T09:00:00+00:00",
        updated_at="2026-05-19T09:00:00+00:00",
        last_accessed=0.0,
    )
    entry.current_strength = 1.0
    await backend.restore(entry)
    raw = await backend.load("import:text-ts")
    assert isinstance(raw.updated_at, str)

    now = entry_epoch("2026-10-16T00:00:00+00:00")
    report = await plane.apply_decay_pass(now=now, prune=False)

    assert report["scanned"] == 1
    assert report["updated"] == 1
    assert report["pruned"] == 0
    refreshed = await backend.load("import:text-ts")
    assert refreshed.current_strength < 1.0
    # The decay pass must not rewrite the write time that recall uses for recency.
    assert entry_epoch(refreshed.updated_at) == entry_epoch("2026-05-19T09:00:00+00:00")
    assert refreshed.metadata["decay"]["last_run"] == now


@pytest.mark.asyncio
async def test_scheduled_decay_job_never_prunes(tmp_path):
    plane, backend = await _plane(tmp_path, "decay-no-prune.sqlite")
    entry = MemoryEntry(
        key="ancient:weak",
        value="very old weak working memory",
        memory_type=MemoryType.WORKING,
        importance=0.0,
        created_at=time.time() - 86400 * 3650,
        updated_at=time.time() - 86400 * 3650,
    )
    entry.current_strength = 0.01
    await backend.restore(entry)

    report = await decay_pass_job(plane)

    assert report["pruned"] == 0
    assert await backend.load("ancient:weak") is not None


@pytest.mark.asyncio
async def test_latest_order_survives_a_decay_pass(tmp_path):
    plane, backend = await _plane(tmp_path, "latest-after-decay.sqlite")
    await _seed_release_history(backend)
    await plane.apply_decay_pass(prune=False)

    results = await plane.recall_intelligent("Clawifi latest live release version", limit=5)

    assert results[0]["key"] == "project:clawifi:release-1.3.0-live:2026-10-13"


@pytest.mark.asyncio
async def test_repeated_decay_passes_do_not_compound(tmp_path):
    plane, backend = await _plane(tmp_path, "decay-twice.sqlite")
    now = time.time()
    entry = MemoryEntry(key="note:x", value="x", memory_type=MemoryType.SEMANTIC,
                        created_at=now - 86400 * 10, updated_at=now - 86400 * 10, last_accessed=0.0)
    entry.current_strength = 1.0
    await backend.restore(entry)
    await plane.apply_decay_pass(now=now, prune=False)
    once = (await backend.load("note:x")).current_strength
    await plane.apply_decay_pass(now=now, prune=False)
    assert (await backend.load("note:x")).current_strength == once


@pytest.mark.asyncio
async def test_english_son_is_not_a_latest_marker(tmp_path):
    plane, backend = await _plane(tmp_path, "family.sqlite")
    now = time.time()
    for key, value, age in (("family:son:name", "My son's name is Deniz.", 86400 * 30),
                            ("family:daughter:name", "My daughter's name is Ada.", 3600)):
        await backend.restore(MemoryEntry(key=key, value=value, memory_type=MemoryType.SEMANTIC,
                                          created_at=now - age, updated_at=now - age))

    keys = [r["key"] for r in await plane.recall_intelligent("what is my son's name", limit=5)]

    assert "family:son:name" in keys
    assert keys[0] == "family:son:name"
