"""The opt-in Postgres maintenance script reports by default and only acts on request (item PG-VACUUM)."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import time
import uuid
from pathlib import Path

import pytest

DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set")

WORD_ENTRY = "zxqvaulta"
WORD_CLAIM = "zxqvaultb"
WORD_ENTITY = "zxqvaultc"


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "vacuum_pg_tenants.py"
    spec = importlib.util.spec_from_file_location("vacuum_pg_tenants", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _make_tenant():
    from bilinc.storage.postgres import PostgresBackend

    backend = PostgresBackend(dsn=DSN, schema=f"bilinc_p_{uuid.uuid4().hex}")
    await backend.init()
    schema = backend.schema
    # autovacuum must not run between a step and its assertion
    for table in _script().TABLES:
        await backend.pool.execute(f'ALTER TABLE "{schema}".{table} SET (autovacuum_enabled = false)')
    return backend, schema


async def _drop(backend, schema):
    import asyncpg

    await backend.close()
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        await conn.close()


async def _flush(conn):
    await conn.fetchval("SELECT pg_stat_force_next_flush()")


class _Recorder:
    """Wraps a connection and records every statement text it is asked to run."""

    def __init__(self, conn):
        self._conn = conn
        self.statements = []

    def __getattr__(self, name):
        target = getattr(self._conn, name)
        if name in {"execute", "fetch", "fetchval", "fetchrow"}:
            async def call(sql, *args, **kwargs):
                self.statements.append(" ".join(str(sql).split()))
                return await target(sql, *args, **kwargs)
            return call
        return target


def test_the_table_set_comes_from_the_tenant_tables():
    from bilinc.storage.postgres_tenancy import TENANT_TABLES

    script = _script()
    assert set(script.TABLES) == set(TENANT_TABLES) - {"schema_version"}


def test_the_default_run_writes_nothing():
    script = _script()

    async def go():
        import asyncpg

        backend, schema = await _make_tenant()
        conn = await asyncpg.connect(DSN)
        try:
            async def state():
                sizes = [await conn.fetchval(f"SELECT pg_total_relation_size('\"{schema}\".{t}')") for t in script.TABLES]
                return sizes, await conn.fetchval(f'SELECT max(version) FROM "{schema}".schema_version')

            before = await state()
            recorder = _Recorder(conn)
            record = await script.maintain_schema(recorder, schema)
            return before, await state(), recorder.statements, record
        finally:
            await conn.close()
            await _drop(backend, schema)

    before, after, statements, record = _run(go())
    assert statements and all(s.upper().startswith("SELECT") for s in statements)
    assert before == after
    assert record["status"] == "ok" and set(record["tables"]) == set(script.TABLES)


def test_the_report_shows_dead_tuples_and_a_plain_vacuum_clears_them():
    script = _script()

    async def go():
        import asyncpg

        backend, schema = await _make_tenant()
        conn = await asyncpg.connect(DSN)
        try:
            await conn.execute(
                f'''INSERT INTO "{schema}".entities (id, canonical_name, created_at, updated_at)
                    SELECT 'e' || g, 'name ' || g, 1, 1 FROM generate_series(1, 50) g''')
            await conn.execute(f'UPDATE "{schema}".entities SET updated_at = 2')
            await _flush(conn)
            before = await script.maintain_schema(conn, schema)
            executed = await script.maintain_schema(conn, schema, execute=True)
            await _flush(conn)
            deadline = time.time() + 5
            while True:
                after = await script.maintain_schema(conn, schema)
                if after["tables"]["entities"]["dead_tuples"] == 0 or time.time() > deadline:
                    break
                await asyncio.sleep(0.2)
            return before, executed, after
        finally:
            await conn.close()
            await _drop(backend, schema)

    before, executed, after = _run(go())
    assert before["tables"]["entities"]["dead_tuples"] > 0
    assert executed["status"] == "ok" and all(t["vacuumed"] for t in executed["tables"].values())
    assert after["tables"]["entities"]["dead_tuples"] == 0 and after["tables"]["entities"]["last_vacuum"] is not None


def test_refused_flags_exit_with_code_2_and_run_nothing(monkeypatch, capsys):
    script = _script()
    monkeypatch.setenv("BILINC_POSTGRES_DSN", "postgresql://invalid.invalid/none")  # must never be used
    assert script.main(["--reindex"]) == 2
    assert script.main(["--full"]) == 2
    assert script.main(["--execute", "--reindex", "--full"]) == 2
    assert script.main(["--execute", "--lock-timeout", "0"]) == 2


async def _raw_pages_contain(conn, schema, relation, word):
    blocks = int(await conn.fetchval(f"SELECT pg_relation_size('\"{schema}\".{relation}') / 8192"))
    needle = word.encode()
    for block in range(blocks):
        page = await conn.fetchval(f"SELECT get_raw_page('\"{schema}\".{relation}', {block})")
        if needle in bytes(page):
            return True
    return False


def test_a_reindex_clears_the_words_of_removed_rows_from_every_index():
    script = _script()
    from bilinc.core.models import MemoryEntry, MemoryType

    async def go():
        import asyncpg

        backend, schema = await _make_tenant()
        conn = await asyncpg.connect(DSN)
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pageinspect")
            await backend.save(MemoryEntry(key="k", value="plain value", memory_type=MemoryType.SEMANTIC,
                                           metadata={"note": WORD_ENTRY}))
            await conn.execute(
                f'''INSERT INTO "{schema}".bilinc_claims (id, memory_key, holder, subject, claim, kind, created_at, updated_at)
                    VALUES ('c1', 'k', 'h', '{WORD_CLAIM}', 'claim text', 'fact', 1, 1)''')
            await conn.execute(
                f'''INSERT INTO "{schema}".entities (id, canonical_name, created_at, updated_at)
                    VALUES ('e1', '{WORD_ENTITY}', 1, 1)''')
            checks = [
                ("idx_bilinc_entries_fts", WORD_ENTRY),
                ("idx_bilinc_claims_subject_active", WORD_CLAIM),
                ("idx_entities_canonical_name", WORD_ENTITY),
            ]
            present_before = [await _raw_pages_contain(conn, schema, idx, word) for idx, word in checks]
            await conn.execute(f'DELETE FROM "{schema}".bilinc_entries')
            await conn.execute(f'DELETE FROM "{schema}".bilinc_claims')
            await conn.execute(f'DELETE FROM "{schema}".entities')
            record = await script.maintain_schema(conn, schema, execute=True, reindex=True)
            absent_after = [not await _raw_pages_contain(conn, schema, idx, word) for idx, word in checks]
            leftovers = await conn.fetchval(
                "SELECT count(*) FROM pg_indexes WHERE schemaname = $1 AND indexname LIKE '%ccnew%'", schema)
            return present_before, record, absent_after, leftovers
        finally:
            await conn.close()
            await _drop(backend, schema)

    present_before, record, absent_after, leftovers = _run(go())
    assert all(present_before)  # the detector sees the words while the rows exist
    assert record["status"] == "ok" and leftovers == 0
    assert all(absent_after)


def test_full_vacuum_rewrites_the_tables_and_leaves_no_trace_of_removed_rows():
    script = _script()
    from bilinc.core.models import MemoryEntry, MemoryType

    async def go():
        import asyncpg

        backend, schema = await _make_tenant()
        conn = await asyncpg.connect(DSN)
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pageinspect")
            await backend.save(MemoryEntry(key="k", value=f"value {WORD_ENTRY}", memory_type=MemoryType.SEMANTIC))
            present = await _raw_pages_contain(conn, schema, "bilinc_entries", WORD_ENTRY)
            await conn.execute(f'DELETE FROM "{schema}".bilinc_entries')
            record = await script.maintain_schema(conn, schema, execute=True, full=True)
            gone = not await _raw_pages_contain(conn, schema, "bilinc_entries", WORD_ENTRY)
            index_gone = not await _raw_pages_contain(conn, schema, "idx_bilinc_entries_fts", WORD_ENTRY)
            return present, record, gone, index_gone
        finally:
            await conn.close()
            await _drop(backend, schema)

    present, record, gone, index_gone = _run(go())
    assert present and record["status"] == "ok" and gone and index_gone


def test_failures_are_reported_per_tenant_and_the_run_exits_1():
    script = _script()

    async def go():
        import asyncpg

        backend, schema = await _make_tenant()
        conn = await asyncpg.connect(DSN)
        empty = f"bilinc_p_{uuid.uuid4().hex}"
        role = f"vt_{uuid.uuid4().hex[:8]}"
        try:
            await conn.execute(f'CREATE SCHEMA "{empty}"')
            missing = await script.maintain_schema(conn, empty, execute=True)
            await conn.execute(f"CREATE ROLE {role} NOLOGIN")
            await conn.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO {role}')
            await conn.execute(f"SET ROLE {role}")
            try:
                denied = await script.maintain_schema(conn, schema, execute=True)
            finally:
                await conn.execute("RESET ROLE")
            records, code = await script.run(DSN, [schema, empty], execute=True)
            ok_and_missing = (records, code)
            return missing, denied, ok_and_missing
        finally:
            await conn.execute("RESET ROLE")
            await conn.execute(f'DROP SCHEMA IF EXISTS "{empty}" CASCADE')
            await conn.execute(f"DROP OWNED BY {role}")
            await conn.execute(f"DROP ROLE IF EXISTS {role}")
            await conn.close()
            await _drop(backend, schema)

    missing, denied, (records, code) = _run(go())
    assert missing["status"] == "skipped_missing_tables"
    assert denied["status"] == "failed" and denied["error"] == "InsufficientPrivilegeError"
    assert code == 1  # a schema missing a table counts as a failed tenant for the exit code
    assert any(r["status"] == "ok" for r in records) and any(r["status"] == "skipped_missing_tables" for r in records)


def test_an_invalid_tenant_name_stops_the_run_before_anything_runs():
    script = _script()

    async def go():
        import asyncpg

        conn = await asyncpg.connect(DSN)
        bad = "bilinc_p_BadName"
        try:
            await conn.execute(f'CREATE SCHEMA "{bad}"')
            return await script.run(DSN, None, execute=True)
        finally:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{bad}" CASCADE')
            await conn.close()

    records, code = _run(go())
    assert records == [] and code == 1


def test_a_held_lock_is_a_named_timeout_for_that_tenant_only():
    script = _script()

    async def go():
        import asyncpg

        locked_backend, locked = await _make_tenant()
        free_backend, free = await _make_tenant()
        holder = await asyncpg.connect(DSN)
        try:
            tx = holder.transaction()
            await tx.start()
            await holder.execute(f'LOCK TABLE "{locked}".bilinc_entries IN ACCESS EXCLUSIVE MODE')
            plain = await script.run(DSN, [locked, free], execute=True, lock_timeout=0.3)
            reindex = await script.run(DSN, [locked, free], execute=True, reindex=True, lock_timeout=0.3)
            await tx.rollback()
            invalid = await holder.fetchval(
                "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = $1 AND NOT i.indisvalid", locked)
            return plain, reindex, invalid
        finally:
            await holder.close()
            await _drop(locked_backend, locked)
            await _drop(free_backend, free)

    (plain_records, plain_code), (reindex_records, reindex_code), invalid = _run(go())
    for records, code in ((plain_records, plain_code), (reindex_records, reindex_code)):
        by_schema = {r["schema"]: r for r in records}
        locked_record = next(r for s, r in by_schema.items() if r["status"] == "failed")
        assert locked_record["error"] == "LockNotAvailableError"
        assert any(r["status"] == "ok" for r in records)  # the other tenant still finished
        assert code == 1
    assert invalid == 0  # nothing was dropped or left invalid here; the script drops nothing itself


def test_running_twice_is_safe():
    script = _script()

    async def go():
        import asyncpg

        backend, schema = await _make_tenant()
        conn = await asyncpg.connect(DSN)
        try:
            first = await script.run(DSN, [schema], execute=True, reindex=True)
            counts = await conn.fetchval(f'SELECT count(*) FROM "{schema}".bilinc_entries')
            second = await script.run(DSN, [schema], execute=True, reindex=True)
            leftovers = await conn.fetchval(
                "SELECT count(*) FROM pg_indexes WHERE schemaname = $1 AND indexname LIKE '%ccnew%'", schema)
            version = await conn.fetchval(f'SELECT max(version) FROM "{schema}".schema_version')
            return first, second, counts, leftovers, version
        finally:
            await conn.close()
            await _drop(backend, schema)

    first, second, counts, leftovers, version = _run(go())
    assert first[1] == 0 and second[1] == 0 and leftovers == 0 and counts == 0 and version is not None


def test_the_security_statement_names_the_postgres_remnants():
    text = (Path(__file__).resolve().parents[1] / "docs" / "security.md").read_text(encoding="utf-8")
    line = next(row for row in text.splitlines() if "secure_delete" in row and "PostgreSQL" in row)
    lowered = line.lower()
    for phrase in ("dead row versions", "index pages", "not overwritten", "write-ahead log", "backups"):
        assert phrase in lowered, phrase
    assert "briefly" not in lowered
