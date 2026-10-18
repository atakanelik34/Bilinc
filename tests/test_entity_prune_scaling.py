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

    def spy(self, conn, entity_ids=None, older_than=0.0):
        calls.append(entity_ids)
        return original(self, conn, entity_ids, older_than)

    monkeypatch.setattr(SQLiteBackend, "_prune_orphan_entities", spy)

    async def go():
        plane = _plane(tmp_path, "s.sqlite")
        await plane.init()
        calls.clear()  # opening a new store runs its one-time sweep; writes after it must not
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
        removed = await plane.backend.sweep_orphan_entities(older_than=0)
        left = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        return removed, left

    removed, left = asyncio.run(go())
    assert removed > 0 and left == 0


def test_rewriting_a_memory_keeps_the_entities_it_still_mentions(tmp_path):
    async def go():
        plane = _plane(tmp_path, "k.sqlite")
        await plane.init()
        await plane.commit("a", "Charles Babbage designed the Analytical Engine.", MemoryType.SEMANTIC)
        conn = plane.backend._get_conn()
        before = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, created_at, aliases FROM entities")}
        entity_id = next(iter(before))
        await plane.backend.add_entity_alias(entity_id, "the engine man")
        await plane.commit("a", "Charles Babbage designed the Analytical Engine.", MemoryType.SEMANTIC)
        row = conn.execute("SELECT created_at, aliases FROM entities WHERE id = ?", (entity_id,)).fetchone()
        return before[entity_id][0], row

    created_before, row = asyncio.run(go())
    assert row is not None and row[0] == created_before and "the engine man" in row[1]


def test_store_open_sweeps_once_and_keeps_recent_entities(tmp_path):
    async def go():
        path = str(tmp_path / "o.sqlite")
        first = SQLiteBackend(path)
        await first.init()
        conn = first._get_conn()
        conn.execute("INSERT INTO entities (id, canonical_name, created_at, updated_at) VALUES ('old', 'Old', 0, 0)")
        conn.execute("INSERT INTO entities (id, canonical_name, created_at, updated_at) VALUES ('new', 'New', strftime('%s','now'), 0)")
        conn.execute("DELETE FROM maintenance")  # as if this database predates the sweep
        conn.commit()
        second = SQLiteBackend(path)
        await second.init()
        after_first_sweep = {r[0] for r in second._get_conn().execute("SELECT id FROM entities")}
        second._get_conn().execute("INSERT INTO entities (id, canonical_name, created_at, updated_at) VALUES ('old2', 'Old2', 0, 0)")
        second._get_conn().commit()
        third = SQLiteBackend(path)
        await third.init()
        after_reopen = {r[0] for r in third._get_conn().execute("SELECT id FROM entities")}
        return after_first_sweep, after_reopen

    after_first_sweep, after_reopen = asyncio.run(go())
    assert after_first_sweep == {"new"}  # the old orphan went; one another process may still link stayed
    assert "old2" in after_reopen  # later opens do not sweep again
