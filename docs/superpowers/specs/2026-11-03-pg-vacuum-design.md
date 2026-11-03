# PG-VACUUM: what a Postgres purge leaves on disk, and an opt-in way to reduce it

## Problem
A SQLite purge removes the text physically: `PRAGMA secure_delete`, an FTS segment merge and a WAL truncate (`storage/sqlite.py:99, 954-975`, reached through the `compact_search_index` hook of `_purge_key`, `cloud/runtime.py:1181-1183`). `PostgresBackend` has no such method, so the hook does nothing on Postgres. After a Postgres purge the live rows are gone or replaced, but removed text **may remain** in:
- **dead row versions** in the table pages, until a vacuum removes them (autovacuum does, on its own schedule);
- **three GIN indexes on `bilinc_entries`**: `idx_bilinc_entries_fts` (over `key`, `value::text` and `metadata::text`, `storage/postgres.py:337-345`), `idx_bilinc_tsv` (the `tsv` column, `:354`) and `idx_bilinc_gin_metadata` (`metadata`, `:195`). A plain vacuum removes dead row pointers from their posting lists, but the entry keys themselves (the words) may stay in the index until the index is rebuilt (`REINDEX`) or the table is rewritten (`VACUUM FULL`);
- **other indexes whose keys come from the value**: the B-tree `idx_bilinc_claims_subject_active` on `bilinc_claims.subject` (`:234`; the claim text comes from the value), the B-tree `idx_entities_canonical_name` on `entities.canonical_name` (`:247`; entity names extracted from the value) and the ivfflat `idx_bilinc_embedding` on `bilinc_entries.embedding` (`:194`). A plain vacuum removes their dead tuples, but the bytes stay in page free space until a rebuild;
- **freed space**, which Postgres does not overwrite (it has no `secure_delete`);
- the **write-ahead log** and the **off-site backups**, until they rotate or expire.
Large values also live in TOAST tables; a table's vacuum covers its TOAST relation.

Postgres cannot promise physical removal, so no change to the purge path can honestly promise it. The script's table set is not a second hand-written list: it is `TENANT_TABLES` (`storage/postgres_tenancy.py:16`) minus `schema_version` (`bilinc_entries`, `eval_candidates`, `bilinc_claims`, `entities`, `entity_mentions`, `memory_embeddings`, `memory_events`, `audit_log`), so a future tenant table cannot be missed. The tables a forget or a purge writes on `origin/main`: `bilinc_entries` (`postgres.py:1075`), `audit_log` (`core/postgres_audit_sync.py:166`), `memory_events` (`:1194`), `entity_mentions` (`:645, 1073`), `bilinc_claims` (`:1071, 1204`; the claim text comes from the value), `memory_embeddings` (`:1074`; vectors of the value); the ready A4r branch also deletes from `entities` and `eval_candidates`, which already exist in every tenant schema.

## What the repository already says
`docs/security.md:125` already states the limit, in a weaker form: "Storage engines can keep a removed value briefly at the storage level. ... PostgreSQL keeps old row versions until autovacuum reclaims them." "Briefly" and "until autovacuum reclaims them" suggest the text disappears, which the list above does not support. That line stays the **single source**: it is corrected there, and nowhere else is a second statement added.

## Approaches
1. **Correct the statement, and give the owner an opt-in tool (chosen).**
   - Files this step changes: `docs/security.md` (line 125, wording below), a comment on the `compact_search_index` hook in `cloud/runtime.py` `_purge_key` (comment only, no behaviour change), `CHANGELOG.md`, the new `scripts/vacuum_pg_tenants.py` and its tests.
   - New wording for `docs/security.md:125`: SQLite overwrites deleted content (`secure_delete`), and the purge merges the full-text index and checkpoints the write-ahead log. PostgreSQL has no secure delete: after a purge the removed value may remain as dead row versions, in index pages, in freed space that is not overwritten, in the write-ahead log and in backups, until those are vacuumed, reindexed or rewritten, or expire. The service operator can vacuum and rebuild tables and indexes to reduce these remnants.
   - `scripts/vacuum_pg_tenants.py`, per `bilinc_p_*` tenant schema, over the table set above (`validate_schema_name` and `quoted()` for every identifier, a plain connection, no `init()`, a session `lock_timeout`, see below):
     - **default, read-only:** report each table's size, dead-tuple count and last (auto)vacuum time;
     - **`--execute`:** plain `VACUUM` on the set (lock `SHARE UPDATE EXCLUSIVE`: reads and writes continue);
     - **`--execute --reindex`:** also `REINDEX TABLE CONCURRENTLY` on every table of the set, which rebuilds all their indexes, the GIN, B-tree and ivfflat ones above included (it does not block reads and writes, needs extra disk while it builds and cannot run in a transaction). If it fails it can leave an invalid index (a `*_ccnew` name): the script reports it by name and tells the operator to drop it with `DROP INDEX CONCURRENTLY` or to rerun; **the script never drops it itself**;
     - **`--execute --full`:** `VACUUM FULL` on the set instead, for a maintenance window (lock `ACCESS EXCLUSIVE`: the tenant blocks while it runs; it needs about the size of the largest table in free disk; it rebuilds every index, so no separate reindex). `--reindex` and `--full` together are refused as redundant; either one without `--execute` is refused with exit code 2.
     - **lock waits are bounded.** `VACUUM FULL` asks for `ACCESS EXCLUSIVE`, and while it waits behind an open transaction every later read and write on the table queues behind it; `REINDEX CONCURRENTLY` also waits for older transactions. The session therefore sets `lock_timeout` (default 5 s; `--lock-timeout SECONDS` overrides it). A timeout is reported for that tenant by name (`LockNotAvailable`) and the run moves on to the next tenant;
     - each tenant is reported on its own line; a failure (for example `InsufficientPrivilege`, since `VACUUM` and `REINDEX` need table ownership, or `MAINTAIN` on Postgres 17+) is named and the other tenants still run.
   - Read-only by default; running it in production is an owner step.
2. **Run a vacuum automatically after every purge.** Rejected: `VACUUM` cannot run inside a transaction and needs its own connection; a plain vacuum scans the table, so a purge on a large tenant would become a long request; a full vacuum would block the tenant. It would still not overwrite freed space or touch the WAL and backups, and a plain vacuum does not clear index entry keys. The cost buys no guarantee.
3. **Only document, ship no tool.** Rejected: the owner would then run raw SQL on a production database, schema by schema, by hand; a small checked tool with a read-only default is safer for what the text recommends.

The purge result and the public wording "removed from storage and history" do not change.

## Test plan (tests first, small commits)
Postgres tests run under the DSN gate. Test tenants get `autovacuum_enabled = false` on the touched tables, so autovacuum cannot run between a step and its assertion; statistics are flushed before they are read (`pg_stat_force_next_flush()` where it exists, otherwise polling for up to 5 s).
1. **Default run writes nothing.** A recording wrapper around the connection sees only read statements, and the row counts, `schema_version` and table sizes are unchanged.
2. **Report.** A tenant with dead tuples (rows inserted and updated, no vacuum yet) reports a non-zero dead-tuple count for the touched table.
3. **`--execute`.** A plain `VACUUM` runs without error on every table of the set; afterwards the dead-tuple count is 0 and `last_vacuum` is set.
4. **Index residue, measured.** With the `pageinspect` extension on the throwaway Postgres (the test skips if it cannot be created): seed a row whose metadata holds a unique word, a claim whose `subject` holds another and an entity whose `canonical_name` holds a third, delete them, then read the raw pages of the three GIN indexes and of the claims and entities B-trees. After `--reindex` (`REINDEX TABLE CONCURRENTLY`) none of the words is in any of them; after `VACUUM FULL` it is not in the table or any index. For a plain `VACUUM` the test records what it finds but asserts nothing about index entry keys: that stays "may remain" in the text.
5. **Flags.** `--reindex` or `--full` without `--execute` exit with code 2 and run nothing; `--reindex` with `--full` is refused.
6a. **Lock timeout.** A second connection holds a conflicting lock on one tenant's table: with a short `--lock-timeout` the script reports `LockNotAvailable` for that tenant and the other tenants still finish.
6. **Failure cases.** A schema missing a table is skipped and reported; a schema with an unexpected name stops the run before anything runs (fail closed); a role without the privilege is reported per tenant by name and the other tenants still run (a second, unprivileged role on the throwaway Postgres, if it can be created; otherwise a recording wrapper that raises).
7. **Twice is safe.**
7b. **SQLite does not change.** The SQLite purge path is untouched; its existing tests (`secure_delete`, the FTS merge, the WAL checkpoint) count as its coverage through the full `bilinc-test` run.
8. **The statement.** A test reads `docs/security.md` and asserts the corrected sentence (dead row versions, index pages, freed space not overwritten, write-ahead log, backups) is there and that the word "briefly" is gone.
9. Run through `bilinc-test` only: `-q -m public_source`, `-q -m internal_runtime`, the Postgres tests, and `.venv/bin/ruff check`.

## Rollback and who runs what
- Code: revert the commit. No schema change; the only runtime-path edit is a comment.
- A plain `VACUUM` removes dead row versions, nothing a client can see. `REINDEX CONCURRENTLY` and `VACUUM FULL` rewrite structures; the second blocks the tenant. The script says so and requires the explicit flag.
- **Running the script in production is an owner step; the worker ships the script, the tests and the text only.** The off-site backups and the WAL are outside this change.

## Release-chain impact
- **Where it ships.** `scripts/` and `docs/` are not part of the PyPI wheel or sdist: the wheel's package list is `bilinc` and `bilinc.cli` (`pyproject.toml`), `MANIFEST.in` prunes the runtime packages, and nothing includes `scripts/` or `docs/`. I could not build an sdist here (the venv has no `setuptools`), so this is checked by reading, not by a build. The build-time check `test_built_sdist_does_not_ship_local_runtime_sources` (`tests/test_cloud_only_package.py:419`, runs when `BILINC_TEST_SDIST` is set) is extended to assert that no `/scripts/` or `/docs/` entry is in the sdist, so the owner's build verifies it.
- **Runtime.** The only change under `src/` is a comment in `cloud/runtime.py`; there is nothing to deploy.
- **Version.** None needed. If the owner ships it with another release, the usual synchronized chain applies.
- **SDK behaviour, site code, MCP tool list, migration:** unchanged.
- **Public text.** `docs/security.md` already names the storage engines at this level of detail; the corrected line keeps that level and adds no internals. It is the one public-facing sentence this change edits, so the owner reviews its wording before it ships anywhere public. Nothing may claim physical removal on Postgres.
- **CHANGELOG:** one line under Changed. The other ready branches also add a top `[Unreleased]` section, so the merge needs a trivial conflict resolution.
