"""Count, and optionally delete, orphan entities in every hosted tenant schema.

An orphan entity is one that no memory mentions any more. Postgres tenants kept
them after a forget or a purge until the backend pruned them on write; this
clears the ones that already exist.

Usage:
    BILINC_POSTGRES_DSN=... python scripts/sweep_pg_orphan_entities.py            # read-only count
    BILINC_POSTGRES_DSN=... python scripts/sweep_pg_orphan_entities.py --execute  # delete

Without ``--execute`` it only runs ``SELECT COUNT(*)`` on a plain connection: it
does not initialise or migrate any tenant and writes nothing. A schema missing the
``entities`` or ``entity_mentions`` table is skipped and reported. ``--execute``
uses the same plain connection and the same statement as
``PostgresBackend.sweep_orphan_entities``; it keeps entities saved or relinked in
the last hour. Run it after confirming that the off-site backup covers the tenant
schemas. Safe to run twice. With ``--execute``, ``deleted`` is the authoritative number: ``orphans``
is counted just before in a separate statement, so the two can differ under concurrent writes.
A tenant schema with an unexpected name stops the run before anything is deleted (fail closed).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from bilinc.storage.postgres import PostgresBackend, orphan_entities_statement
from bilinc.storage.postgres_tenancy import quoted, validate_schema_name


async def tenant_schemas(conn) -> list[str]:
    rows = await conn.fetch(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'bilinc\\_p\\_%' ORDER BY schema_name"
    )
    return [validate_schema_name(row["schema_name"]) for row in rows]


async def has_tables(conn, schema: str) -> bool:
    found = await conn.fetchval(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = $1 "
        "AND table_name IN ('entities', 'entity_mentions')",
        schema,
    )
    return int(found) == 2


async def sweep_schema(conn, schema: str, *, execute: bool) -> dict:
    """Count the orphans of one tenant schema, or delete them; never initialises the schema."""
    record: dict = {"schema": schema}
    if not await has_tables(conn, schema):
        record["status"] = "skipped_missing_tables"
        return record
    prefix = quoted(schema) + "."
    cutoff = time.time() - PostgresBackend.ORPHAN_SWEEP_MIN_AGE_SECONDS
    record["orphans"] = int(await conn.fetchval(orphan_entities_statement(prefix, count=True), cutoff))
    if execute:
        result = await conn.execute(orphan_entities_statement(prefix), cutoff)
        record["deleted"] = int(result.split()[-1])
    record["status"] = "ok"
    return record


async def main(execute: bool) -> int:
    import asyncpg

    dsn = os.environ.get("BILINC_POSTGRES_DSN")
    if not dsn:
        print("BILINC_POSTGRES_DSN is required", file=sys.stderr)
        return 2
    conn = await asyncpg.connect(dsn)
    failed = 0
    try:
        schemas = await tenant_schemas(conn)
        for schema in schemas:
            try:
                record = await sweep_schema(conn, schema, execute=execute)
            except Exception as exc:  # report and continue with the next tenant
                record = {"schema": schema, "status": "failed", "error": type(exc).__name__}
                failed += 1
            print(json.dumps(record), flush=True)
    finally:
        await conn.close()
    print(json.dumps({"tenants": len(schemas), "execute": execute, "failed": failed}), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execute", action="store_true", help="delete the orphans (default: count only)")
    sys.exit(asyncio.run(main(parser.parse_args().execute)))
