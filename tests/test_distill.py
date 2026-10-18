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
