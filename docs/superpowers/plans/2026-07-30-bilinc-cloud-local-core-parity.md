# Bilinc Cloud Local-Core Parity Sprint

**Status:** Ready for implementation  
**Created:** 2026-07-30  
**Owner:** Atakan / ReARC Labs  
**Target executor:** Claude Opus 5  
**Primary repository:** `/Users/busecimen/Downloads/Projeler/Agent/Bilinc`  
**Public site/control plane:** `/Users/busecimen/Downloads/Projeler/bilinc-site 2`  
**Concerns:** `agent-memory`, `security-critical`, `public-facing`, `payments`  
**Release posture:** Implement and verify locally; do not push, publish, deploy, or mutate production without a separate explicit approval.

## 1. Executor instruction

You are Claude Opus 5 acting as a detail-obsessed senior product and backend engineer for ReARC Labs.

Implement this sprint end to end, in dependency order, with small reviewable commits and evidence for every acceptance gate. Read the relevant code before editing. Prefer existing Bilinc architecture and repository patterns over new abstractions.

Do not push. Do not publish. Do not deploy. Those are separate approval gates.

Do not treat this as a request to copy every local MCP tool into Bilinc Cloud. The goal is **core lifecycle parity**: a Cloud user should be able to write, recall, deliberately revise, deliberately forget, checkpoint, inspect a change, restore a known-good state, and inspect their authenticated runtime status using the same product vocabulary as local Bilinc.

The target public Cloud MCP surface after this sprint is:

1. `commit_mem`
2. `recall`
3. `revise`
4. `forget`
5. `status`
6. `snapshot`
7. `diff`
8. `rollback`

The following local tools are intentionally not part of this sprint:

- `consolidate`
- `summarize`
- `event_segment`
- `bilinc_workspace_preview`
- `bilinc_workspace_status`
- `bilinc_workspace_replay_session`
- `bilinc_health`
- `bilinc_benchmark`
- `bilinc_export`
- `bilinc_import`
- `claims_list`
- raw `contradictions`
- `bilinc_recall_smart` as a separate tool
- `bilinc_query_analysis` as a separate tool
- multi-agent sync administration

Do not add those tools opportunistically. Smart retrieval remains represented by the existing `recall` profiles. Epistemic read tools such as `verify`, `claims_search`, `claim_contradictions`, and `query_graph` are a separate follow-up sprint after the core lifecycle is proven in Cloud.

## 2. Why this sprint exists

Bilinc local currently exposes a mature StatePlane and a 27-tool MCP surface. The public Bilinc Cloud package intentionally ships a narrow SDK, CLI, and MCP adapter, but its current public lifecycle is too narrow:

- `CloudClient` exposes only `commit`, `recall`, and `status`.
- Cloud MCP exposes only `commit_mem`, `recall`, and `status`.
- `status()` currently calls the public system health endpoint instead of authenticated account/workspace/capability status.
- The Cloud runtime already creates and lists project-isolated snapshots, but the public SDK and MCP adapter do not expose them.
- Public copy describes revision, forgetting, snapshots, diffs, and rollback more broadly than the current public agent-facing API supports.

This creates a product gap. A user can write and retrieve memory, but cannot complete the state lifecycle that differentiates Bilinc from a vector store.

## 3. Product decision

“Cloud approaches local” means:

- the same core product concepts;
- the same stable tool names where they are already public/local vocabulary;
- equivalent observable behavior for the supported lifecycle;
- Cloud-safe authorization, tenancy, billing, concurrency, and recovery controls;
- additive backward compatibility for existing Cloud users.

It does **not** mean:

- exposing internal operator/debug tools to agents;
- shipping local StatePlane/storage internals in the public PyPI artifact;
- reproducing every local implementation detail over HTTP;
- reviving the historical local-to-Cloud monkey-patch or dual-write prototype;
- making Cloud depend on a local Bilinc database;
- changing plan prices, credit packs, payment provider, memory backend, or deployment target.

## 4. Verified current baseline

Verify these facts again before editing. If current code differs, record the drift and update this document in the implementation branch before proceeding.

### 4.1 Public package

- Current package version at planning time: `2.1.5`.
- Public package list is intentionally limited to `bilinc` and `bilinc.cli`.
- Public dependencies are currently `certifi` and `mcp`.
- Public API includes `CloudClient` and the Cloud MCP adapter.
- Public wheel/sdist must not contain local runtime packages.

Relevant files:

- `pyproject.toml`
- `src/bilinc/__init__.py`
- `src/bilinc/client.py`
- `src/bilinc/cloud_mcp.py`
- `src/bilinc/cli/main.py`
- `tests/test_cloud_only_package.py`

### 4.2 Internal Cloud runtime

The private/internal runtime already provides:

- project-isolated SQLite StatePlane instances;
- verified AGM-backed commit;
- profiled recall;
- snapshot creation;
- snapshot listing.

Relevant files:

- `src/bilinc/cloud/runtime.py`
- `src/bilinc/cloud/service.py`
- `tests/test_cloud_runtime.py`
- `tests/test_cloud_service.py`

### 4.3 Site control plane

The Next.js control plane already provides:

- bearer API-key authorization;
- organization/project/API-key grant resolution;
- plan entitlement checks;
- usage quota and Cloud credit reservation;
- idempotent usage recording;
- credit reservation release on failed runtime operations;
- public commit, recall, and snapshot routes.

Relevant files:

- `app/api/cloud/memory/commit/route.ts`
- `app/api/cloud/memory/recall/route.ts`
- `app/api/cloud/memory/snapshots/route.ts`
- `lib/cloud/runtime-access.ts`
- `lib/cloud/repository.ts`
- `lib/billing/usage.ts`
- `lib/billing/credits.ts`
- `lib/billing/entitlements.ts`

### 4.4 Important existing risks

1. Usage-event idempotency does not prove mutation idempotency. A retried write can mutate the sidecar twice while being billed once.
2. Public recall accepts a limit of 100 while the sidecar currently accepts at most 50.
3. Control-plane routes can flatten sidecar failures into generic `503` responses and may return internal error text.
4. Snapshot IDs are timestamp-derived and the stored full snapshot is not yet exposed through a safe restore workflow.
5. Local rollback accepts a raw timestamp and executes immediately. That is not safe enough for a hosted multi-tenant agent API.
6. The site working tree was dirty at planning time. Do not overwrite or mix those unrelated changes into this sprint.

## 5. User stories

1. As an agent developer, I want the existing `commit_mem`, `recall`, and `status` behavior to keep working after the upgrade.
2. As an agent developer, I want one Cloud API key to expose the supported memory lifecycle without local database configuration.
3. As an agent, I want to revise a known memory deliberately so that changes are distinguishable from accidental overwrites.
4. As an agent, I want to remove a memory from active recall with an audit reason so that obsolete state stops influencing later runs.
5. As an operator, I want to create and list project-scoped snapshots before risky agent work.
6. As an operator, I want to diff current state against a known snapshot before deciding to restore it.
7. As an operator, I want rollback to require preview and explicit confirmation so an agent cannot silently destroy current state.
8. As an operator, I want rollback to fail if the project state changed after preview.
9. As a workspace owner, I want status to show the authenticated workspace, plan, limits, supported capabilities, and runtime readiness without exposing secrets.
10. As a Cloud customer, I want operations to be billed once even if a request is retried.
11. As a Cloud customer, I want a repeated idempotent mutation to return the original result rather than execute twice.
12. As a security reviewer, I want every snapshot, diff, rollback, revise, and forget operation isolated to the API key's project.
13. As a security reviewer, I want cross-project identifiers to behave as not found and never disclose whether another tenant's object exists.
14. As an SDK user, I want typed, stable errors that tell me whether to authenticate, upgrade, retry, resolve a conflict, or fix my input.
15. As an MCP user, I want destructive tools to describe their risk in the schema and require explicit arguments.
16. As a package user, I want the public wheel to remain Cloud-only and free of internal runtime code.
17. As a docs reader, I want examples and capability claims to match the exact released package and live Cloud surface.
18. As a ReARC operator, I want deployment and public release to remain separate approval gates after local implementation passes.

## 6. Target public capability contract

### 6.1 Tool matrix

| Tool | Current Cloud | Target | Mutation | Destructive | Metering policy |
|---|---:|---:|---:|---:|---|
| `commit_mem` | Yes | Preserve and harden | Yes | No | Existing `memory_write` |
| `recall` | Yes | Preserve and normalize | No | No | Existing `recall` |
| `status` | Miswired to public health | Authenticated account/runtime status | No | No | No usage charge |
| `revise` | No | Add | Yes | Controlled overwrite | Existing `memory_write` |
| `forget` | No | Add | Yes | Yes | Existing `memory_write` |
| `snapshot` | Backend route only | Add create/list to SDK and MCP | Create only | No | Create uses `snapshot`; list is free |
| `diff` | No | Add snapshot-to-current/snapshot-to-snapshot | No | No | No usage charge in this sprint |
| `rollback` | No | Add preview/execute flow | Yes | Yes | Preview free; execute uses `rollback` |

Do not add a new billing event or change a credit cost in this sprint. If the existing event model cannot represent the operation safely, stop at that operation's release gate and report the exact decision needed.

### 6.2 Public operational endpoints

Preserve:

- `GET /api/cloud/health` as unauthenticated service health.
- `POST /api/cloud/memory/commit`
- `POST /api/cloud/memory/recall`
- `GET /api/cloud/memory/snapshots`
- `POST /api/cloud/memory/snapshots`

Add:

- `GET /api/cloud/status`
- `POST /api/cloud/memory/revise`
- `POST /api/cloud/memory/forget`
- `POST /api/cloud/memory/diff`
- `POST /api/cloud/memory/rollback/preview`
- `POST /api/cloud/memory/rollback`

Do not silently repurpose `/api/cloud/health`. `CloudClient.status()` must move to authenticated `/api/cloud/status`, while a new `CloudClient.health()` method may expose public service health.

### 6.3 Internal sidecar endpoints

Preserve existing commit, recall, and snapshots endpoints. Add project-scoped internal endpoints corresponding to revise, forget, diff, rollback preview, rollback execute, and status only where the control plane cannot build the result itself.

All sidecar endpoints must:

- require the existing sidecar service token;
- validate the project UUID before filesystem access;
- operate only inside the normalized project directory;
- return stable machine-readable error codes;
- never accept organization/project ownership claims from public request bodies;
- never log the sidecar token, customer API key, full memory value, or snapshot contents.

## 7. Public operation schemas

Names below are the public SDK/MCP contract. Public HTTP may use the existing camelCase convention; internal sidecar payloads may remain snake_case. Centralize translation instead of duplicating ad hoc parsing.

### 7.1 `commit_mem`

Inputs:

- `key: str`, required, 1-512 characters;
- `value: JSON`, required;
- `memory_type`, default `semantic`;
- `importance: float`, default `1.0`, range `0.0-1.0`;
- `metadata: object`, default empty;
- `source: str | null`;
- `session_id: str | null`;
- `canonical: bool | null`;
- `priority: float | null`, range `0.0-1.0`;
- `ttl: number | null`, positive seconds;
- `idempotency_key: str | null`.

Behavior:

- preserve current simple calls;
- map the richer Hermes/local metadata contract without changing the local runtime API;
- return operation, affected keys, removed keys, entry/state version, and additive request metadata;
- do not automatically retry the mutation until runtime-level idempotency is implemented.

### 7.2 `recall`

Inputs:

- `query: str`, required, 1-4096 characters;
- `profile: fast | balanced | verified | deep`, entitlement-gated;
- `limit: int`, default 10, range 1-100;
- `memory_types: list | null`;
- `explain: bool`, default false.

Behavior:

- use one canonical maximum across public route and sidecar;
- keep recall profiles in one tool instead of publishing a separate smart-recall tool;
- return evidence/provenance only to the degree supported by the selected profile;
- ensure response size is bounded.

### 7.3 `revise`

Inputs:

- `key: str`, required;
- `value: JSON`, required;
- `importance: float`, default `1.0`;
- `strategy: entrenchment | recency | verification | importance`, default aligned with local behavior;
- `reason: str | null`;
- `expected_version: str | null`;
- `idempotency_key: str | null`.

Behavior:

- require the memory to exist;
- preserve AGM conflict handling and audit history;
- return `404 memory_not_found` when absent;
- return `409 version_conflict` when `expected_version` is stale;
- use the existing `memory_write` entitlement/credit path;
- a duplicate idempotency key with the same payload returns the original result;
- the same idempotency key with a different payload returns `409 idempotency_conflict`.

### 7.4 `forget`

Inputs:

- `key: str`, required;
- `reason: str`, required for Cloud;
- `expected_version: str | null`;
- `idempotency_key: str | null`.

Behavior:

- remove the memory from active recall immediately;
- retain an audit-safe deletion receipt according to existing retention policy;
- do not promise regulatory erasure; privacy erasure is a separate admin lifecycle;
- never echo the deleted value in the public response or logs;
- return `404 memory_not_found` when absent unless an identical idempotent request already succeeded;
- use the existing `memory_write` entitlement/credit path.

### 7.5 `status`

Authenticated response:

- API/package contract version;
- service readiness without private topology;
- organization/workspace/project identifiers in the minimum useful form;
- plan key and entitlement state;
- trial/entitlement end time when applicable;
- supported Cloud MCP tools;
- supported recall profiles;
- usage limits and current usage where already available;
- purchased/included credit summary where already available;
- API key prefix or ID metadata only, never the raw key;
- capabilities object with booleans for revise, forget, snapshots, diff, rollback;
- request ID.

Do not expose:

- database paths;
- VM names;
- sidecar URL/token;
- Stripe identifiers or secrets;
- raw entitlement SQL/source details;
- other projects in the organization unless the API key is explicitly authorized for them.

### 7.6 `snapshot`

MCP/SDK interface:

- `action: create | list`, default `create`;
- `label: str | null` for create;
- `metadata: object | null` for create;
- `limit: int` for list.

Behavior:

- generate collision-resistant IDs for new snapshots;
- keep existing timestamp-derived snapshots readable;
- store project ID only through the server-side project boundary, never from public input;
- return metadata, root hash, entry counts, and creation time;
- do not return the entire snapshot payload by default;
- list is not billed; create uses the existing snapshot event.

### 7.7 `diff`

Inputs:

- `from_snapshot_id: str`, required;
- `to_snapshot_id: str | null`; null means current state;
- `include_values: bool`, default false;
- `limit: int`, bounded.

Behavior:

- return added/modified/removed keys and counts;
- values are redacted by default;
- if values are requested, enforce response-size bounds and current project authorization;
- a snapshot from another project returns `404 snapshot_not_found`;
- diff is read-only and does not reserve credits in this sprint.

### 7.8 `rollback`

This is a two-stage operation under one MCP name and two HTTP endpoints.

Preview inputs:

- `mode: preview`;
- `snapshot_id: str`;
- `reason: str`, required.

Preview response:

- bounded diff summary;
- current root hash;
- target root hash;
- counts of records to create/update/remove;
- opaque, one-time confirmation token;
- token expiry;
- explicit warning that execute is destructive.

Execute inputs:

- `mode: execute`;
- `snapshot_id: str`;
- `confirmation_token: str`;
- `reason: str`;
- `idempotency_key: str | null`.

Execute behavior:

- require a valid preview token bound to project, snapshot, current root, and reason;
- expire tokens after a short bounded interval;
- reject reused tokens unless the identical idempotent execution already succeeded;
- return `409 state_changed_since_preview` if the current root changed;
- record the rollback reason and affected-key counts in the audit trail;
- never return restored/deleted values;
- use the existing rollback entitlement and credit path only on successful execution;
- release any credit reservation on failure.

## 8. Compatibility and response rules

### 8.1 Existing clients

- Existing `commit`, `recall`, and `status` command names must remain.
- Existing successful commit/recall top-level fields must remain readable.
- Additive metadata belongs under `_meta` where possible:
  - `requestId`
  - `idempotencyKey`
  - `apiVersion`
  - `projectId` only when safe
- Do not wrap existing payloads in a new top-level `data` object in this sprint.

### 8.2 Errors

Keep the existing top-level string `error` for compatibility and add:

- `message`
- `requestId`
- `retryable`
- `details` only when public-safe.

Canonical public error codes must include:

- `missing_api_key` -> 401
- `invalid_api_key` -> 401
- `entitlement_inactive` or existing equivalent -> 403
- `capability_not_entitled` -> 403
- `payment_required` -> 402
- `invalid_request` plus specific validation code -> 400
- `memory_not_found` -> 404
- `snapshot_not_found` -> 404
- `version_conflict` -> 409
- `idempotency_conflict` -> 409
- `state_changed_since_preview` -> 409
- `rollback_confirmation_expired` -> 410
- `rate_limited` -> 429
- `cloud_runtime_unavailable` -> 503

Do not return raw exception text from the sidecar to public callers. Log an allowlisted error code plus request ID; never log credentials or full memory payloads.

## 9. Architecture decisions

### 9.1 Preserve the package boundary

Internal Cloud runtime modules may change, but the public wheel/sdist must still include only the public SDK, CLI, and MCP adapter packages. Artifact tests must explicitly deny:

- `bilinc/core`
- `bilinc/storage`
- `bilinc/eval`
- `bilinc/observability`
- `bilinc/integrations`
- `bilinc/mcp_server`
- `bilinc/adaptive`
- `bilinc/retrieval`
- `bilinc/security`
- `bilinc/jobs`
- `bilinc/cloud`

### 9.2 No historical dual-write resurrection

Do not restore `_add_cloud_sync`, monkey-patch the local backend, or perform synchronous Cloud writes inside local persistence. The former prototype could swallow errors, duplicate writes, and blur local/Cloud authority.

This sprint makes the hosted API complete enough for future native providers. A standalone Hermes provider is a separate sprint.

### 9.3 Mutation idempotency

Billing idempotency is not sufficient. Persist a project-scoped mutation receipt containing:

- idempotency-key hash;
- operation;
- normalized request hash;
- completion status;
- safe response/result hash;
- created/updated time;
- bounded expiry/retention.

Required behavior:

- first request executes once;
- concurrent duplicate waits for or reads the same terminal result;
- same key and same normalized payload returns the original safe response;
- same key and different payload returns `409 idempotency_conflict`;
- failed non-terminal attempts can be retried according to a documented state machine;
- secrets and full values are not stored in the control-plane receipt.

Do not add automatic mutation retries to the SDK until this acceptance gate passes.

### 9.4 Concurrency

Return an opaque entry/state version after mutation and recall where practical. `revise` and `forget` accept optional optimistic concurrency. Rollback requires a current-root match even when the caller does not supply an entry version.

### 9.5 Tenant isolation

Every public identifier is resolved inside the project authorized by the bearer key. Never query an object globally and then compare project ownership afterward. Cross-project probes must return the same not-found behavior as nonexistent objects.

### 9.6 Billing and credits

For billable mutations:

1. validate the public payload before reserving;
2. authorize API key and entitlement;
3. reserve credits with the request idempotency key;
4. execute exactly one runtime mutation;
5. record usage only after durable success;
6. release reservation on any failure;
7. do not double-record on duplicate success.

Free read paths must not reserve credits.

### 9.7 Status versus health

- Health answers “is the service reachable?”
- Status answers “what can this authenticated key/workspace do?”

Keep these separate throughout SDK, CLI, MCP, docs, tests, and monitoring.

## 10. Work plan: vertical slices

Each slice must be independently testable and leave the previous public surface working.

### Slice 0 — Preflight and contract freeze

**Type:** AFK  
**Blocked by:** None

1. Verify both repository roots, remotes, branches, status, and current tests.
2. The Bilinc repository was clean at planning time. Create a focused branch such as `claude/bilinc-cloud-local-core-parity`.
3. The site repository was dirty at planning time. Do not edit the original working tree.
4. Create an isolated named site worktree under `/Users/busecimen/Downloads/Projeler/.worktrees/` from the latest canonical `origin/main`.
5. Record the current public SDK/MCP schemas as contract fixtures.
6. Add failing tests for the target eight-tool Cloud MCP surface without implementing the tools yet.
7. Add a short implementation receipt section to this plan with actual starting SHAs and drift.

**Exit gate:** clean implementation worktrees, frozen current contracts, red tests for intended additive behavior.

### Slice 1 — Split public health from authenticated status

**Type:** AFK  
**Blocked by:** Slice 0

1. Add authenticated `/api/cloud/status`.
2. Build its response only from existing grant, entitlement, usage, and capability sources.
3. Keep `/api/cloud/health` unchanged for monitoring.
4. Add `CloudClient.health()`.
5. Move `CloudClient.status()` to authenticated status.
6. Update CLI status output and Cloud MCP status.
7. Ensure missing key fails cleanly for status while health remains public.

**Exit gate:** health and status tests prove their separate contracts; no secret/internal topology leakage.

### Slice 2 — Harden existing commit and recall contracts

**Type:** AFK  
**Blocked by:** Slice 1

1. Centralize validation and error translation.
2. Resolve the 100-versus-50 recall-limit mismatch.
3. Add additive metadata fields to responses.
4. Pass richer commit metadata through the control plane and sidecar.
5. Add request IDs.
6. Normalize public-safe sidecar errors.
7. Add real mutation idempotency before enabling automatic write retries.
8. Add bounded read retries only for retryable transport/5xx failures.

**Exit gate:** old SDK examples pass; duplicate commit executes once; same idempotency key with different payload returns 409; no double billing.

### Slice 3 — Snapshot public exposure

**Type:** AFK  
**Blocked by:** Slice 2

1. Harden snapshot identifiers and metadata.
2. Keep old snapshot files readable.
3. Add SDK `snapshot()` create/list behavior.
4. Add CLI snapshot create/list commands using existing CLI style.
5. Add Cloud MCP `snapshot`.
6. Ensure list is free and create is billed once.
7. Ensure full snapshot contents are not returned by default.

**Exit gate:** SDK, CLI, MCP, route, sidecar, usage, and cross-tenant tests pass.

### Slice 4 — Explicit revise and forget lifecycle

**Type:** AFK  
**Blocked by:** Slice 2

1. Add runtime and sidecar revise behavior using existing AGM machinery.
2. Add runtime and sidecar forget behavior using the existing audit/event model.
3. Add public routes with authorization, entitlements, credits, idempotency, and conflict handling.
4. Add SDK, CLI, and MCP methods/tools.
5. Require a reason for Cloud forget.
6. Do not expose deleted values.

**Exit gate:** behavior is equivalent across direct sidecar tests, public route tests, SDK tests, CLI tests, and MCP schema/handler tests.

### Slice 5 — Read-only snapshot diff

**Type:** AFK  
**Blocked by:** Slice 3

1. Resolve snapshots only inside the authorized project.
2. Support snapshot-to-current and snapshot-to-snapshot diff.
3. Redact values by default.
4. Add bounded optional value output.
5. Add SDK, CLI, and MCP interfaces.
6. Do not bill or reserve credits.

**Exit gate:** deterministic diff tests cover add/update/remove, empty diff, corrupted snapshot, oversized response, and cross-project probing.

### Slice 6 — Two-stage rollback

**Type:** HITL before public release; implementation may proceed locally  
**Blocked by:** Slices 3 and 5

1. Add preview and execute flow.
2. Bind confirmation to project, snapshot, current state root, reason, and expiry.
3. Ensure execute is one-time and idempotent.
4. Add a current-root concurrency check.
5. Add SDK `rollback_preview()` and `rollback()` or an equally clear typed interface.
6. Add CLI commands with an explicit confirmation argument; no interactive prompt in automation mode.
7. Add MCP `rollback` with `mode=preview|execute`.
8. Meter only successful execution.

**Exit gate:** destructive E2E test in a disposable project proves exact restoration, preserved audit receipt, no cross-project access, no stale-preview execution, and no double billing.

### Slice 7 — Public package and MCP parity

**Type:** AFK  
**Blocked by:** Slices 1-6

1. Expose all eight lifecycle capabilities in `CloudClient`.
2. Preserve `Bilinc` alias behavior.
3. Expose exactly eight Cloud MCP tools.
4. Keep MCP server construction lazy so import does not require an API key.
5. Require the API key only when building/using the client as current package behavior dictates.
6. Keep human-readable CLI errors free of tracebacks and secrets.
7. Update package tests, wheel/sdist allowlist, and clean-venv smoke.
8. Do not decide the release version in code until release approval.

**Exit gate:** public artifact remains Cloud-only and a clean install can exercise all non-destructive mock flows.

### Slice 8 — Docs and public-truth synchronization

**Type:** AFK locally; deployment is gated  
**Blocked by:** Slice 7

Work only in the isolated site worktree.

1. Update the canonical product-truth module to list the eight supported Cloud MCP tools.
2. Update:
   - API reference;
   - Python SDK;
   - MCP docs;
   - quickstart;
   - snapshots/rollback docs;
   - operations;
   - errors;
   - entitlements;
   - production checklist;
   - migration page;
   - changelog draft;
   - `llms.txt`;
   - `llms-full.txt`;
   - `ai-index.json`;
   - JSON-LD/FAQ claims where affected.
3. Keep the current published version until a new package is actually published.
4. Do not claim advanced epistemic tools.
5. Explain destructive rollback as preview plus explicit execution.
6. Update docs smoke to execute SDK/CLI examples against a local mock server.
7. Add a claim test that public docs and product truth agree on tool count and names.

**Exit gate:** typecheck, tests, docs smoke, build, and public-claim checks pass with no version fiction.

### Slice 9 — Release-candidate evidence

**Type:** HITL  
**Blocked by:** Slices 0-8

1. Re-run every test from clean worktrees.
2. Build wheel and sdist.
3. Run artifact leak inspection.
4. Install wheel in a fresh environment with `PYTHONPATH` unset.
5. Run SDK, CLI, and MCP mock smokes.
6. Run site tests/typecheck/build/docs smoke.
7. Produce:
   - changed-file inventory;
   - API contract diff;
   - database migration inventory;
   - security/tenant-isolation evidence;
   - billing/idempotency evidence;
   - rollback evidence;
   - package artifact manifest;
   - deployment and rollback notes without secrets.
8. Stop before push, PR, PyPI publish, database migration, VM deploy, or public-site deploy.

**Exit gate:** one review packet lets Atakan approve or reject each external side effect separately.

## 11. Required test architecture

Test externally visible behavior at the highest stable seam. Do not assert private helper implementation unless required for a security invariant.

### 11.1 Package repository tests

Add or extend focused tests for:

- `ProjectRuntimeManager` lifecycle operations;
- sidecar API request validation and error mapping;
- project isolation;
- snapshot compatibility;
- revise/forget audit behavior;
- diff correctness;
- rollback preview/execute;
- state-root conflict;
- mutation idempotency;
- public `CloudClient` method, path, method, body, headers, timeout, and error behavior;
- CLI subcommands and safe exit codes;
- exact Cloud MCP tool names and schemas;
- missing-key behavior;
- public artifact leakage.

### 11.2 Site/control-plane tests

Add route/repository tests for:

- missing, invalid, revoked, and expired keys;
- inactive entitlement;
- plan capability denial;
- payment-required response;
- validation before credit reservation;
- one reservation and one usage event per successful idempotent mutation;
- reservation release after runtime failure;
- no charge for list/diff/rollback preview/status;
- charge once for snapshot create and rollback execute;
- cross-project snapshot and rollback probes;
- sidecar timeout and unavailable behavior;
- public-safe error normalization;
- request ID propagation.

### 11.3 Concurrency and failure tests

At minimum:

1. Two concurrent requests with the same idempotency key and payload.
2. Two concurrent requests with the same key and different payload.
3. Sidecar succeeds but usage recording transiently fails.
4. Credit reservation succeeds but sidecar fails.
5. Client disconnects after durable sidecar success.
6. Rollback preview followed by an intervening commit.
7. Rollback confirmation token reuse.
8. Expired confirmation token.
9. Corrupted snapshot file.
10. Missing snapshot file.
11. Oversized value/metadata/diff response.
12. Cross-project identifier probing.

For every ambiguous partial-failure case, document the authoritative state and retry behavior. Do not hide ambiguity behind a generic 500.

## 12. Security and privacy checklist

- [ ] Bearer API keys are never logged.
- [ ] Sidecar tokens are never logged or returned.
- [ ] Full memory values are absent from normal logs and usage receipts.
- [ ] Idempotency storage uses hashes, not raw payloads.
- [ ] Snapshot paths cannot escape the normalized project directory.
- [ ] Snapshot IDs cannot be used across projects.
- [ ] Rollback confirmation cannot be replayed across projects or state roots.
- [ ] All destructive operations require explicit reason and arguments.
- [ ] Public errors do not reveal internal filesystem, SQL, VM, or sidecar details.
- [ ] No endpoint trusts a public project or organization ID.
- [ ] Response sizes and list limits are bounded.
- [ ] Public package still excludes internal runtime code.
- [ ] Existing API-key and entitlement boundaries remain authoritative.
- [ ] Secret scanning finds no credential pattern in changed files, fixtures, logs, or receipts.

## 13. Definition of done

The sprint is complete only when all statements are true:

1. Existing commit/recall users remain compatible.
2. `CloudClient.status()` returns authenticated capability/account status.
3. Public service health remains separately available.
4. Cloud SDK and MCP expose exactly eight lifecycle capabilities.
5. Revise and forget preserve audit-safe state transitions.
6. Snapshot create/list is exposed and project isolated.
7. Diff is available without exposing values by default.
8. Rollback requires preview, explicit confirmation, and unchanged current root.
9. Mutation idempotency prevents duplicate state changes, not only duplicate billing.
10. Every billable successful operation is recorded once.
11. Every failed operation releases any credit reservation.
12. Cross-tenant tests pass for every identifier-bearing route.
13. Public wheel and sdist remain Cloud-only.
14. Clean-venv package, CLI, and MCP smokes pass with `PYTHONPATH` unset.
15. Site product truth, docs, LLM routes, and code examples match the implementation.
16. No public version is changed before package release.
17. No production side effect occurred without explicit approval.
18. The implementation branch contains a concise evidence receipt.

## 14. Verification commands

Use repository-native commands. Adjust only when the repository itself documents a different command.

### Bilinc package repository

```bash
cd "/Users/busecimen/Downloads/Projeler/Agent/Bilinc"

python3 -m pytest -q -o 'addopts=' \
  tests/test_cloud_runtime.py \
  tests/test_cloud_service.py \
  tests/test_cloud_usage.py \
  tests/test_cloud_only_package.py \
  tests/test_cli_error_paths.py

python3 -m pytest -q -o 'addopts='
python3 -m ruff check src tests
python3 -m build
```

Artifact inspection must list wheel and sdist files and fail on every forbidden prefix.

Clean install smoke:

```bash
tmp_venv="$(mktemp -d)/venv"
python3 -m venv "$tmp_venv"
env -u PYTHONPATH "$tmp_venv/bin/python" -m pip install --upgrade pip
env -u PYTHONPATH "$tmp_venv/bin/python" -m pip install dist/*.whl
env -u PYTHONPATH "$tmp_venv/bin/python" -c \
  'import bilinc; from bilinc import CloudClient; print(bilinc.__version__)'
env -u PYTHONPATH "$tmp_venv/bin/bilinc" --version
env -u PYTHONPATH "$tmp_venv/bin/bilinc" --help
```

Do not call authenticated production mutation endpoints during routine tests.

### Bilinc site/control plane

```bash
cd "<isolated-bilinc-site-worktree>"

npm test
npm run test:public-claims
npm run docs:verify-code-smoke
npm run cloud:verify-phase5-limits
npm run cloud:verify-credits
npx tsc --noEmit
npm run lint
npm run build
```

Add a focused parity verification script if existing tests cannot prove route, SDK, MCP, metering, and claim synchronization in one deterministic local run.

## 15. Commit strategy

Use:

```text
Atakan Elik <atakan@rearclabs.com>
```

Suggested commits:

1. `test: freeze Bilinc Cloud lifecycle contracts`
2. `feat: add authenticated Cloud capability status`
3. `fix: harden Cloud commit and recall contracts`
4. `feat: expose Cloud snapshots`
5. `feat: add Cloud revise and forget lifecycle`
6. `feat: add snapshot diff`
7. `feat: add guarded Cloud rollback`
8. `feat: expand Cloud SDK CLI and MCP lifecycle`
9. `docs: sync Bilinc Cloud lifecycle truth`
10. `test: add Bilinc Cloud parity release evidence`

Do not combine package and site changes into one repository commit. Do not push or open PRs without explicit approval.

## 16. Stop conditions and approval gates

Stop and report before:

- changing plan prices, quotas, credit costs, or top-up amounts;
- changing Stripe or any payment provider setting;
- changing the memory backend or project isolation model;
- changing deployment target or production VM configuration;
- applying production database migrations;
- publishing a PyPI version;
- pushing branches or opening/merging PRs;
- deploying `bilinc.space`;
- enabling advanced epistemic tools publicly;
- deleting customer memory, snapshots, keys, usage, or billing records;
- printing or copying any secret value.

If a strategy ambiguity appears, preserve current behavior and produce a decision note. Do not silently choose a broader product policy.

## 17. Final implementation report format

Return:

### A. State

- starting and final branch/SHAs;
- worktree status;
- commits created;
- whether any side effect gate remains closed.

### B. Implemented lifecycle

- exact SDK methods;
- exact CLI commands;
- exact MCP tools;
- exact public/internal routes;
- compatibility notes.

### C. Security and billing proof

- tenant isolation tests;
- idempotency tests;
- reservation/usage tests;
- destructive rollback tests;
- secret scan result.

### D. Package proof

- pytest and Ruff results;
- wheel/sdist contents;
- clean install result;
- public boundary result.

### E. Site proof

- tests;
- typecheck;
- lint;
- build;
- docs smoke;
- product-truth/LLM-route sync.

### F. Remaining decisions

- approval gates;
- known residual risks;
- recommended next sprint.

## 18. Explicit next sprint boundary

After this core lifecycle sprint is accepted, create a separate sprint for:

- `verify`
- `claims_search`
- `claim_contradictions`
- `query_graph`
- standalone `hermes-bilinc-memory` Cloud provider
- queued/non-blocking Hermes turn capture
- local-only, cloud-only, and hybrid privacy modes
- provider-specific retention and consent UX

Do not pull those concerns into this implementation unless Atakan explicitly expands the scope.

## 19. Implementation receipt

### 19.1 Starting state (verified 2026-07-30)

| Repository | Path | Start SHA | Start branch | Working tree |
|---|---|---|---|---|
| Bilinc package | `/Users/busecimen/Downloads/Projeler/Agent/Bilinc` | `410204a` | `main` | clean (plan file untracked) |
| Bilinc site | `/Users/busecimen/Downloads/Projeler/bilinc-site 2` | `57ec208` | `main` | dirty — **not touched** |

Implementation branches:

- Package: `claude/bilinc-cloud-local-core-parity` from `410204a`.
- Site: `claude/bilinc-cloud-local-core-parity` from `origin/main` (`57ec208`), checked out in the
  isolated worktree `/Users/busecimen/Downloads/Projeler/.worktrees/bilinc-site-cloud-parity`.
  The original dirty site working tree was never modified.

### 19.2 Baseline verification

```
PYTHONPATH=src python3 -m pytest -q -o 'addopts=' \
  tests/test_cloud_runtime.py tests/test_cloud_service.py tests/test_cloud_usage.py \
  tests/test_cloud_only_package.py tests/test_cli_error_paths.py
24 passed, 2 skipped
```

### 19.3 Drift from the planning-time baseline

1. **Test invocation.** A published `bilinc` wheel is installed in the system interpreter and
   shadows `src/`. Internal-runtime tests only import `bilinc.cloud` when run with
   `PYTHONPATH=src`. Section 14's commands are therefore run as `PYTHONPATH=src python3 -m pytest …`
   for internal tests, and with `PYTHONPATH` unset for the public-artifact smoke.
2. **Site test runner.** `npm test` covers `tests/auth`, `tests/docs`, `tests/promotions`, and
   `tests/public` only. There is no existing `tests/cloud` lane, so this sprint adds one and wires
   it into `npm test`.
3. **`lib/cloud/runtime.ts`** is a one-line re-export shim, not a runtime module. The real
   control-plane runtime seam is `lib/cloud/runtime-access.ts`.
4. Everything else in section 4 matched the code as written.

### 19.4 Contract freeze

`tests/test_cloud_lifecycle_contract.py` freezes the eight-tool MCP surface, the SDK lifecycle
methods, route paths, destructive-tool schema requirements, and the canonical error-code table.
It was red on 25 of 29 assertions before implementation began.
