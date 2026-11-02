"""The orphan-entity sweep script counts without writing and deletes only with --execute (item A4r)."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import time
import uuid
from pathlib import Path

import pytest

from bilinc.core.entities import Entity, EntityMention
from bilinc.storage.postgres import PostgresBackend

DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set")


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "sweep_pg_orphan_entities.py"
    spec = importlib.util.spec_from_file_location("sweep_pg_orphan_entities", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_count_only_writes_nothing_and_execute_deletes_old_orphans():
    sweep = _script()

    async def go():
        import asyncpg

        backend = PostgresBackend(dsn=DSN, schema=f"bilinc_p_{uuid.uuid4().hex}")
        await backend.init()
        schema = backend.schema
        try:
            await backend.save_entity(Entity(canonical_name="Old Orphan"))
            await backend.save_entity(Entity(canonical_name="Fresh Orphan"))
            kept = Entity(canonical_name="Mentioned")
            await backend.save_entity(kept)
            await backend.save_entity_mention(EntityMention(entity_id=kept.id, memory_key="k", mention_text="Mentioned"))
            await backend.pool.execute(
                "UPDATE entities SET updated_at = $1 WHERE canonical_name IN ('Old Orphan', 'Mentioned')", time.time() - 7200)

            conn = await asyncpg.connect(DSN)
            try:
                async def snapshot():
                    return (
                        await conn.fetchval(f'SELECT count(*) FROM "{schema}".entities'),
                        await conn.fetchval(f'SELECT count(*) FROM "{schema}".entity_mentions'),
                        await conn.fetchval(f'SELECT max(version) FROM "{schema}".schema_version'),
                    )

                before = await snapshot()
                counted = await sweep.sweep_schema(conn, schema, execute=False)
                after_count = await snapshot()
                executed = await sweep.sweep_schema(conn, schema, execute=True)
                after_execute = await snapshot()
                again = await sweep.sweep_schema(conn, schema, execute=True)

                empty = f"bilinc_p_{uuid.uuid4().hex}"
                await conn.execute(f'CREATE SCHEMA "{empty}"')
                try:
                    skipped = await sweep.sweep_schema(conn, empty, execute=True)
                finally:
                    await conn.execute(f'DROP SCHEMA "{empty}" CASCADE')
            finally:
                await conn.close()
            return before, counted, after_count, executed, after_execute, again, skipped
        finally:
            await backend.close()
            conn = await asyncpg.connect(DSN)
            try:
                await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            finally:
                await conn.close()

    before, counted, after_count, executed, after_execute, again, skipped = asyncio.new_event_loop().run_until_complete(go())
    assert counted["orphans"] == 1 and "deleted" not in counted
    assert after_count == before  # count-only: no row, mention or schema_version changed
    assert executed["deleted"] == 1
    assert after_execute[0] == before[0] - 1 and after_execute[1:] == before[1:]  # only the old orphan went
    assert again["orphans"] == 0 and again["deleted"] == 0
    assert skipped["status"] == "skipped_missing_tables"
