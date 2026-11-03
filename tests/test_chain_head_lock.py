"""A8a: appends to the Postgres audit and event hash chains are serialized in the database.

Needs a disposable PostgreSQL (BILINC_TEST_POSTGRES_DSN). Every writer below has its own
connection, like a second worker would; nothing shares a connection or a pool.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid

import pytest

from bilinc.core import postgres_chain_lock
from bilinc.core.audit import OpType, verify_chain
from bilinc.core.event_ledger import compute_event_hash
from bilinc.core.postgres_audit import PostgresAuditTrail
from bilinc.core.postgres_audit_sync import SyncPostgresAuditTrail
from bilinc.storage import postgres as postgres_storage
from bilinc.storage.postgres import PostgresBackend
from bilinc.storage.postgres_tenancy import search_path_setting

DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set")

SITES = ["audit_sync", "audit_async", "events"]
CHAIN_OF = {"audit_sync": "audit_log", "audit_async": "audit_log", "events": "memory_events"}


def _new_schema() -> str:
    return "bilinc_p_" + uuid.uuid4().hex


class Site:
    """One writer: its own connection to the chain under test."""

    def __init__(self, kind: str, schema: str):
        self.kind, self.schema = kind, schema
        self.chain = CHAIN_OF[kind]
        self.writer = None

    async def open(self):
        if self.kind == "audit_sync":
            self.writer = SyncPostgresAuditTrail(DSN, schema=self.schema)
        elif self.kind == "audit_async":
            self.writer = PostgresAuditTrail(DSN)  # public schema: this twin has no tenant schema
        else:
            self.writer = PostgresBackend(DSN, schema=self.schema)
        await self.writer.init()
        return self

    async def close(self):
        await self.writer.close()

    async def append(self, n: int):
        key = f"k{n}"
        if self.kind == "audit_sync":
            return await asyncio.to_thread(self.writer.log, OpType.CREATE, key, None, {"n": n})
        if self.kind == "audit_async":
            return await self.writer.log(OpType.CREATE, key, None, {"n": n})
        return await self.writer.append_memory_event(operation="commit", subject="s", memory_key=key)

    async def append_that_fails_after_the_lock(self, monkeypatch):
        if self.kind == "events":
            def boom(**_kwargs):
                raise RuntimeError("injected")
            monkeypatch.setattr(postgres_storage, "create_memory_event", boom)
            try:
                await self.writer.append_memory_event(operation="commit", subject="s")
            finally:
                monkeypatch.undo()
            return
        # a NOT NULL violation at the INSERT, after the head was read
        if self.kind == "audit_sync":
            await asyncio.to_thread(self.writer.log, OpType.CREATE, None)
        else:
            await self.writer.log(OpType.CREATE, None)

    @property
    def lock_schema(self) -> str:
        return "public" if self.kind == "audit_async" else self.schema


async def _connect(schema: str):
    import asyncpg

    if schema == "public":
        return await asyncpg.connect(DSN)
    return await asyncpg.connect(DSN, server_settings={"search_path": search_path_setting(schema)})


async def _holder(schema: str, chain: str):
    """A transaction that holds the chain's lock, the way a second writer would."""
    conn = await _connect(schema)
    tx = conn.transaction()
    await tx.start()
    await conn.execute(postgres_chain_lock.lock_sql(chain))
    return conn, tx


async def _waiting_appenders() -> int:
    import asyncpg

    conn = await asyncpg.connect(DSN)
    try:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
        )
    finally:
        await conn.close()


async def _audit_rows(site: Site, after_id: int = 0):
    conn = await _connect(site.lock_schema)
    try:
        return [dict(r) for r in await conn.fetch("SELECT * FROM audit_log WHERE id > $1 ORDER BY id", after_id)]
    finally:
        await conn.close()


async def _max_audit_id(site: Site) -> int:
    rows = await _audit_rows(site)
    return rows[-1]["id"] if rows else 0


@pytest.fixture
def schema():
    return _new_schema()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", SITES)
async def test_an_append_waits_for_the_chain_lock_and_then_completes(kind, schema):
    site = await Site(kind, schema).open()
    try:
        conn, tx = await _holder(site.lock_schema, site.chain)
        task = asyncio.create_task(site.append(0))
        await asyncio.sleep(0.5)
        assert not task.done()
        assert await _waiting_appenders() >= 1  # waiting on the lock, not just slow
        await tx.commit()
        await conn.close()
        await asyncio.wait_for(task, 10)
    finally:
        await site.close()


@pytest.mark.asyncio
async def test_the_other_chain_and_the_other_tenant_are_not_blocked(schema):
    audit = await Site("audit_sync", schema).open()
    events = await Site("events", schema).open()
    other = await Site("audit_sync", _new_schema()).open()
    try:
        conn, tx = await _holder(schema, "audit_log")
        await asyncio.wait_for(events.append(0), 5)
        await asyncio.wait_for(other.append(0), 5)
        await tx.rollback()
        await conn.close()
        await asyncio.wait_for(audit.append(0), 5)
    finally:
        for s in (audit, events, other):
            await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", SITES)
async def test_a_lock_timeout_fails_the_append_and_leaves_the_chain_alone(kind, schema, monkeypatch):
    site = await Site(kind, schema).open()
    try:
        await site.append(0)
        monkeypatch.setattr(postgres_chain_lock, "CHAIN_LOCK_TIMEOUT", "200ms")
        conn, tx = await _holder(site.lock_schema, site.chain)
        with pytest.raises(Exception, match="(?i)lock timeout|lock_not_available|could not obtain"):
            await asyncio.wait_for(site.append(1), 10)
        await tx.rollback()
        await conn.close()
        await asyncio.wait_for(site.append(2), 10)
    finally:
        await site.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", SITES)
async def test_a_failure_after_the_lock_releases_it(kind, schema, monkeypatch):
    site = await Site(kind, schema).open()
    try:
        await site.append(0)
        with pytest.raises(Exception):
            await site.append_that_fails_after_the_lock(monkeypatch)
        await asyncio.wait_for(site.append(1), 5)  # not blocked by a leaked lock
    finally:
        await site.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", SITES)
async def test_a_closed_lock_holder_releases_the_lock(kind, schema):
    site = await Site(kind, schema).open()
    try:
        conn, _tx = await _holder(site.lock_schema, site.chain)
        task = asyncio.create_task(site.append(0))
        await asyncio.sleep(0.3)
        assert not task.done()
        conn.terminate()  # the holder dies without committing
        await asyncio.wait_for(task, 10)
    finally:
        await site.close()


# ---- many independent writers --------------------------------------------------------------

WRITERS, PER_WRITER = 5, 5


async def _hammer(kind: str, schema: str):
    sites = [await Site(kind, schema).open() for _ in range(WRITERS)]
    async def run(i, s):  # one writer = one connection, used by one caller at a time
        for j in range(PER_WRITER):
            await s.append(i * PER_WRITER + j)

    try:
        await asyncio.gather(*(run(i, s) for i, s in enumerate(sites)))
    finally:
        for s in sites:
            await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["audit_sync", "audit_async"])
async def test_concurrent_audit_writers_keep_one_linear_chain(kind, schema):
    probe = await Site(kind, schema).open()
    try:
        start = await _max_audit_id(probe)
        await _hammer(kind, schema)
        rows = await _audit_rows(probe, start)
    finally:
        await probe.close()
    assert len(rows) == WRITERS * PER_WRITER
    assert len({r["prev_root"] for r in rows}) == len(rows)           # nobody linked to the same head
    for earlier, later in zip(rows, rows[1:]):
        assert later["prev_root"] == earlier["root_hash"]
    if kind == "audit_sync":
        assert verify_chain(rows)["valid"] is True


@pytest.mark.asyncio
async def test_concurrent_event_writers_keep_one_linear_chain(schema):
    await _hammer("events", schema)
    reader = PostgresBackend(DSN, schema=schema)
    await reader.init()
    try:
        events = await reader.list_memory_events()
    finally:
        await reader.close()
    _assert_event_chain(events, WRITERS * PER_WRITER)


def _assert_event_chain(events, expected_count):
    """Walk the links from the genesis row; independent of ``time``."""
    assert len(events) == expected_count
    by_prev = {}
    for e in events:
        assert e.prev_event_hash not in by_prev, "two events link to the same predecessor"
        by_prev[e.prev_event_hash] = e
        assert compute_event_hash(e) == e.event_hash
    walked, link = [], None
    while link in by_prev:
        e = by_prev[link]
        walked.append(e)
        link = e.event_hash
    assert len(walked) == expected_count, "the chain forked or has a gap"
    assert walked[-1].time == max(e.time for e in events)
    assert all(a.time < b.time for a, b in zip(walked, walked[1:]))


@pytest.mark.asyncio
async def test_a_clock_that_steps_back_does_not_fork_the_event_chain(schema, monkeypatch):
    from bilinc.core import event_ledger

    backend = PostgresBackend(DSN, schema=schema)
    await backend.init()
    try:
        now = time.time()
        clock = iter([now, now - 3600.0, now - 7200.0, now - 7200.0])
        monkeypatch.setattr(event_ledger.time, "time", lambda: next(clock))
        for n in range(4):
            await backend.append_memory_event(operation="commit", subject="s", memory_key=f"k{n}")
        monkeypatch.undo()
        events = await backend.list_memory_events()
    finally:
        await backend.close()
    _assert_event_chain(events, 4)
