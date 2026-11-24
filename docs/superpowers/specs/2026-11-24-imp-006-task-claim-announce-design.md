# IMP-006: task claim and announce on top of Bilinc memory (design)

Status: design for review, 2026-11-24. Branch `vm/imp-006` from origin/main `29ed56d` (2.7.3). Source:
improve plan `state/improve-2026-11-10/006-design-task-claim-and-announce.md` (written at 085bb99;
the owner asked for this design by name). Internal design note; nothing here is public text.

## Goal

Let several agents share work through one Bilinc project: claim a task so nobody else does it, mark
it done, leave notes, and announce what happened, using calls that already exist. This item delivers
the design and a set of pinned tests that make the guarantees the design stands on fail loudly if a
later change breaks them. It adds no server, schema or storage change.

## What exists (re-checked on 29ed56d; E numbers kept from the plan)

- **E1 Create-only write**: `commit(..., if_absent=True)` writes when the key is absent and fails with
  `memory_exists` (409) when it is present; the check runs inside the project's write lock
  (cloud/runtime.py:780-815, `_serialized_project_mutation` runtime.py:123). SDK client.py:997-1019.
  Since vm/b4b (ready, not merged) also on the Cloud MCP `commit_mem` and `bilinc commit --if-absent`.
- **E2 Version-checked change**: `revise`, `confirm`, `forget` take `expected_version`; a stale one
  fails with `version_conflict` (409) (runtime.py:1111, 1154, 1325; SDK client.py:1057, 1130).
- **E3 Versions everywhere**: `entry_version` is a hash of the stored entry (runtime.py:196); it comes
  back from writes, recall results and list entries; reads do not change it.
- **E4 One writer at a time per project** inside one runtime process (runtime.py:123).
- **E5 Feed**: `list_memories(prefix, order="newest", updated_after=...)` with keyset cursors
  (runtime.py:986; SDK client.py:1297, `iter_memories` 1360, `get_memory` 1418).
- **E6 Per-key history** (runtime.py:950; SDK client.py:1279).
- **E7 Heartbeat without resending the value**: `confirm(key, expected_version)` only moves
  `updated_at` and returns a new version (runtime.py:1154).
- **E9 Undo**: snapshots, diff, two-step rollback.

## What is missing (G numbers kept)

- **G1** Plain `commit` is never version-checked; a careless `commit` on a task key replaces a claim.
- **G2** Under the default ENTRENCHMENT strategy a revise with lower importance returns HTTP 200 with
  `success: false` (adaptive/agm_engine.py:200-203); a client must read `success`.
- **G3** Create-only only from the SDK: closed by vm/b4b (Cloud MCP + CLI), pending release.
- **G4** No lease: a claim never expires by itself; staleness is a client convention.
- **G5** A change does not record who made it beyond the `reason` text and the value.
- **G6** Coordination records are ordinary memories: they show up in recall, the dream pass and the
  wiki export.
- **G7** The guarantees hold inside one runtime process; two processes serving one project could both
  pass a create-only check (deployment fact, owner).
- **G8** The SDK cannot tell whether the live route honoured `ifAbsent` (owner check, same as B4b).
- **G12** The local stdio server has neither `if_absent` nor `expected_version`.

## Approaches

1. **A documented recipe on the existing calls (chosen).** Key layout and a small state machine;
   E1 for new tasks, notes and announcements; E2 (`revise` with `strategy="recency"`) for claim,
   release, done and takeover; E7 as heartbeat; E5 as board and feed; E6 as record. Pin E1-E7 with
   tests. Accepts G1, G4, G5, G6, G7 as limits.
2. **Server-side claim calls** (claim/heartbeat/release with a service-judged lease, a key range where
   every write must name a version, the writer recorded on every change). Closes G1, G4, G5; needs
   the runtime, the control plane (site), capability flags, SDK, both MCP adapters and a local twin.
   Worth it only after a real multi-agent run on approach 1 shows which limit hurts.
3. **Separate coordination tables** (assign/notes/subtasks/announce per tenant). Rebuilds versioning,
   history, audit and rollback that memories already have, needs a storage-schema change in both
   backends, and splits "what agents know" from "what agents are doing". Rejected.

Choice: approach 1 now; approach 2 is the named second step, gated on evidence from a real run.

## Behaviour (the recipe as a client sees it)

Keys use only `[A-Za-z0-9_.:-]`, at most 256 characters (security/validator.py:10).

| Record | Key | Value | Written with |
|---|---|---|---|
| task | `coord:<board>:task:<task_id>` | object: `title`, `state` (`open`, `claimed`, `done`, `failed`), `owner`, `lease_seconds`, `parent`, `result` | create: `commit(..., if_absent=True, importance=1.0)`; every later change: `revise(..., expected_version=<read>, strategy="recency", importance=1.0, reason="<verb> by <agent>")` |
| note | `coord:<board>:note:<task_id>:<utc>-<agent>-<rand>` | text or object | `commit(..., if_absent=True)`; never revised |
| announcement | `coord:<board>:announce:<utc>-<agent>-<rand>` | text or object | `commit(..., if_absent=True)`; never revised |

Rules:
- Claim: read the task, check `state == "open"`, `revise` with the version just read.
  `version_conflict` = someone else won; pick another task, do not retry the same one.
- After every `revise` check both: no error and `success` true (G2). Task records always use
  `strategy="recency"` and `importance=1.0`.
- Never `commit` (plain) on an existing task key (G1).
- Heartbeat: `confirm(key, expected_version=<current>)` well inside `lease_seconds`; keep the version.
- Takeover: stale = `state == "claimed"` and `updatedAt` older than `lease_seconds`; take it with a
  `revise` naming the version read; a heartbeat in between makes the takeover fail with
  `version_conflict` (wanted).
- Done / failed / release: `revise` with the current version.
- Board: `iter_memories(prefix="coord:<board>:task:", values="full")`, filter by `state`.
- Feed: `list_memories(prefix="coord:<board>:announce:", order="newest", updated_after=<newest seen>)`,
  de-duplicate by key.
- Who did what: `owner`, the `reason` text, and `history(key)` (G5).

## Open questions

1. Key range `coord:` vs a reserved `bilinc:coord:` (reservation is enforced by the control plane,
   not here): **owner**. The recipe uses `coord:` until then.
2. Keep coordination records out of recall / dream pass / wiki export (G6)? **owner**; no change in
   this item.
3. Does the live commit route honour `ifAbsent` (G8), and does more than one runtime process serve a
   project (G7)? **owner**; the recipe's safety rests on both. Same live check as B4b.
4. Clock for staleness: the recipe compares the reader's clock with the service's `updatedAt`.
   Answer from this repo: take "now" from the `updatedAt` of a write the reader just made (any confirm
   or note) to avoid skew; lease length stays a client choice (no number fixed here).
5. Metering of coordination writes: **owner** (no figures here).
6. SDK helper or recipe only: recipe only for now; a helper after one real run.
7. Local parity (G12): local agents would need `if_absent` and `expected_version` on the stdio server
   first; **owner** decides whether local coordination is wanted.

## This item's deliverables

1. This spec.
2. **Pinned guarantees** `tests/test_coordination_primitives.py` (build step), hosted runtime class,
   SQLite and Postgres where marked; they must pass on 29ed56d unchanged (characterization, not
   red-first). Every test asserts outcomes, versions and order, never timings:
   - E1: N concurrent create-only commits on one key -> exactly one success, the rest `memory_exists`;
     the stored value is the winner's. Both backends.
   - E2: N concurrent revises naming the same version -> exactly one success, the rest
     `version_conflict`. Both backends.
   - E3: version unchanged by recall, history and list; the version a revise/confirm returns equals
     the one listed afterwards.
   - E5: `list_memories(order="newest", updated_after=t)` returns only later entries, newest first,
     and a cursor stays valid while another write lands.
   - E6: history of a task shows create, update (reason "claim by a"), confirm (reason "heartbeat")
     in order.
   - E7: a takeover naming the version from before a heartbeat gets `version_conflict`.
   - G2 pin: a lower-importance revise under the default strategy returns `success: false`, the same
     call with `strategy="recency"` succeeds (documents the rule the recipe depends on).
3. Step 3 of the plan (`if_absent` on the Cloud MCP tool and the CLI) is **done as B4b** (vm/b4b);
   not repeated here.

STOP rules carried from the plan: if any pinned test fails on unmodified 29ed56d, or the Postgres
concurrency pins fail while SQLite passes, stop and report (that changes the design); do not weaken
an assertion.

Not in this item: new routes, a version-required rule, a reserved range, service-side leases, a writer
field, excluding records from recall/dream/wiki, an SDK helper class, local server changes, README or
site text, the remote connector, and any public claim about multi-agent coordination.

## Test plan

The pinned tests above (`bilinc-test`, Postgres via `BILINC_TEST_POSTGRES_DSN`); then the full gate:
`bilinc-test -q -m public_source`, `-m internal_runtime`, `ruff check`. Failure cases covered:
`memory_exists`, `version_conflict`, `success: false`. Not tested here on purpose: two runtime
processes (G7) and the live route (G8); both are owner checks.

## Release-chain impact

- Tests and this spec only: no package, runtime, site, registry or migration change. Nothing to
  release. The public-facing part (G3) ships with B4b.
