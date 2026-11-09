# Dream pass: SDK, CLI and stdio MCP design (2.7.0)

Status: design, 2026-11-09. The dream pass lets the user's own agent tidy its Bilinc Cloud memory (merge true duplicates, retire stale entries, leave unclear contradictions alone) and undo the result in one step. Bilinc runs no model: the agent reads candidates and sends actions. The hosted service does the work; this package is a client.

## Behaviour (hosted service, as seen by a client)

- `dream_start` returns a dream id and up to 200 candidate entries changed since the last finished dream (first run: the last 7 days), newest first, each with value, type, importance, source, update time and version. Dream report entries (`bilinc:dream:*`) are never candidates.
- `dream_apply` takes up to 25 actions per call: `{op: revise | forget | confirm | flag, key, expected_version, new_value?, merged_from?, reason, evidence_keys}` and returns a result per action: `applied`, `conflict` (the entry changed since it was read) or `error`. Before any change it records each action's prior state in a report: an index entry `bilinc:dream:<id>` plus one entry per change, `bilinc:dream:<id>:<n>`.
- Forget cap: at most 30% of the candidates and at most 20 per dream; a page that would exceed it is refused before any write (`forget_cap`).
- `dream_undo` reverses the dream's own changes only. An entry another writer changed after the dream is reported as a conflict and left alone. Undoing a removed entry restores its value, type, importance and source; other metadata such as TTL or canonical flags is not restored, so an entry that had a TTL comes back without one (`metadata_restored: false`).
- Undo window: 7 days. After that, the prior states are removed from the report and the dream can no longer be undone (`undo_window_expired`).
- Every applied action, report write and undo write is a normal metered write.
- Local-only (`bilinc.db`) memory has no dream pass in this version.

## SDK (`src/bilinc/client.py`, additive)

- `CloudClient.commit(..., if_absent: bool | None = None)`: sends `ifAbsent: true` only when set; the existing call shape is unchanged.
- `CloudClient.dream_start(*, prefix=None, since=None, limit=200, agent=None)` → `POST /api/cloud/memory/dream/start`.
- `CloudClient.dream_apply(dream_id, actions, *, report=None)` → `POST /api/cloud/memory/dream/apply`, split into pages of 25 with `final: true` on the last page only. It stops at the first page that fails and raises that error with the results gathered so far attached (`exc.partial`). Each page carries a stable idempotency key derived from the dream id and page number, so a retried call replays instead of writing twice.
- `CloudClient.dream_undo(dream_id)` → `POST /api/cloud/memory/dream/undo`.
- `CloudClient.dream_show(dream_id)` → `POST /api/cloud/memory/dream/show` (free read).
- Validation mirrors the server limits (key length, ≤25 is handled by splitting, op names, required `expected_version`, `reason`, `evidence_keys`), raising `BilincValidationError` before any request.

## CLI (`bilinc dream`)

- `bilinc dream start [--prefix P] [--since ISO] [--limit N] [--json]`: prints the dream id, candidate count, forget cap and the candidates (JSON with `--json`).
- `bilinc dream apply <dream_id> [--file actions.json | -]`: the file holds `{"actions": [...], "report": {...}}` (the `dream` prompt's output shape) or a bare action list; prints a per-action table and totals.
- `bilinc dream undo <dream_id>`: prints restored keys, conflicts and kept entries; restored forgets say "metadata not restored".
- `bilinc dream show <dream_id> [--json]`.
- Exit codes: 0 success; 1 API error (message only, no traceback); 2 usage error. A partially undone dream exits 0 and lists the conflicts.

## Stdio MCP (`src/bilinc/cloud_mcp.py`)

- Tools `dream_start`, `dream_apply`, `dream_undo`, calling the client methods above.
- They call the hosted service, so they are part of `CLOUD_MCP_TOOLS` (not `LOCAL_MCP_TOOLS`, which is for tools acting on the user's disk) and of `docs/public/product-truth.json`.
- Annotations: `dream_start` not read-only (it writes the report index), `dream_apply` and `dream_undo` destructive.

## Tests (fake transport)

- `commit(if_absent=True)` sends `ifAbsent`; default payload unchanged.
- Each dream method hits its route with the documented payload.
- 60 actions → pages of 25/25/10, `final` only on the last, stable per-page idempotency keys; a failing second page stops and exposes the first page's results.
- CLI: start/apply (file and stdin)/undo/show output and exit codes; `metadata not restored` shown for restored forgets.
- MCP: registered tools equal `CLOUD_MCP_TOOLS | LOCAL_MCP_TOOLS`; dream tool annotations and schemas.
- Truth contract: `product-truth.json` tool list equals `CLOUD_MCP_TOOLS`.

## Out of scope

Release and version bump, the Claude Code plugin, scheduling (a nightly run is a recipe, not a feature), metadata restore and canonical marking (later version).
