import asyncio

from bilinc.core.models import MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.integrations.distill import commit_distilled
from bilinc.storage.sqlite import SQLiteBackend


def test_distilled_facts_recall_with_sources(tmp_path):
    async def extract(text):
        return ["The user's budget tracker uses Flask 2.3.1.", "The user stores data in SQLite 3.39."]

    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "d.sqlite")), enable_verification=False, enable_audit=False)
        await plane.init()
        keys = await commit_distilled(plane, "t001", "user: I'm on Flask 2.3.1 with SQLite 3.39.\nassistant: Great.",
                                      extract, timestamp="2024-03-15T12:00:00+00:00")
        out = await plane.recall_reflective("Which Flask version?", limit=5, memory_types=[MemoryType.SEMANTIC],
                                            expand_sources=True)
        return keys, out["results"]

    keys, results = asyncio.run(go())
    assert keys == ["t001#f00", "t001#f01"]
    assert results and all(r["key"].startswith("t001#f") for r in results)
    top = results[0]
    assert top["key"] == "t001#f00"
    assert top["source"]["key"] == "t001" and "Flask 2.3.1" in top["source"]["value"]


def test_recall_without_expand_sources_is_unchanged(tmp_path):
    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "e.sqlite")), enable_verification=False, enable_audit=False)
        await plane.init()
        await commit_distilled(plane, "t002", "user: Deadline is May 14.", lambda t: ["The deadline is May 14."])
        return (await plane.recall_reflective("deadline", limit=5))["results"]

    assert all("source" not in r for r in asyncio.run(go()))


def test_recommitting_a_source_with_fewer_facts_forgets_the_extra_ones(tmp_path):
    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "f.sqlite")), enable_verification=False, enable_audit=False)
        await plane.init()
        await commit_distilled(plane, "t3", "v1", lambda t: ["a fact", "b fact", "c fact"])
        keys = await commit_distilled(plane, "t3", "v2", lambda t: ["only fact"])
        left = [k for k in ("t3#f00", "t3#f01", "t3#f02") if await plane.backend.load(k) is not None]
        return keys, left

    keys, left = asyncio.run(go())
    assert keys == ["t3#f00"] and left == ["t3#f00"]


def test_string_extractor_result_is_one_fact(tmp_path):
    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "g.sqlite")), enable_verification=False, enable_audit=False)
        await plane.init()
        return await commit_distilled(plane, "t4", "x", lambda t: "a single fact")

    assert asyncio.run(go()) == ["t4#f00"]


def _source_case(tmp_path, name, mutate, query_timestamp=None):
    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / name)), enable_verification=False, enable_audit=False)
        await plane.init()
        await commit_distilled(plane, "s1", "user: The launch date is May 14.", lambda t: ["The launch date is May 14."],
                               timestamp="2024-05-01T12:00:00+00:00")
        await mutate(plane)
        out = await plane.recall_reflective("When is the launch date?", limit=5, memory_types=[MemoryType.SEMANTIC],
                                            expand_sources=True, query_timestamp=query_timestamp)
        return [r for r in out["results"] if r["key"] == "s1#f00"]

    return asyncio.run(go())


async def _noop(plane):
    return None


def test_forgotten_source_is_not_attached(tmp_path):
    async def forget_source(plane):
        await plane.forget("s1")

    hits = _source_case(tmp_path, "h.sqlite", forget_source)
    assert hits and "source" not in hits[0]


def test_invalidated_source_is_not_attached(tmp_path):
    async def invalidate(plane):
        entry = await plane.backend.load("s1")
        entry.superseded_by = "s1-v2"  # replaced by a newer version
        await plane.backend.restore(entry)

    hits = _source_case(tmp_path, "i.sqlite", invalidate)
    assert hits and "source" not in hits[0]
    for unparseable in ("", "garbage"):  # recall treats these as a current recall, and so do sources
        hits = _source_case(tmp_path, f"i{len(unparseable)}.sqlite", invalidate, query_timestamp=unparseable)
        assert hits and "source" not in hits[0]


def test_source_after_the_as_of_time_is_not_attached(tmp_path):
    async def move_source_later(plane):
        entry = await plane.backend.load("s1")
        entry.metadata = {**entry.metadata, "source_timestamp": "2024-06-01T12:00:00+00:00"}
        await plane.backend.restore(entry)

    hits = _source_case(tmp_path, "j.sqlite", move_source_later, query_timestamp="2024-05-10T00:00:00+00:00")
    assert hits and "source" not in hits[0]


def test_visible_source_is_attached_for_as_of_recall(tmp_path):
    hits = _source_case(tmp_path, "k.sqlite", _noop, query_timestamp="2024-05-10T00:00:00+00:00")
    assert hits and hits[0]["source"]["key"] == "s1"


def test_failed_fact_write_is_cleaned_up_by_a_retry(tmp_path):
    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "h.sqlite")), enable_verification=False, enable_audit=False)
        await plane.init()
        await commit_distilled(plane, "t5", "v1", lambda t: ["one fact"])
        real_commit = plane.commit

        async def failing(key, *args, **kwargs):
            if key == "t5#f03":
                raise RuntimeError("backend write failed")
            return await real_commit(key, *args, **kwargs)

        plane.commit = failing
        try:
            await commit_distilled(plane, "t5", "v2", lambda t: ["a", "b", "c", "d", "e"])
        except RuntimeError:
            pass
        plane.commit = real_commit
        await commit_distilled(plane, "t5", "v3", lambda t: ["only fact"])
        return [k for k in (f"t5#f{i:02d}" for i in range(5)) if await plane.backend.load(k) is not None]

    assert asyncio.run(go()) == ["t5#f00"]


def test_source_key_in_the_fact_key_space_is_rejected(tmp_path):
    import pytest

    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "i.sqlite")), enable_verification=False, enable_audit=False)
        await plane.init()
        await commit_distilled(plane, "chat#f00", "x", lambda t: ["a fact"])

    with pytest.raises(ValueError):
        asyncio.run(go())
