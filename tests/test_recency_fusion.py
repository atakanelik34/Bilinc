import asyncio

from bilinc.core.models import MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend


def _recall(tmp_path, monkeypatch, enabled):
    if enabled:
        monkeypatch.setenv("BILINC_RECALL_RECENCY_FUSION", "1")
    else:
        monkeypatch.delenv("BILINC_RECALL_RECENCY_FUSION", raising=False)

    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / f"r{enabled}.sqlite")), enable_verification=False, enable_audit=False)
        await plane.init()
        for i, (when, score) in enumerate([("2024-03-01", 64), ("2024-03-08", 72), ("2024-03-15", 79), ("2024-04-01", 85)]):
            await plane.commit(f"q{i}", f"The user scored {score}% on the parallelogram law quiz.", MemoryType.EPISODIC,
                               metadata={"source_timestamp": f"{when}T12:00:00+00:00"})
        res = await plane.recall_intelligent("What score did I get on the parallelogram law quiz?", limit=4,
                                             query_timestamp="2024-03-20T00:00:00+00:00")
        return [r["key"] for r in res]

    return asyncio.run(go())


def test_recency_fusion_prefers_the_value_current_at_query_time(tmp_path, monkeypatch):
    keys = _recall(tmp_path, monkeypatch, enabled=True)
    assert "q3" not in keys  # after the query time: filtered as before
    assert keys[0] == "q2"  # most recent value as of 2024-03-20


def test_recency_fusion_is_off_by_default(tmp_path, monkeypatch):
    keys = _recall(tmp_path, monkeypatch, enabled=False)
    assert "q3" not in keys and set(keys) == {"q0", "q1", "q2"}
