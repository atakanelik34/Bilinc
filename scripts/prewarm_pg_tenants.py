"""Pre-warm every hosted tenant schema after a runtime upgrade.

Schema v2 adds the full-text ``tsv`` column and fills it the first time a
tenant loads; schema v3 rebuilds it once from folded text. On a large tenant
that first load can take seconds, and if it is a metered write the receipt
flow can time out. Run this once after switching the runtime and before
reopening traffic: it initialises each ``bilinc_p_*`` schema in turn and logs
how long each one took.

Usage:
    BILINC_POSTGRES_DSN=... python scripts/prewarm_pg_tenants.py [--dry-run]

``--dry-run`` lists the tenant schemas and how many rows each would fill,
without changing anything.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from bilinc.storage.postgres import PostgresBackend
from bilinc.storage.postgres_tenancy import quoted, validate_schema_name


async def tenant_schemas(conn) -> list[str]:
    rows = await conn.fetch(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'bilinc\\_p\\_%' ORDER BY schema_name"
    )
    return [validate_schema_name(row["schema_name"]) for row in rows]


async def rows_to_fill(conn, schema: str) -> int:
    has_column = await conn.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = $1 AND table_name = 'bilinc_entries' "
        "AND column_name = 'tsv_at'",
        schema,
    )
    if has_column:
        version = await conn.fetchval(f"SELECT max(version) FROM {quoted(schema)}.schema_version")
        if version is not None and version < 3:
            # Schema v3 rebuilds every full-text vector from folded text.
            return int(await conn.fetchval(f"SELECT COUNT(*) FROM {quoted(schema)}.bilinc_entries"))
        return int(
            await conn.fetchval(
                f"SELECT COUNT(*) FROM {quoted(schema)}.bilinc_entries "
                "WHERE tsv IS NULL OR tsv_at IS DISTINCT FROM updated_at"
            )
        )
    return int(await conn.fetchval(f"SELECT COUNT(*) FROM {quoted(schema)}.bilinc_entries"))


async def main(dry_run: bool) -> int:
    import asyncpg

    dsn = os.environ.get("BILINC_POSTGRES_DSN")
    if not dsn:
        print("BILINC_POSTGRES_DSN is required", file=sys.stderr)
        return 2
    conn = await asyncpg.connect(dsn)
    try:
        schemas = await tenant_schemas(conn)
        pending = {schema: await rows_to_fill(conn, schema) for schema in schemas}
    finally:
        await conn.close()

    failed = 0
    for schema in schemas:
        record: dict = {"schema": schema, "rows_to_fill": pending[schema]}
        if not dry_run:
            started = time.perf_counter()
            backend = PostgresBackend(dsn=dsn, schema=schema)
            try:
                await backend.init()
                record["ms"] = round((time.perf_counter() - started) * 1000)
                record["status"] = "ok"
            except Exception as exc:  # report and continue with the next tenant
                record["status"] = "failed"
                record["error"] = type(exc).__name__
                failed += 1
            finally:
                await backend.close()
        print(json.dumps(record), flush=True)
    print(json.dumps({"tenants": len(schemas), "dry_run": dry_run, "failed": failed}), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args().dry_run)))
