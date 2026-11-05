"""Update-time ordering of the Postgres memory list (hosted runtime).

Runs only when BILINC_TEST_POSTGRES_DSN points at a disposable PostgreSQL; each
test uses its own tenant schema and drops it afterwards.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from bilinc.core.models import MemoryEntry
from bilinc.storage.postgres import PostgresBackend

DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")


@pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set")
@pytest.mark.parametrize("order", ["newest", "oldest"])
def test_postgres_list_page_orders_by_update_time_and_pages_through_ties(order):
    async def scenario():
        import asyncpg

        backend = PostgresBackend(dsn=DSN, schema=f"bilinc_p_{uuid.uuid4().hex}")
        await backend.init()
        try:
            for key, stamp in (("x", 5.0), ("a", 5.0), ("m", 9.0), ("z", 1.0)):
                await backend.save(MemoryEntry(key=key, value=key))
                async with backend.pool.acquire() as conn:
                    await conn.execute("UPDATE bilinc_entries SET updated_at = $1 WHERE key = $2", stamp, key)
            seen, after = [], None
            while True:
                page = await backend.list_page(
                    order=order,
                    after_key=after[1] if after else None,
                    after_updated=after[0] if after else None,
                    limit=1,
                )
                if not page:
                    return seen
                seen.append(page[0].key)
                after = (page[0].updated_at, page[0].key)
        finally:
            await backend.close()
            conn = await asyncpg.connect(DSN)
            try:
                await conn.execute(f'DROP SCHEMA IF EXISTS "{backend.schema}" CASCADE')
            finally:
                await conn.close()

    expected = ["m", "a", "x", "z"] if order == "newest" else ["z", "a", "x", "m"]
    assert asyncio.new_event_loop().run_until_complete(scenario()) == expected


@pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set")
def test_postgres_exclude_sources_and_updated_at_index():
    async def scenario():
        import asyncpg

        backend = PostgresBackend(dsn=DSN, schema=f"bilinc_p_{uuid.uuid4().hex}")
        await backend.init()
        try:
            rows = [
                ("a", "agent", {}, 10.0),
                ("b", "sample-chat-transcript", {}, 20.0),
                ("c", "", {}, 30.0),
                ("d", "agent", {}, 40.0),
                ("e", "", {"source": "sample-chat-transcript"}, 50.0),
                ("f", "agent", {}, 60.0),
            ]
            for key, source, meta, stamp in rows:
                await backend.restore(MemoryEntry(key=key, value=key, source=source, metadata=meta))
                async with backend.pool.acquire() as conn:
                    await conn.execute("UPDATE bilinc_entries SET updated_at = $1 WHERE key = $2", stamp, key)
            async with backend.pool.acquire() as conn:
                await conn.execute("UPDATE bilinc_entries SET source = NULL WHERE key = 'f'")
            excl = ["sample-chat-transcript"]
            page = await backend.list_page(order="newest", exclude_sources=excl, limit=10)
            assert [e.key for e in page] == ["f", "d", "c", "a"]
            assert await backend.count_filtered(exclude_sources=excl) == 4
            for empty in ([], None):
                assert len(await backend.list_page(exclude_sources=empty, limit=10)) == 6
                assert await backend.count_filtered(exclude_sources=empty) == 6
            async with backend.pool.acquire() as conn:
                found = await conn.fetch(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = $1 AND indexname = 'idx_bilinc_updated_at'",
                    backend.schema,
                )
            assert len(found) == 1
        finally:
            await backend.close()
            conn = await asyncpg.connect(DSN)
            try:
                await conn.execute(f'DROP SCHEMA IF EXISTS "{backend.schema}" CASCADE')
            finally:
                await conn.close()

    asyncio.new_event_loop().run_until_complete(scenario())
