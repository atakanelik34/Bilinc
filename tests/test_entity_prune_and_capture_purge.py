"""Forget, rewrite and purge leave no orphan entities and no capture rows that name the key (item A4r).

Every scenario runs on SQLite; the Postgres variant runs only when BILINC_TEST_POSTGRES_DSN is set.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid

import pytest

from bilinc.core.entities import Entity, EntityMention
from bilinc.core.models import MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.eval.capture import EvalCaptureRow
from bilinc.storage.postgres import PostgresBackend
from bilinc.storage.sqlite import SQLiteBackend

DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set"))]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _open(kind, tmp_path):
    if kind == "sqlite":
        backend = SQLiteBackend(str(tmp_path / f"{uuid.uuid4().hex}.sqlite"))
    else:
        backend = PostgresBackend(dsn=DSN, schema=f"bilinc_p_{uuid.uuid4().hex}")
    await backend.init()
    return backend


async def _close(kind, backend):
    if kind == "sqlite":
        await backend.close()
        return
    import asyncpg

    await backend.close()
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{backend.schema}" CASCADE')
    finally:
        await conn.close()


async def _all(kind, backend, sql):
    if kind == "sqlite":
        return [tuple(r) for r in backend._get_conn().execute(sql).fetchall()]
    return [tuple(r.values()) for r in await backend.pool.fetch(sql)]


async def _entity_names(kind, backend):
    return {row[0] for row in await _all(kind, backend, "SELECT canonical_name FROM entities")}


async def _plane(kind, tmp_path):
    backend = await _open(kind, tmp_path)
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    return plane, backend


def _row(query="q", keys=(), detail=None):
    return EvalCaptureRow(
        schema_version=1, tool_name="recall", query=query, retrieved_keys=list(keys),
        retrieved_scores=[0.5] * len(keys), memory_types=["semantic"] * len(keys),
        latency_ms=1, created_at=time.time(), detail=detail or {},
    )


@pytest.mark.parametrize("kind", BACKENDS)
def test_forget_right_after_write_prunes_entities_only_it_mentioned(kind, tmp_path):
    async def go():
        plane, backend = await _plane(kind, tmp_path)
        try:
            await plane.commit("a", "Ada Lovelace met Charles Babbage in London.", MemoryType.SEMANTIC)
            await plane.commit("b", "Charles Babbage designed the Analytical Engine.", MemoryType.SEMANTIC)
            before = await _entity_names(kind, backend)
            await plane.forget("a")  # no sleep: a recency guard in the prune would hide the leak
            after = await _entity_names(kind, backend)
            mentioned = {r[0] for r in await _all(
                kind, backend,
                "SELECT e.canonical_name FROM entities e JOIN entity_mentions m ON m.entity_id = e.id")}
            return before, after, mentioned
        finally:
            await _close(kind, backend)

    before, after, mentioned = _run(go())
    assert any("Babbage" in name for name in after)  # still mentioned by "b"
    assert after == mentioned  # no orphan left
    assert after < before  # the entities only "a" mentioned are gone


@pytest.mark.parametrize("kind", BACKENDS)
def test_rewrite_that_drops_an_entity_prunes_it_right_away(kind, tmp_path):
    async def go():
        plane, backend = await _plane(kind, tmp_path)
        try:
            await plane.commit("a", "Ada Lovelace met Charles Babbage in London.", MemoryType.SEMANTIC)
            await plane.commit("a", "The weather in Paris was mild.", MemoryType.SEMANTIC)
            names = await _entity_names(kind, backend)
            mentioned = {r[0] for r in await _all(
                kind, backend,
                "SELECT e.canonical_name FROM entities e JOIN entity_mentions m ON m.entity_id = e.id")}
            return names, mentioned
        finally:
            await _close(kind, backend)

    names, mentioned = _run(go())
    assert names == mentioned
    assert not any("Babbage" in name for name in names)


@pytest.mark.parametrize("kind", BACKENDS)
def test_a_rewrite_that_keeps_an_entity_keeps_its_row(kind, tmp_path):
    async def go():
        plane, backend = await _plane(kind, tmp_path)
        try:
            await plane.commit("a", "Charles Babbage designed the Analytical Engine.", MemoryType.SEMANTIC)
            ids = {r[0] for r in await _all(kind, backend, "SELECT id FROM entities WHERE canonical_name LIKE '%Babbage%'")}
            await plane.commit("a", "Charles Babbage lived in London.", MemoryType.SEMANTIC)
            ids_after = {r[0] for r in await _all(kind, backend, "SELECT id FROM entities WHERE canonical_name LIKE '%Babbage%'")}
            return ids, ids_after
        finally:
            await _close(kind, backend)

    ids, ids_after = _run(go())
    assert ids and ids == ids_after


@pytest.mark.parametrize("kind", BACKENDS)
def test_a_mention_that_moves_prunes_the_old_entity(kind, tmp_path):
    async def go():
        backend = await _open(kind, tmp_path)
        try:
            old, new = Entity(canonical_name="Old Name"), Entity(canonical_name="New Name")
            await backend.save_entity(old)
            await backend.save_entity(new)
            mention = EntityMention(entity_id=old.id, memory_key="k", mention_text="Old Name")
            await backend.save_entity_mention(mention)
            mention.entity_id = new.id
            await backend.save_entity_mention(mention)
            return await _entity_names(kind, backend)
        finally:
            await _close(kind, backend)

    names = _run(go())
    assert "Old Name" not in names and "New Name" in names


@pytest.mark.parametrize("kind", BACKENDS)
def test_prune_false_refreshes_updated_at_and_prunes_nothing(kind, tmp_path):
    async def go():
        backend = await _open(kind, tmp_path)
        try:
            entity = Entity(canonical_name="Only Mention", updated_at=1.0)
            await backend.save_entity(entity)
            await backend.save_entity_mention(EntityMention(entity_id=entity.id, memory_key="k", mention_text="Only Mention"))
            await backend.delete_entity_mentions_for_memory_key("k", prune=False)
            rows = await _all(kind, backend, "SELECT canonical_name, updated_at FROM entities")
            return rows
        finally:
            await _close(kind, backend)

    rows = _run(go())
    assert len(rows) == 1 and rows[0][1] > 1000.0


@pytest.mark.parametrize("kind", BACKENDS)
def test_init_deletes_no_old_orphan_and_the_sweep_is_opt_in(kind, tmp_path):
    async def go():
        backend = await _open(kind, tmp_path)
        try:
            await backend.save_entity(Entity(canonical_name="Old Orphan"))
            await backend.save_entity(Entity(canonical_name="Fresh Orphan"))
            old = time.time() - 7200  # save_entity stamps "now" on SQLite, so age the row by hand
            if kind == "sqlite":
                backend._get_conn().execute("UPDATE entities SET updated_at = ? WHERE canonical_name = 'Old Orphan'", (old,))
                backend._get_conn().commit()
            else:
                await backend.pool.execute("UPDATE entities SET updated_at = $1 WHERE canonical_name = 'Old Orphan'", old)
            await backend.init()  # opening again must not delete anything that already exists
            after_init = await _entity_names(kind, backend)
            counted = await backend.sweep_orphan_entities(dry_run=True)
            after_dry = await _entity_names(kind, backend)
            removed = await backend.sweep_orphan_entities()
            after_sweep = await _entity_names(kind, backend)
            again = await backend.sweep_orphan_entities()
            return after_init, counted, after_dry, removed, after_sweep, again
        finally:
            await _close(kind, backend)

    after_init, counted, after_dry, removed, after_sweep, again = _run(go())
    assert {"Old Orphan", "Fresh Orphan"} <= after_init
    assert counted == 1  # only the old one is old enough to count (age guard)
    assert after_dry == after_init  # a dry run deletes nothing
    assert removed == 1 and after_sweep == {"Fresh Orphan"}  # the recent orphan survives
    assert again == 0  # idempotent


@pytest.mark.parametrize("kind", BACKENDS)
def test_purge_eval_candidates_removes_rows_naming_the_key_only(kind, tmp_path):
    async def go():
        backend = await _open(kind, tmp_path)
        try:
            await backend.record_eval_candidate(_row("find it", keys=["secret", "other"]))
            await backend.record_eval_candidate(_row("secret", keys=[], detail={"key": "secret"}))
            await backend.record_eval_candidate(_row("secret", keys=[]))
            await backend.record_eval_candidate(_row("unrelated", keys=["other"], detail={"key": "other"}))
            await backend.record_eval_candidate(_row("quoted the value", keys=[]))  # known limit: never named the key
            removed = await backend.purge_eval_candidates("secret")
            left = sorted(r.query for r in await backend.list_eval_candidates())
            return removed, left
        finally:
            await _close(kind, backend)

    removed, left = _run(go())
    assert removed == 3
    assert left == ["quoted the value", "unrelated"]


@pytest.mark.parametrize("kind", BACKENDS)
def test_purge_eval_candidates_matches_the_scrubbed_key(kind, tmp_path):
    key = "note:" + "x" * 600  # long: stored capped, so scrub_query(key) differs from the key
    _scrubbed_key_case(kind, tmp_path, key)


@pytest.mark.parametrize("kind", BACKENDS)
def test_purge_eval_candidates_matches_a_secret_shaped_key(kind, tmp_path):
    key = "note:sk-abcdefghijklmnop:token"  # token-shaped: stored as "note:[REDACTED]:token"
    _scrubbed_key_case(kind, tmp_path, key)


def _scrubbed_key_case(kind, tmp_path, key):
    from bilinc.eval.capture import scrub_query

    stored = scrub_query(key)
    assert stored != key

    async def go():
        backend = await _open(kind, tmp_path)
        try:
            await backend.record_eval_candidate(_row("x", keys=[stored]))
            removed = await backend.purge_eval_candidates(key)
            return removed, await backend.list_eval_candidates()
        finally:
            await _close(kind, backend)

    removed, left = _run(go())
    assert removed == 1 and left == []


def test_sqlite_purge_eval_candidates_survives_a_malformed_row(tmp_path):
    async def go():
        backend = await _open("sqlite", tmp_path)
        try:
            await backend.record_eval_candidate(_row("good", keys=["secret"]))
            backend._get_conn().execute(
                "INSERT INTO eval_candidates (tool_name, query, retrieved_keys, detail, created_at) "
                "VALUES ('recall', 'bad', 'not json', 'not json', 1.0)")
            backend._get_conn().commit()
            return await backend.purge_eval_candidates("secret")
        finally:
            await _close("sqlite", backend)

    assert _run(go()) == 1
