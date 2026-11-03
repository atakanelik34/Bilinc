"""Count, and optionally remove, the legacy ``previous_value`` field from stored memories.

Before 2.6.0 a revision copied up to 200 characters of the replaced value into the new
entry's ``metadata.previous_value``. Current code no longer writes or carries it; this
removes it from rows that already hold it. It touches only that one metadata key, in the
entries table. Events, audit rows and snapshot files commit to what they recorded and are
left alone: a purge of the key removes them.

Usage (from a repository checkout; ``scripts/`` is not part of the package):
    python scripts/scrub_legacy_previous_value.py --sqlite PATH                         # read-only count
    python scripts/scrub_legacy_previous_value.py --sqlite PATH --execute --backup-dir DIR
    BILINC_POSTGRES_DSN=... python scripts/scrub_legacy_previous_value.py               # read-only count
    BILINC_POSTGRES_DSN=... python scripts/scrub_legacy_previous_value.py --execute

Without ``--execute`` nothing is written. SQLite ``--execute`` refuses to run without
``--backup-dir``: it takes the write lock first (and stops, changing nothing, if another process
holds it), copies the database there with SQLite's backup API (mode 0600; the copy still holds the
text, so keep it or destroy it once you have checked the result), verifies the copy, then updates
in one transaction with ``secure_delete`` on and truncates the write-ahead log, so the old text is
not left in freed pages. Rows whose metadata is not valid JSON are left alone and reported.

Postgres: each tenant schema is updated in its own transaction on a plain connection (no ``init()``,
nothing migrated); the report lists schemas updated, skipped and failed, and a stopped run can be
repeated. There is no copy: the way back is the count-only run and the off-site backup, which you
should confirm covers the tenant schemas first. The removed text stays in dead tuples, and in the
pages of the ``idx_bilinc_entries_fts`` index, until vacuum or reindex (backlog item PG-VACUUM).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

FIELD = "previous_value"


class ScrubError(RuntimeError):
    """The run stopped before changing anything."""


def _legacy_rows(conn: sqlite3.Connection) -> tuple[list[tuple[str, str]], list[str]]:
    legacy: list[tuple[str, str]] = []
    malformed: list[str] = []
    for key, metadata in conn.execute("SELECT key, metadata FROM memories"):
        if metadata is None or metadata == "":
            continue
        try:
            parsed = json.loads(metadata)
        except (TypeError, ValueError):
            malformed.append(key)
            continue
        if isinstance(parsed, dict) and FIELD in parsed:
            legacy.append((key, metadata))
    return legacy, malformed


def scrub_sqlite(path, *, execute: bool, backup_dir) -> dict:
    """Count the legacy rows of a SQLite database, or remove the field after taking a verified copy."""
    path = Path(path)
    if not path.is_file():
        raise ScrubError(f"database not found: {path}")
    if not execute:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            legacy, malformed = _legacy_rows(conn)
        finally:
            conn.close()
        return {"database": str(path), "legacy_rows": len(legacy), "skipped_malformed": malformed}

    if backup_dir is None:
        raise ScrubError("--execute needs --backup-dir: a copy of the database is taken before anything changes")
    conn = sqlite3.connect(path, timeout=0, isolation_level=None)
    try:
        conn.execute("PRAGMA secure_delete=ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise ScrubError("the database is busy: another process holds the write lock; stop it and retry") from exc
        try:
            backup = _take_backup(path, Path(backup_dir))
            legacy, malformed = _legacy_rows(conn)
            for key, metadata in legacy:
                parsed = json.loads(metadata)
                parsed.pop(FIELD, None)
                conn.execute(
                    "UPDATE memories SET metadata = ? WHERE key = ? AND metadata = ?",
                    (json.dumps(parsed), key, metadata),
                )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        return {
            "database": str(path),
            "legacy_rows": len(legacy),
            "scrubbed": len(legacy),
            "skipped_malformed": malformed,
            "backup": str(backup),
            "wal_checkpointed": checkpoint is not None and checkpoint[0] == 0,
        }
    finally:
        conn.close()


def _take_backup(path: Path, backup_dir: Path) -> Path:
    """Copy the database with SQLite's backup API, from a separate read-only connection.

    The caller already holds the write lock, so no other writer can change the database while the
    copy is made; readers are not blocked by it, and the backup API must not run on the connection
    that owns the open transaction.
    """
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = backup_dir / f"{path.name}.pre-scrub-{time.strftime('%Y%m%dT%H%M%S')}"
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)  # private from the first byte
    os.close(descriptor)
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    copy = sqlite3.connect(target)
    try:
        source.backup(copy)
        expected = source.execute("SELECT count(*) FROM memories").fetchone()[0]
        actual = copy.execute("SELECT count(*) FROM memories").fetchone()[0]
    finally:
        copy.close()
        source.close()
    if expected != actual:
        raise ScrubError(f"the backup holds {actual} rows but the database holds {expected}; nothing was changed")
    os.chmod(target, 0o600)
    return target


async def tenant_schemas(conn) -> list[str]:
    from bilinc.storage.postgres_tenancy import validate_schema_name

    rows = await conn.fetch(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'bilinc\\_p\\_%' ORDER BY schema_name"
    )
    return [validate_schema_name(row["schema_name"]) for row in rows]


async def scrub_schema(conn, schema: str, *, execute: bool) -> dict:
    """Count the legacy rows of one tenant schema, or remove the field; never initialises the schema."""
    from bilinc.storage.postgres_tenancy import quoted

    record: dict = {"schema": schema}
    found = await conn.fetchval(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = $1 AND table_name = 'bilinc_entries'",
        schema,
    )
    if int(found) != 1:
        record["status"] = "skipped_missing_tables"
        return record
    table = f"{quoted(schema)}.bilinc_entries"
    async with conn.transaction():
        record["legacy_rows"] = int(await conn.fetchval(f"SELECT COUNT(*) FROM {table} WHERE metadata ? '{FIELD}'"))
        if execute:
            result = await conn.execute(f"UPDATE {table} SET metadata = metadata - '{FIELD}' WHERE metadata ? '{FIELD}'")
            record["scrubbed"] = int(result.split()[-1])
    record["status"] = "ok"
    return record


async def main_postgres(execute: bool) -> int:
    import asyncpg

    dsn = os.environ.get("BILINC_POSTGRES_DSN")
    if not dsn:
        print("BILINC_POSTGRES_DSN is required (or pass --sqlite PATH)", file=sys.stderr)
        return 2
    conn = await asyncpg.connect(dsn)
    failed = 0
    try:
        schemas = await tenant_schemas(conn)
        for schema in schemas:
            try:
                record = await scrub_schema(conn, schema, execute=execute)
            except Exception as exc:  # report and continue with the next tenant
                record = {"schema": schema, "status": "failed", "error": type(exc).__name__}
                failed += 1
            print(json.dumps(record), flush=True)
    finally:
        await conn.close()
    print(json.dumps({"tenants": len(schemas), "execute": execute, "failed": failed}), flush=True)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sqlite", metavar="PATH", help="scrub this SQLite database instead of Postgres tenants")
    parser.add_argument("--execute", action="store_true", help="remove the field (default: count only)")
    parser.add_argument("--backup-dir", metavar="DIR", help="where SQLite --execute copies the database first")
    args = parser.parse_args()
    if args.sqlite:
        try:
            print(json.dumps(scrub_sqlite(args.sqlite, execute=args.execute, backup_dir=args.backup_dir)))
        except ScrubError as exc:
            print(f"stopped, nothing changed: {exc}", file=sys.stderr)
            return 1
        return 0
    return asyncio.run(main_postgres(args.execute))


if __name__ == "__main__":
    sys.exit(main())
