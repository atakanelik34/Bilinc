# PG-VACUUM: what a Postgres purge leaves on disk, and an opt-in way to reduce it

## Problem
A SQLite purge removes the text physically: `PRAGMA secure_delete`, an FTS segment merge and a WAL truncate (`storage/sqlite.py:99, 954-975`, called through the `compact_search_index` hook of `_purge_key`, `cloud/runtime.py:1181-1183`). `PostgresBackend` has no such method, so the hook does nothing on Postgres. After a Postgres purge the live rows are gone or replaced (entries, audit values, event payloads, entity rows, capture rows), but:
- the old row versions stay as **dead tuples** in the table pages until a vacuum removes them (autovacuum does it eventually, on its own schedule);
- the GIN expression index `idx_bilinc_entries_fts` indexes `metadata::text` (`storage/postgres.py:337-345`), so its pages keep tokens of removed text until vacuum or reindex;
- even after a vacuum, freed space is not overwritten, and the write-ahead log and the off-site backups keep older page images until they rotate.

Postgres has no `secure_delete`. So physical removal cannot be promised, and no change to the purge path can honestly promise it.

## Approaches
1. **State the limit, and give the owner an opt-in tool (chosen).**
   - Document what a Postgres purge does and does not remove (the list above), next to the purge code and in the internal runtime README, so nobody reads "purged" as "gone from every file".
   - `scripts/vacuum_pg_tenants.py`: per tenant schema, report the dead-tuple count and the last (auto)vacuum time of the tables a purge touches; with `--execute`, run a plain `VACUUM` on them (it takes `SHARE UPDATE EXCLUSIVE`: reads and writes continue); with `--execute --full`, also `VACUUM FULL` and `REINDEX` of the full-text index (`ACCESS EXCLUSIVE`: the tenant blocks while it runs, so it is for a maintenance window and prints that).
   - Read-only by default, like the other maintenance scripts; running it in production is an owner step.
2. **Run a vacuum automatically after every purge.** Rejected: `VACUUM` cannot run inside a transaction and needs its own connection; a plain vacuum scans the table, so a purge on a large tenant would turn into a long request; a full vacuum would block the tenant. It would also still not overwrite freed space or touch the WAL and backups, so the promise stays unmade. The cost buys no guarantee.
3. **Only document, ship no tool.** Rejected: the owner could then only run raw SQL on a production database, per schema, by hand; a small checked tool with a read-only default is the safer way to do what the documentation recommends.

The purge result and the public wording do not change: "removed from storage and history" is about the live data and the history Bilinc serves, and the README says what is not covered.

## Test plan (tests first, small commits)
Postgres tests run under the DSN gate; the documentation point is checked by a test that reads the files.
1. Default run changes nothing: no statement other than reads is issued (a recording wrapper around the connection) and the row counts and `schema_version` are unchanged.
2. A tenant with dead tuples (insert rows, update them, no vacuum yet) reports a non-zero count for the touched table; after `--execute` the plain `VACUUM` ran without error on each touched table and the report shows the run (`vacuumed: true`).
3. `--execute --full` runs `VACUUM FULL` and `REINDEX` on a small tenant without error, and refuses to run without `--execute`. Both print the lock warning.
4. A schema missing a table is skipped and reported; a schema with an unexpected name stops the run before anything runs (fail closed, `validate_schema_name`); a tenant that fails is reported and the others still run.
5. Running twice is safe.
6. The README text is present (a test greps the internal README for the stated limits), so the statement does not silently disappear.
7. Run through `bilinc-test` only: `-q -m public_source`, `-q -m internal_runtime`, the Postgres tests, and `.venv/bin/ruff check`.

## Rollback and who runs what
- Code: revert the commit. No schema change, no change to a purge or to any runtime path.
- A plain `VACUUM` removes dead row versions, nothing a client can see. `VACUUM FULL` and `REINDEX` rewrite the table and the index and block the tenant while they run: the script says so and needs `--full`.
- **Running the script in production is an owner step; the worker ships the script, the tests and the text only.** The off-site backups and the WAL are outside this change.

## Release-chain impact
- **Where it ships.** The script and the internal README are not part of the PyPI wheel or sdist (`MANIFEST.in`, `pyproject.toml` `packages`, `docs/repository-contract.md:13`): they live in the repository checkout. No runtime code changes, so there is nothing to deploy.
- **Version.** None needed: no code in the wheel or the runtime changes. If the owner ships it with another release, the usual synchronized chain applies.
- **SDK behaviour, site code, MCP tool list, migration:** unchanged.
- **Public text:** unchanged wording ("removed from storage and history"); the internal README gains the limits. Nothing public may claim physical removal on Postgres.
- **CHANGELOG:** one line under Added. The other ready branches also add a top `[Unreleased]` section, so the merge needs a trivial conflict resolution.
