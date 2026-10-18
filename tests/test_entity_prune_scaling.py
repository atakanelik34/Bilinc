import asyncio
import time

from bilinc.core.models import MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend


def test_rewriting_one_memory_keeps_shared_entities_and_drops_orphans(tmp_path):
    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "e.sqlite")), enable_verification=False, enable_audit=False)
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


def test_commit_cost_does_not_grow_with_store_size(tmp_path):
    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "s.sqlite")), enable_verification=False, enable_audit=False)
        await plane.init()
        times = []
        for batch in range(3):
            t0 = time.perf_counter()
            for i in range(400):
                n = batch * 400 + i
                await plane.commit(f"m{n}", f"Project Orion{n} uses Postgres{n} and Redis{n} in Berlin{n}.", MemoryType.SEMANTIC)
            times.append(time.perf_counter() - t0)
        return times

    first, _, last = asyncio.run(go())
    assert last < first * 2.5  # was quadratic: every write swept all entities and mentions
