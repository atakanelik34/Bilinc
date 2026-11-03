"""Report on, and optionally vacuum or rebuild, the tables a purge touches in every hosted tenant schema.

Postgres has no ``secure_delete``. After a purge the removed text may remain as dead row versions, in the
pages of the tables' indexes (the GIN full-text and metadata indexes, the claims and entities B-trees, the
embedding index), in freed space that is not overwritten, in the write-ahead log and in backups. This
reduces the first two; the log and the backups are outside it. It does not change what a purge does.

Usage (from a repository checkout; ``scripts/`` is not part of the package):
    BILINC_POSTGRES_DSN=... python scripts/vacuum_pg_tenants.py                              # read-only report
    BILINC_POSTGRES_DSN=... python scripts/vacuum_pg_tenants.py --execute                    # plain VACUUM
    BILINC_POSTGRES_DSN=... python scripts/vacuum_pg_tenants.py --execute --reindex          # + REINDEX TABLE CONCURRENTLY
    BILINC_POSTGRES_DSN=... python scripts/vacuum_pg_tenants.py --execute --full             # VACUUM FULL (maintenance window)
    ...                     --schema bilinc_p_<id>                                           # limit to named tenants (repeatable)

Default is read-only: table sizes, dead-tuple counts and last (auto)vacuum times, nothing written, no
``init()``. Per table, ``--execute`` runs ``VACUUM`` (lock ``SHARE UPDATE EXCLUSIVE``: reads and writes
continue). ``--reindex`` then runs ``REINDEX TABLE CONCURRENTLY`` (no blocking of reads and writes, extra disk
while it builds). ``--full`` runs ``VACUUM FULL`` instead: lock ``ACCESS EXCLUSIVE``, the tenant blocks while
it runs, and it needs about the size of the largest table in free disk; it rebuilds every index, so no separate
reindex. ``--reindex`` and ``--full`` together, or either one without ``--execute``, are refused (exit 2).

Lock waits are bounded: the session sets ``lock_timeout`` (default 5 s, ``--lock-timeout SECONDS``) so a request
queued behind an open transaction cannot stall the tenant; a timeout is reported for that tenant and the run goes
on. ``statement_timeout`` is set to 0 on the session so an inherited timeout cannot abort a long rewrite. A failed
``REINDEX CONCURRENTLY`` can leave an invalid index (a ``*_ccnew`` name): it is reported by name, and the operator
drops it with ``DROP INDEX CONCURRENTLY`` or reruns; this script never drops anything.

Exit code: 0 when every tenant succeeded, 1 when any tenant failed or was skipped for a missing table, 2 for
refused flags. VACUUM and REINDEX need table ownership (or MAINTAIN on Postgres 17+); a missing privilege is
reported per tenant by name. Running this in production is an owner step.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from bilinc.storage.postgres_tenancy import TENANT_TABLES, quoted, validate_schema_name

#: The tables a forget or a purge writes, derived from the tenant table list so a new table cannot be missed.
TABLES = tuple(table for table in TENANT_TABLES if table != "schema_version")
DEFAULT_LOCK_TIMEOUT = 5.0


async def tenant_schemas(conn) -> list[str]:
    rows = await conn.fetch(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'bilinc\\_p\\_%' ORDER BY schema_name"
    )
    return [validate_schema_name(row["schema_name"]) for row in rows]


async def _report(conn, schema: str) -> dict:
    tables: dict = {}
    for table in TABLES:
        row = await conn.fetchrow(
            "SELECT pg_total_relation_size(to_regclass($1)) AS size, s.n_dead_tup, s.last_vacuum, s.last_autovacuum "
            "FROM (SELECT 1) one LEFT JOIN pg_stat_user_tables s ON s.schemaname = $2 AND s.relname = $3",
            f"{quoted(schema)}.{table}", schema, table,
        )
        tables[table] = {
            "size_bytes": int(row["size"] or 0),
            "dead_tuples": int(row["n_dead_tup"] or 0),
            "last_vacuum": row["last_vacuum"].isoformat() if row["last_vacuum"] else None,
            "last_autovacuum": row["last_autovacuum"].isoformat() if row["last_autovacuum"] else None,
        }
    return tables


async def _invalid_indexes(conn, schema: str) -> list[str]:
    rows = await conn.fetch(
        "SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = $1 AND NOT i.indisvalid ORDER BY c.relname",
        schema,
    )
    return [row["relname"] for row in rows]


async def maintain_schema(conn, schema: str, *, execute: bool = False, reindex: bool = False, full: bool = False,
                          lock_timeout: float = DEFAULT_LOCK_TIMEOUT) -> dict:
    """Report on one tenant schema, or vacuum (and reindex, or rewrite) its tables; never initialises it."""
    import asyncpg

    schema = validate_schema_name(schema)
    record: dict = {"schema": schema}
    # pg_tables, not information_schema: the latter hides tables the role has no privilege on, which would
    # make a missing privilege look like a missing table.
    present = await conn.fetchval(
        "SELECT COUNT(*) FROM pg_catalog.pg_tables WHERE schemaname = $1 AND tablename = ANY($2::text[])",
        schema, list(TABLES),
    )
    if int(present) != len(TABLES):
        record["status"] = "skipped_missing_tables"
        return record
    # Every lock wait is bounded, the read-only report included: even the size lookup takes a lock, and
    # queued behind an open transaction it would stall. set_config is a SELECT, so the default run issues
    # reads only. The session's own settings are put back at the end.
    previous = {name: await conn.fetchval("SELECT current_setting($1)", name)
                for name in ("lock_timeout", "statement_timeout")}
    await conn.fetchval("SELECT set_config('lock_timeout', $1, false)", f"{max(1, int(lock_timeout * 1000))}ms")
    if execute:
        await conn.fetchval("SELECT set_config('statement_timeout', '0', false)")
    try:
        try:
            record["tables"] = await _report(conn, schema)
        except asyncpg.PostgresError as exc:
            record["status"] = "failed"
            record["error"] = type(exc).__name__
            return record
        record["status"] = "ok"
        if not execute:
            return record
        # VACUUM by a role that does not own the table only warns and skips it, which would read as success.
        not_owned = await conn.fetch(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = $1 AND tablename = ANY($2::text[]) "
            "AND NOT pg_has_role(current_user, tableowner, 'USAGE') ORDER BY tablename",
            schema, list(TABLES),
        )
        if not_owned:
            record["status"] = "failed"
            record["error"] = "InsufficientPrivilegeError"
            record["table"] = not_owned[0]["tablename"]
            return record
        for table in TABLES:
            qualified = f"{quoted(schema)}.{table}"
            try:
                if full:
                    await conn.execute(f"VACUUM FULL {qualified}")
                else:
                    await conn.execute(f"VACUUM {qualified}")
                    if reindex:
                        await conn.execute(f"REINDEX TABLE CONCURRENTLY {qualified}")
                record["tables"][table]["vacuumed"] = True
            except asyncpg.PostgresError as exc:
                record["status"] = "failed"
                record["error"] = type(exc).__name__
                record["table"] = table
                invalid = await _invalid_indexes(conn, schema)
                if invalid:
                    record["invalid_indexes"] = invalid
                    record["hint"] = ("drop each invalid index with DROP INDEX CONCURRENTLY, or run again; "
                                      "this script never drops one itself")
                break
        return record
    finally:
        for name, value in previous.items():
            await conn.fetchval("SELECT set_config($1, $2, false)", name, value)


async def run(dsn: str, schemas, *, execute: bool = False, reindex: bool = False, full: bool = False,
              lock_timeout: float = DEFAULT_LOCK_TIMEOUT) -> tuple[list[dict], int]:
    """Process the named tenant schemas (all of them when ``schemas`` is None); returns (records, exit code)."""
    import asyncpg

    conn = await asyncpg.connect(dsn)
    records: list[dict] = []
    try:
        try:
            names = [validate_schema_name(name) for name in schemas] if schemas else await tenant_schemas(conn)
        except ValueError as exc:  # an unexpected schema name: stop before anything runs
            print(f"stopped before running anything: {exc}", file=sys.stderr)
            return [], 1
        for name in names:
            try:
                record = await maintain_schema(conn, name, execute=execute, reindex=reindex, full=full,
                                               lock_timeout=lock_timeout)
            except Exception as exc:  # report and continue with the next tenant
                record = {"schema": name, "status": "failed", "error": type(exc).__name__}
            records.append(record)
    finally:
        await conn.close()
    return records, 0 if all(record["status"] == "ok" for record in records) else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execute", action="store_true", help="run VACUUM (default: report only)")
    parser.add_argument("--reindex", action="store_true", help="with --execute: also REINDEX TABLE CONCURRENTLY")
    parser.add_argument("--full", action="store_true", help="with --execute: VACUUM FULL instead (blocks the tenant)")
    parser.add_argument("--lock-timeout", type=float, default=DEFAULT_LOCK_TIMEOUT, metavar="SECONDS")
    parser.add_argument("--schema", action="append", metavar="NAME", help="limit to this tenant schema (repeatable)")
    args = parser.parse_args(argv)
    if (args.reindex or args.full) and not args.execute:
        print("--reindex and --full need --execute", file=sys.stderr)
        return 2
    if args.reindex and args.full:
        print("--reindex and --full together are refused: VACUUM FULL already rebuilds every index", file=sys.stderr)
        return 2
    if args.lock_timeout <= 0:
        print("--lock-timeout must be above 0 (a zero timeout would wait forever)", file=sys.stderr)
        return 2
    dsn = os.environ.get("BILINC_POSTGRES_DSN")
    if not dsn:
        print("BILINC_POSTGRES_DSN is required", file=sys.stderr)
        return 2
    records, code = asyncio.run(run(dsn, args.schema, execute=args.execute, reindex=args.reindex, full=args.full,
                                    lock_timeout=args.lock_timeout))
    for record in records:
        print(json.dumps(record, default=str), flush=True)
        if record.get("hint"):
            print(f"{record['schema']}: invalid index {record['invalid_indexes']}: {record['hint']}", file=sys.stderr)
    print(json.dumps({"tenants": len(records), "execute": args.execute, "failed": sum(r["status"] != "ok" for r in records)}),
          flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
