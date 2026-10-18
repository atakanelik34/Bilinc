import asyncio

from bilinc.core.models import MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend


def _plane(tmp_path, name):
    return StatePlane(backend=SQLiteBackend(str(tmp_path / name)), enable_verification=False, enable_audit=False)


def test_rewriting_one_memory_keeps_shared_entities_and_drops_orphans(tmp_path):
    async def go():
        plane = _plane(tmp_path, "e.sqlite")
        await plane.init()
        await plane.commit("a", "Ada Lovelace met Charles Babbage in London.", MemoryType.SEMANTIC)
        await plane.commit("b", "Charles Babbage designed the Analytical Engine.", MemoryType.SEMANTIC)
        conn = plane.backend._get_conn()
        before = {r[0] for r in conn.execute("SELECT canonical_name FROM entities")}
        await plane.backend.delete_entity_mentions_for_memory_key("a")
        after = {r[0] for r in conn.execute("SELECT canonical_name FROM entities")}
        mentioned = {r[0] for r in conn.execute(
            "SELECT e.canonical_name FROM entities e JOIN entity_mentions m ON m.entity_id = e.id")}
        return before, after, mentioned

    before, after, mentioned = asyncio.run(go())
    assert after == mentioned  # no orphans left, nothing still mentioned was removed
    assert after <= before


def test_writes_prune_only_touched_entities(tmp_path, monkeypatch):
    """Deterministic guard for the quadratic regression: a write never asks for a full sweep."""
    calls = []
    original = SQLiteBackend._prune_orphan_entities

    def spy(self, conn, entity_ids=None):
        calls.append(entity_ids)
        return original(self, conn, entity_ids)

    monkeypatch.setattr(SQLiteBackend, "_prune_orphan_entities", spy)

    async def go():
        plane = _plane(tmp_path, "s.sqlite")
        await plane.init()
        calls.clear()  # opening a store runs one full sweep on purpose; writes after it must not
        for n in range(30):
            await plane.commit(f"m{n}", f"Project Orion{n} uses Postgres{n} in Berlin{n}.", MemoryType.SEMANTIC)
            await plane.commit(f"m{n}", f"Project Orion{n} moved to Redis{n} in Paris{n}.", MemoryType.SEMANTIC)
        await plane.backend.delete("m0")

    asyncio.run(go())
    assert calls and all(ids is not None for ids in calls)


def test_sweep_orphan_entities_clears_leftovers(tmp_path):
    async def go():
        plane = _plane(tmp_path, "w.sqlite")
        await plane.init()
        await plane.commit("a", "Grace Hopper wrote COBOL.", MemoryType.SEMANTIC)
        conn = plane.backend._get_conn()
        conn.execute("DELETE FROM entity_mentions")  # simulate orphans left by an older version
        conn.commit()
        removed = await plane.backend.sweep_orphan_entities()
        left = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        return removed, left

    removed, left = asyncio.run(go())
    assert removed > 0 and left == 0
