# PREV-VAL: legacy `metadata.previous_value` keeps text of replaced values

## Problem
Before 2.6.0, a revision that replaced a value copied `repr(old value)[:200]` into the new entry's `metadata.previous_value` (`adaptive/agm_engine.py`; the fix is `b897427`). Since 2.6.0 a revision stores only `previous_value_sha256` and pops the old field (`agm_engine.py:474-478`). That fixes new revisions only. Rows written before the fix still hold up to 200 characters of an older value, and nothing in the code removes them (`grep previous_value src/` finds the one `pop`, and the sha256 line).

Why the text stays and spreads:
- A stored row is loaded into memory as a `MemoryEntry` with its metadata. Paths that rewrite the entry without replacing its value copy that metadata forward unchanged, so the text lands again in the row, the audit `before`/`after`, the event payload (`core/stateplane.py:3324, 3577`: `payload_json={"metadata": entry.metadata, ...}`) and the next snapshot file:
  - `confirm` (`cloud/runtime.py:898-935`): by design "metadata stays exactly as stored";
  - `revise` with an identical value (`runtime.py:985-1025`): AGM treats it as a no-op and the entry built from `previous_state` keeps the metadata;
  - a TTL rewrite and `consolidate` (`core/stateplane.py:1543-1560`), which saves the buffered entry as it is;
  - a rollback restore (`runtime.py:1442-1459`), which restores the snapshot's entries as they were.
- The local database of the owner holds 200 such rows (Vault Local-Audit "Data quality"); production is unknown.
- No read route returns metadata, so this is storage exposure, not an API leak. It still defeats "revise to remove sensitive text" and any later purge of the key's neighbours is unaffected.

## Approaches
1. **Reserve the field name at the model boundary (chosen, for new copies).** `MemoryEntry.__post_init__` drops a `previous_value` key from `metadata`. Every entry that is loaded, rebuilt from a snapshot or a request, then written, no longer carries it; the next write of any legacy row of any kind (confirm, same-value revise, TTL, consolidate, rollback) persists it clean, and it never reaches events, audit or snapshots again. No migration, no schema change, covers all four non-revising paths with one change.
   - Cost: `previous_value` becomes a reserved metadata key. AGM already pops it on every revision (`agm_engine.py:474-475`), so a caller's own `previous_value` is already discarded on replacing writes; this extends the same rule to every write and load. The release note says so.
2. **Strip it only in `backend.save` / `restore`.** Catches the persisted row but not the in-memory entry that has already been used to build event payloads and audit values, so the event and audit copies would still carry it. Rejected.
3. **Scrub at rest only (a script).** Cleans what exists but does not stop a legacy row that has not been scrubbed from copying the text again on its next confirm or rewrite. Needed as well, for rows that nobody writes again (below), but not sufficient. Chosen as the second part, not alone.

**At-rest scrub (second part).** `scripts/scrub_legacy_previous_value.py` removes the key from the `metadata` column of existing rows.
- Targets: Postgres tenant schemas (`bilinc_entries.metadata`, JSONB: `metadata - 'previous_value'`) and a SQLite database file (`memories.metadata`, text JSON: `json_remove(metadata, '$.previous_value')`, only for rows where `json_valid(metadata)`).
- Default is read-only: it counts the rows that carry the field and writes nothing. `--execute` updates them. Postgres uses a plain connection (no `init()`, as `scripts/sweep_pg_orphan_entities.py` does); `--sqlite PATH` takes a file.
- `--execute` on a SQLite file refuses to run unless `--backup-dir` is given; it first copies the database with SQLite's online backup API (`sqlite3.Connection.backup`), verifies the copy opens and holds the same row count, then updates in one transaction. On Postgres the way back is the count-only run and the nightly off-site backup; the script says so and does not take a copy itself.
- It does not touch `memory_events` payloads, `audit_log` values or snapshot files. Events and audit rows commit to their payload with a stored hash, so rewriting them would break the chain checks, and a purge of the key already removes them. Old snapshot files are backlog item A7. After this change those places keep legacy text until the key is purged; no new copy is made.
- Running it on the owner's `~/bilinc.db` or on production is an owner step (backlog LOCAL-REPAIR and PREV-VAL-PROD). The worker ships the script and tests only and touches no real database.

## Test plan (tests first, small commits)
Postgres tests run under the DSN gate; SQLite tests always.
1. `MemoryEntry(metadata={"previous_value": "x", "keep": 1})` has no `previous_value` and still has `keep`; the caller's dict is not mutated; `from_dict` and a snapshot round trip behave the same.
2. Seed a legacy row (raw SQL: metadata with `previous_value`) on both backends. After each of `confirm`, `revise` with the same value, a `consolidate` of that key, a TTL rewrite and a rollback restore from a snapshot that holds the legacy entry: the stored row, the newest audit `after_value`, the newest event payload and the new snapshot file hold no `previous_value` and none of the seeded text. Revision of a different value still stores `previous_value_sha256` (existing tests at `tests/test_mcp_server_v2.py:461-462`, `tests/test_forget_state_sync.py:104-105` stay green).
3. Scrub script, SQLite: default run counts the legacy rows and the file is byte-identical afterwards (hash before and after); `--execute` without `--backup-dir` exits non-zero and changes nothing; with it, the backup exists and opens with the same row count, only `previous_value` is removed (other metadata keys survive), a row with malformed JSON metadata is left alone and reported, a second run finds nothing.
4. Scrub script, Postgres: default run changes no row (`schema_version` and counts unchanged, no `init()`); `--execute` removes the key and keeps other metadata keys; a schema without the table is skipped and reported; twice is safe.
5. Run through `bilinc-test` only: `-q -m public_source`, `-q -m internal_runtime`, the Postgres tests, and `.venv/bin/ruff check`.

## Rollback and who runs what
- Code: revert the commit. No schema change.
- The scrub removes a metadata key for good. Way back: the count-only run first; the SQLite backup the script takes; the nightly off-site backup for production (not verified from here, the owner confirms before `--execute`). The old text is of a replaced value and is no part of the current memory, so what is lost is only the leftover copy.
- **Running the script on the owner's local database or in production is an owner step.** The worker ships code and tests only and touches neither.

## Release-chain impact
- **Runtime and PyPI package:** the model, the new script. One synchronized version, number chosen by the owner. `pyproject.toml`, `bilinc.__version__`, `server.json` and the MCP registry entry, the hosted runtime image and any site version display move together (`tests/test_public_truth_contract.py` requires one version).
- **SDK behaviour, site code, MCP tool list:** unchanged. No API, tool schema or response field changes. A client that read `metadata.previous_value` from storage gets nothing, but no route returned it.
- **Migration:** none; the scrub is an owner-run command.
- **Public text:** nothing may claim old values are gone from history: events, audit rows and older snapshot files keep legacy text until the key is purged. Wording rule stays "removed from storage and history" for a purge only.
