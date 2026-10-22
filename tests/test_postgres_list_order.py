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
