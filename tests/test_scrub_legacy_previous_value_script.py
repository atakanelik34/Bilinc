"""The legacy-field scrub script counts without writing and removes only ``previous_value`` (item PREV-VAL)."""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import sqlite3
import stat
import uuid
from pathlib import Path

import pytest

LEGACY = "Quartz harbor plan: call Dana Whitfield"
DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "scrub_legacy_previous_value.py"
    spec = importlib.util.spec_from_file_location("scrub_legacy_previous_value", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE memories (key TEXT PRIMARY KEY, value TEXT, metadata TEXT)")
    rows = [
        ("legacy", "v1", json.dumps({"previous_value": LEGACY, "keep": "yes"})),
        ("legacy2", "v2", json.dumps({"previous_value": LEGACY})),
        ("clean", "v3", json.dumps({"keep": "also"})),
        ("empty", "v4", None),
        ("broken", "v5", "not json {"),
    ]
    conn.executemany("INSERT INTO memories VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metadata(path: Path) -> dict:
    conn = sqlite3.connect(path)
    try:
        return {k: m for k, m in conn.execute("SELECT key, metadata FROM memories")}
    finally:
        conn.close()


def test_sqlite_count_only_writes_nothing(tmp_path):
    script = _script()
    db = tmp_path / "bilinc.db"
    _make_db(db)
    before = _digest(db)
    report = script.scrub_sqlite(db, execute=False, backup_dir=None)
    assert report["legacy_rows"] == 2 and report["skipped_malformed"] == ["broken"] and "scrubbed" not in report
    assert _digest(db) == before


def test_sqlite_execute_needs_a_backup_directory(tmp_path):
    script = _script()
    db = tmp_path / "bilinc.db"
    _make_db(db)
    before = _digest(db)
    with pytest.raises(script.ScrubError, match="backup"):
        script.scrub_sqlite(db, execute=True, backup_dir=None)
    assert _digest(db) == before


def test_sqlite_execute_removes_only_the_field_and_leaves_no_trace_on_disk(tmp_path):
    script = _script()
    db = tmp_path / "bilinc.db"
    backups = tmp_path / "backups"
    _make_db(db)
    report = script.scrub_sqlite(db, execute=True, backup_dir=backups)
    assert report["scrubbed"] == 2 and report["skipped_malformed"] == ["broken"]

    metadata = _metadata(db)
    assert json.loads(metadata["legacy"]) == {"keep": "yes"}
    assert json.loads(metadata["legacy2"]) == {}
    assert json.loads(metadata["clean"]) == {"keep": "also"}
    assert metadata["empty"] is None and metadata["broken"] == "not json {"

    # the text is gone from the database file and from its write-ahead log
    for candidate in (db, Path(str(db) + "-wal")):
        if candidate.exists():
            assert b"Dana Whitfield" not in candidate.read_bytes()

    # the backup is the owner's to keep or destroy: private, complete, and it still holds the text
    copies = list(backups.iterdir())
    assert len(copies) == 1 and stat.S_IMODE(copies[0].stat().st_mode) == 0o600
    assert report["backup"] == str(copies[0])
    copy = sqlite3.connect(copies[0])
    try:
        assert copy.execute("SELECT count(*) FROM memories").fetchone()[0] == 5
    finally:
        copy.close()
    assert b"Dana Whitfield" in copies[0].read_bytes()

    again = script.scrub_sqlite(db, execute=False, backup_dir=None)
    assert again["legacy_rows"] == 0


def test_sqlite_execute_changes_nothing_when_the_database_is_busy(tmp_path):
    script = _script()
    db = tmp_path / "bilinc.db"
    _make_db(db)
    holder = sqlite3.connect(db, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")  # another process holds the write lock
    try:
        before = _metadata(db)
        with pytest.raises(script.ScrubError, match="busy"):
            script.scrub_sqlite(db, execute=True, backup_dir=tmp_path / "backups")
        assert _metadata(db) == before
    finally:
        holder.execute("ROLLBACK")
        holder.close()


@pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set")
def test_postgres_count_only_writes_nothing_and_execute_removes_the_key():
    script = _script()
    from bilinc.storage.postgres import PostgresBackend

    async def go():
        import asyncpg

        backend = PostgresBackend(dsn=DSN, schema=f"bilinc_p_{uuid.uuid4().hex}")
        await backend.init()
        schema = backend.schema
        conn = await asyncpg.connect(DSN)
        try:
            await conn.execute(
                f'''INSERT INTO "{schema}".bilinc_entries (id, key, memory_type, value, metadata, created_at, updated_at)
                    VALUES ('1', 'legacy', 'semantic', '"v"', $1::jsonb, 1, 1), ('2', 'clean', 'semantic', '"v"', $2::jsonb, 1, 1)''',
                json.dumps({"previous_value": LEGACY, "keep": "yes"}), json.dumps({"keep": "also"}))

            async def snapshot():
                return (
                    await conn.fetchval(f'SELECT count(*) FROM "{schema}".bilinc_entries'),
                    await conn.fetchval(f'SELECT max(version) FROM "{schema}".schema_version'),
                    str(await conn.fetch(f'SELECT key, metadata FROM "{schema}".bilinc_entries ORDER BY key')),
                )

            before = await snapshot()
            counted = await script.scrub_schema(conn, schema, execute=False)
            after_count = await snapshot()
            executed = await script.scrub_schema(conn, schema, execute=True)
            rows = {r["key"]: json.loads(r["metadata"]) for r in await conn.fetch(f'SELECT key, metadata FROM "{schema}".bilinc_entries')}
            again = await script.scrub_schema(conn, schema, execute=True)

            empty = f"bilinc_p_{uuid.uuid4().hex}"
            await conn.execute(f'CREATE SCHEMA "{empty}"')
            try:
                skipped = await script.scrub_schema(conn, empty, execute=True)
            finally:
                await conn.execute(f'DROP SCHEMA "{empty}" CASCADE')
            return before, counted, after_count, executed, rows, again, skipped
        finally:
            await backend.close()
            await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            await conn.close()

    before, counted, after_count, executed, rows, again, skipped = asyncio.new_event_loop().run_until_complete(go())
    assert counted["legacy_rows"] == 1 and "scrubbed" not in counted
    assert after_count == before  # count-only: no row and no schema_version changed
    assert executed["scrubbed"] == 1
    assert rows == {"legacy": {"keep": "yes"}, "clean": {"keep": "also"}}
    assert again["legacy_rows"] == 0 and again["scrubbed"] == 0
    assert skipped["status"] == "skipped_missing_tables"


def test_sqlite_execute_on_a_database_made_by_the_backend_keeps_search_and_columns(tmp_path):
    from bilinc.core.models import MemoryEntry, MemoryType
    from bilinc.storage.sqlite import SQLiteBackend

    script = _script()
    db = tmp_path / "real.db"

    async def seed():
        backend = SQLiteBackend(str(db))
        await backend.init()
        for key, value in (("plan", "harbor plan for the quarter"), ("note", "unrelated note")):
            await backend.save(MemoryEntry(key=key, value=value, memory_type=MemoryType.SEMANTIC, metadata={"keep": "yes"}))
        conn = backend._get_conn()
        conn.execute("UPDATE memories SET metadata = json_set(metadata, '$.previous_value', ?) WHERE key = 'plan'", (LEGACY,))
        conn.commit()
        await backend.close()

    def columns():
        conn = sqlite3.connect(db)
        try:
            return conn.execute("SELECT key, value, memory_type, importance, source, updated_at FROM memories ORDER BY key").fetchall()
        finally:
            conn.close()

    async def check():
        backend = SQLiteBackend(str(db))
        await backend.init()
        try:
            return [row for row in backend.fts_search("harbor")]
        finally:
            await backend.close()

    asyncio.new_event_loop().run_until_complete(seed())
    before = columns()
    report = script.scrub_sqlite(db, execute=True, backup_dir=tmp_path / "backups")
    assert report["scrubbed"] == 1
    assert columns() == before  # every other column is untouched, updated_at included
    assert asyncio.new_event_loop().run_until_complete(check())  # full-text search still finds the row
    for candidate in (db, Path(str(db) + "-wal")):
        if candidate.exists():
            assert b"Dana Whitfield" not in candidate.read_bytes()


def test_a_failed_backup_leaves_no_copy_behind(tmp_path, monkeypatch):
    """A copy that fails is removed: it would hold the text it was meant to protect."""
    script = _script()
    db = tmp_path / "bilinc.db"
    _make_db(db)
    backups = tmp_path / "backups"
    real_connect = sqlite3.connect

    class _FailingBackup(sqlite3.Connection):
        def backup(self, *args, **kwargs):
            raise sqlite3.OperationalError("disk full")

    def connect(target, *args, **kwargs):
        if str(target).startswith("file:") and "mode=ro" in str(target):
            kwargs["factory"] = _FailingBackup
        return real_connect(target, *args, **kwargs)

    monkeypatch.setattr(script.sqlite3, "connect", connect)
    with pytest.raises(sqlite3.OperationalError, match="disk full"):
        script.scrub_sqlite(db, execute=True, backup_dir=backups)
    assert list(backups.iterdir()) == []
    monkeypatch.undo()
    assert _metadata(db)["legacy"] == json.dumps({"previous_value": LEGACY, "keep": "yes"})  # nothing was changed
