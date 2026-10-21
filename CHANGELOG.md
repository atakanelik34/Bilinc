# Changelog

All notable changes to Bilinc.

## [2.5.0] — 2026-10-21

### Added

- `forget(..., purge=True)` (SDK), `bilinc forget --purge` (CLI) and `"purge": true` on the hosted forget route remove a memory and also remove its stored values from the audit trail and from every snapshot of the workspace. This also works on a memory that was forgotten earlier and cannot be undone. The audit hash chain keeps verifying: a new PURGE receipt in the chain lists every emptied row, and verification accepts an emptied row only when a later receipt names it. Key names and value hashes remain, so this is removal from storage and history, not cryptographic erasure. The SDK raises if the server does not confirm a requested purge.
- Internal runtime: `DELETE /v1/projects/{project_id}` removes a workspace's schema or database, snapshots and files for the control plane's deletion schedule. It is refused unless `BILINC_PURGE_ENABLED` is on and supports `?dry_run=true`. Capabilities `memory_purge` and `project_purge`.

### Security

- Hosted writes are scanned for secrets before anything is stored. A `commit` or `revise` whose key, value, metadata, source, session ID or reason contains a provider-shaped credential (AWS, GitHub, GitLab, Slack, Stripe live, Anthropic, OpenAI, Google API, PyPI and Bilinc keys, JWTs, PEM private keys) is rejected with `secret_detected` (HTTP 422), and the response never echoes the value. Credential fields whose value looks generated (`password=…` or `Authorization: Bearer …` followed by letters mixed with digits, or a long mixed-case string; a dict key such as `api_key`) are replaced with `[REDACTED]` and reported in a `warnings` list; a plain-word value is left as written. Operator notes (the reasons given to `forget`, `confirm` and `rollback`, and snapshot labels and metadata) are masked the same way but never refused, so a memory can always be removed or restored. Documentation examples, placeholders, paths and prose are left alone. The runtime advertises this as the `secret_scan` capability; `BILINC_SECRET_SCAN=off` turns it off.

### Fixed

- Hosted recall (PostgreSQL backend) now ranks with full-text search. Each entry keeps a `tsv` column built from its decoded key, value and allowlisted metadata, so Turkish and other non-ASCII words are found even though values are stored as escaped JSON. Queries OR their content words, as the local FTS5 path does, and the best match comes first; the old `fts_search` ordered matches worst-first and was never called. The ranking fills the existing hybrid slot of `recall_intelligent`, so the fusion weights and the `explain` fields are unchanged. Schema version 2 adds the nullable column and a GIN index without rewriting the table, and fills existing rows once, in batches, the first time each tenant loads.
- Local full-text recall no longer splits words that start with the Turkish dotted capital I: `İstanbul` was searched as `i` and `stanbul`.
- The audit trail is described as what it is, a linear SHA-256 hash chain, not a Merkle chain.

## [2.4.1] — 2026-10-19

### Added

- Internal runtime: the hosted memory list (`POST /v1/projects/{project_id}/memories`) takes an optional `sources` filter, so the Bilinc Cloud dashboard can show only the memories a given app or source saved. It matches the effective source exactly (the stored source, else a string `metadata.source`; `""` selects memories with no source), runs inside the storage query on SQLite and PostgreSQL so the page, `total` and `next_cursor` all respect it, and accepts 1–20 values of at most 256 characters. The runtime advertises it as the `memory_list_source` capability.

### Fixed

- Align the SDK, CLI, PyPI package, hosted website and MCP Registry release versions at 2.4.1. The public SDK API and protocol contracts are unchanged; the PyPI package still ships only the cloud SDK, CLI and MCP adapter.
- Internal runtime: the memory list, history and recall report the same effective source the new filter matches; a `metadata.source` that is not a string now reads as no source instead of being passed through.

## [2.4.0] — 2026-10-19

### Added

- Internal runtime: `bilinc.integrations.distill.commit_distilled` stores an exchange as an episodic source and each fact an agent distils from it as its own semantic memory that points back to the source, with the same timestamp. `recall_reflective(expand_sources=True)` attaches that source to each fact result. Searching distilled facts fits far more of a long conversation into a fixed recall budget while keeping the original wording one step away. A source is attached only when the recall could return it itself (not forgotten, invalidated, superseded, or later than an as-of time), and committing a source again replaces its facts, cleaning up after an earlier interrupted commit. Source keys ending in `#f<n>` are rejected because that is the fact key space.
- Internal runtime: opt-in recency tie-breaking for as-of recall. With `BILINC_RECALL_RECENCY_FUSION=1`, a recall that carries a `query_timestamp` orders near-equal matches newest first, so a question asked at a point in time sees the value that was current then. Relevance order between clearly different matches is unchanged. Off by default.
- Internal runtime: opt-in cross-encoder reranking. `BILINC_RERANK_MODEL` names a local Sentence Transformers cross-encoder; at most the top `BILINC_RERANK_DEPTH` results (default 100), and no more than five per requested result (at least 20), are rescored against the memory content and the query. Scores are the model's raw logits for every model. The current-state and latest-version preferences still apply afterwards, scores follow the final order, a reordered result reports its own fused score in `signals.fused` and the reason in `reordered_by`, and scoring runs off the event loop, one batch at a time per model. `BILINC_RERANK_DEVICE` and `BILINC_RERANK_MODEL_REVISION` are optional. Off by default; if the model cannot be loaded, recall keeps the fused order, logs a warning and retries later.

### Fixed

- Align the SDK, CLI, PyPI package, hosted website and MCP Registry release versions at 2.4.0. The public SDK API and protocol contracts are unchanged; the PyPI package still ships only the cloud SDK, CLI and MCP adapter.
- Internal runtime (SQLite): removing a memory's entity mentions no longer sweeps every entity against every mention to find orphans. Only the entities those mentions pointed at are checked, so writes stay constant-time as a store grows instead of slowing ingest quadratically. Rewriting a memory keeps the entities it still mentions, with their aliases. Each database is swept once for orphans left by older versions (entities saved or relinked in the last hour are kept, since another process may be linking them); rollback and snapshot restore keep entity aliases too; `SQLiteBackend.sweep_orphan_entities()` runs the sweep again on demand.

## [2.3.11] — 2026-10-16

### Fixed

- Align the SDK, CLI, PyPI package, hosted website and MCP Registry release versions at 2.3.11. The public SDK API and protocol contracts are unchanged.
- Internal runtime: keyword recall sends every distinct question term to FTS5 (up to 64) instead of only the first ten, so questions that open with conversational filler still match on their content words.

## [2.3.10] — 2026-10-16

### Fixed

- Align the SDK, CLI, PyPI package, hosted website and MCP Registry release versions at 2.3.10. The public SDK API and protocol contracts are unchanged.
- Internal runtime: "latest/current" recall now returns the newest entry of a key family instead of an older sibling or a stale status entry.
- Internal runtime: the decay pass no longer crashes on ISO text timestamps or malformed decay metadata, no longer rewrites `updated_at`, and counts elapsed time from its previous run. The scheduled decay job no longer prunes.

## [2.3.9] — 2026-10-09

### Changed

- Align the SDK, CLI, PyPI package, hosted website and MCP Registry release versions at 2.3.9. The SDK API, storage and protocol contracts are unchanged.
- Hosted website: clearer page titles and descriptions, links from the home page to the comparison and guide pages, and structured data that names Bilinc's public profiles.
- README: the stdio adapter has eleven tools.

## [2.3.8] — 2026-10-08

### Added

- Review what Bilinc remembers. Bilinc Cloud can list the memories a project stores (ordered by key, with prefix, memory type and updated-time filters, page by page with a total count), show one memory's recorded changes newest first with the value before and after, and confirm that a memory is still accurate without resending its value. Listing and history are reads and are not billed; confirming costs one write.
- History never returns values recorded before a memory was forgotten; it still shows that the change happened and the recorded reason.
- SDK: `CloudClient.list_memories()`, `iter_memories()`, `history()`, `confirm()` and `export()`, which returns every stored memory with its full value.
- CLI: `bilinc list`, `bilinc history`, `bilinc confirm` and `bilinc export` (`-o` writes a file readable only by its owner).
- MCP adapter: `list_memories` and `history` (read-only) and `confirm`, with read-only and destructive hints on each.
- The SDK publishes the `memory_exists` and `capability_unavailable` error codes, which Bilinc Cloud already returns.

### Changed

- The MCP adapter needs `mcp` 1.10.0 or newer (tool titles and annotations).
- The website dashboard can browse a workspace's memory read-only and export it as JSON.
- Align the SDK, CLI, PyPI package, hosted website and MCP Registry release versions at 2.3.8.

## [2.3.7] — 2026-10-08

### Changed

- Align the SDK, CLI, PyPI package, hosted website and MCP Registry release versions at 2.3.7. The SDK API, storage and protocol contracts are unchanged.
- Hosted website server package security updates.
- The PyPI project page lists the hosted connector's ten tools and links pricing.

## [2.3.6] — 2026-10-07

### Changed

- Align the SDK, CLI, PyPI package, hosted website and MCP Registry release versions at 2.3.6. The SDK API, storage and protocol contracts are unchanged.
- Bilinc Cloud re-checks AWS Marketplace subscriptions every hour, so a renewal or cancellation made in AWS reaches the Bilinc plan even if a notification is missed.
- Hosted website server package security updates.

## [2.3.5] — 2026-10-07

### Changed

- Align the SDK, CLI, PyPI package, hosted website and MCP Registry release versions at 2.3.5. The SDK API, storage and protocol contracts are unchanged.
- The hosted connector's consent screen names an app that registered itself by the site it returns to and marks it as unverified, so a misleading app name cannot pass for Claude. Connected apps shows each app's site.
- Hosted website dependency security updates.

## [2.3.4] — 2026-10-06

### Added

- Recall in the hosted Claude connector shows how long ago each memory was last written or confirmed, and marks entries past their review window as possibly outdated. The default window is 90 days for facts, decisions, how-tos and places, and 1 day for working notes; episodic memories (events) are never marked, and at most three entries are marked per recall. Nothing is hidden or deleted, and revising a memory with the same value confirms it. The structured recall result gains `age_days`, `freshness` and `review_window_days`.

### Changed

- Align the SDK, CLI, PyPI package, hosted website and MCP Registry release versions at 2.3.4. The SDK API, storage and protocol contracts are unchanged.
- Add a runtime test that a same-value `revise` refreshes `updated_at` and keeps `created_at`, which is what the confirmation relies on.

## [2.3.3] — 2026-10-06

### Changed

- Align the SDK, CLI, PyPI package, hosted website and MCP Registry release versions at 2.3.3.
- Document the no-install Claude remote connector alongside the eight-tool Python stdio adapter, with user-wide Claude Code setup.
- Refresh release instructions and current public documentation; SDK client/version attribution identifies 2.3.3.

### Hosted website fixes

- Keep safe campaign and external-referrer context on copy and setup interactions.
- Respect measurement consent when old attribution cookies remain present.
- Exclude owner/team testing from activation reporting without granting additional dashboard access or altering billing records.

## MCP Registry 2.3.2 — 2026-10-05 (registry metadata only; the PyPI package stays 2.3.1)

- `server.json` adds the hosted remote MCP server, `https://mcp.bilinc.space/mcp` (Streamable HTTP, OAuth 2.1), next to the existing PyPI package, so registries list the no-install connector.
- The registry version is `2.3.2` because a prerelease such as `2.3.1-1` would not become "latest". The next PyPI release must therefore be `2.3.3` or later, or the registry will refuse its `server.json`.

## [2.3.1] — 2026-09-28

### Fixed

- `bilinc mcp install` now prints a config that works right after `bilinc login`. `command` is the absolute interpreter that has Bilinc installed — a bare `python` is missing on macOS and from Claude Desktop's PATH — and there is no `env` block when a key is saved, because the adapter reads the saved key itself. It used to write `"BILINC_API_KEY": "${BILINC_API_KEY}"`, which clients that do not expand variables passed through literally.

### Added

- `bilinc mcp install --client claude-code` prints a ready `claude mcp add --scope user bilinc -- ...` command. `--client claude-desktop` prints the config and where Claude Desktop keeps it.

## [2.3.0] — 2026-09-25

### Added

- One-click `bilinc login`: opens the browser, signs in with Google, GitHub, or email on bilinc.space, and saves an API key for this computer. It uses a loopback redirect to `127.0.0.1` with PKCE (RFC 8252, RFC 7636); the key travels only in an HTTPS response body, never in a URL.
- `bilinc login --device` for machines without a browser: approve a short code from any browser (RFC 8628).
- `--no-browser` prints the sign-in URL instead of opening a browser. `bilinc login --api-key` still saves a key directly for CI.

### Changed

- First-run guidance, `bilinc signup`, and the missing-key error point to `bilinc login` and the permanent free tier (free, no card required). The retired 7-day trial wording is gone.
- The saved CLI config is created owner-only (`0600`, directory `0700`) from the first write, instead of being chmod-ed after it.
- The activation campaign moves to `activation_2_3_0`.

### Internal runtime (source tree only, not in the wheel)

- Fixed cross-process belief staleness when several agents share one Bilinc database.

## [2.2.0] — 2026-08-11

### Added

- Added a deterministic, provenance-first, read-only Graph Doctor and projection preview for the internal StatePlane runtime.
- Added preview evidence for duplicate, stale, secret-like, and provenance integrity checks without graph backfill or mutation.

### Fixed

- Kept source-only runtime modules out of the public wheel while preserving the internal runtime source tree.
- Redacted password-less PostgreSQL database paths from health and stats output as well as credential-bearing DSNs.
- Verified the full release suite with package artifacts and PostgreSQL/pgvector integration enabled.

## [2.1.9] — 2026-08-06

### Changed

- Promoted conservative lexical inflection recall with exact-form precedence and a bounded event-time metadata surface.
- Current-state recall now collapses only a singular explicit state topic to its newest evidence while preserving multi-topic evidence and historical `include_stale` queries.
- Preserved the cloud-only public package boundary and synchronized the SDK, CLI, MCP server manifest, and activation campaign to 2.1.9.

## [2.1.8] — 2026-08-04

### Changed

- Hosted recall now defaults to the current valid state: expired, future-dated, and superseded entries are excluded from normal recall while audit callers can explicitly request stale history.
- Preserved memory-type scope across lexical, hybrid, and optional semantic candidate paths.
- Added neutral Cloud-runtime and retrieval regression coverage for the current-state contract.
- Corrected the public LongMemEval receipt to the frozen verified values: Hit@5 98.0% and NDCG@5 0.913.

## [2.1.7] — 2026-08-03

### Activation telemetry

- Align the CLI activation campaign with the 2.1.7 release.
- Identify SDK and CLI runtime calls with safe client/version headers.
- Mark `bilinc quicktest` commit and recall calls for hosted activation reporting.
- Clarify that email confirmation provisions the first hosted key for onboarding.

## [2.1.6] — 2026-07-30

### Added
- The Cloud MCP adapter and SDK now expose the full core memory lifecycle: `revise`, `forget`,
  `snapshot`, `diff`, and `rollback` join `commit_mem`, `recall`, and `status`. One API key, no local
  database configuration.
- `CloudClient.health()` for public service health, plus `revise()`, `forget()`, `create_snapshot()`,
  `list_snapshots()`, `snapshot()`, `diff()`, `rollback_preview()`, and `rollback()`.
- CLI gains `health`, `revise`, `forget`, `snapshot create|list`, `diff`, and
  `rollback preview|execute`.
- Typed SDK errors behind a canonical public error-code table, so a caller can branch on
  authenticate / upgrade / retry / resolve a conflict / fix input. All of them still subclass
  `BilincCloudError`.
- `commit` accepts the full provenance contract (`source`, `session_id`, `canonical`, `priority`,
  `ttl`) and returns an opaque entry version for optimistic concurrency.
- Writes accept an `idempotency_key`, so a retry replays the original result instead of applying
  twice.

### Changed
- **Breaking:** `CloudClient.status()` now returns authenticated workspace, plan, capability, limit,
  and usage information from `GET /api/cloud/status`. Service health moved to `CloudClient.health()`
  and the unchanged `GET /api/cloud/health`. Repoint uptime monitors at `health()`, or an expired
  entitlement will read as an outage.
- `forget` requires a reason on Cloud. It is written to the audit trail, and the deleted value is
  never returned.
- Rollback is two-stage: a free preview mints a short-lived confirmation token, and execute requires
  it plus an unchanged project state root.
- Read-only calls retry a bounded number of times on transport and 5xx failures. Writes stay
  single-shot and rely on server-side idempotency instead.

### Fixed
- Recall now accepts the documented limit of 100 end to end. The runtime capped at 50, so limits
  between 51 and 100 became opaque `503`s.
- Snapshot identifiers are collision resistant. They were derived from a float timestamp, so two
  snapshots taken in the same microsecond overwrote each other. Existing timestamp-named snapshots
  stay readable and correctly ordered.

## [2.1.5] — 2026-07-25

### Added
- Published package metadata now carries project URLs (homepage, documentation, repository, changelog, issues), so the PyPI page links back to the docs and source instead of standing alone.
- `server.json` describing the Cloud MCP adapter for the official MCP Registry, plus the `mcp-name` ownership marker in the package description.

### Changed
- No functional change to the SDK, CLI, or MCP adapter. This release exists to make the published package discoverable from the MCP Registry and from PyPI search.

## [2.1.4] — 2026-07-10

### Fixed
- Use a certifi-backed TLS context for Bilinc Cloud SDK/CLI requests so macOS Python installs with an empty OpenSSL CA path do not fail with `CERTIFICATE_VERIFY_FAILED`.

## [2.1.3] — 2026-06-01

### Changed
- Tightened the first-run activation path so `bilinc start` points users to the 7-day trial, hosted API key creation, `bilinc login`, and `bilinc quicktest`.
- Added tracked CLI signup/install URLs for measuring PyPI-to-Cloud activation without changing the Cloud entitlement gate.
- Updated README first-run copy to make a passing `bilinc quicktest` the first success milestone.

## [2.1.2] — 2026-05-29

### Added
- Added the CLI-led activation path: `bilinc start`, `bilinc login`, `bilinc quicktest`, `bilinc doctor`, and `bilinc mcp install`.
- Added local CLI config support so `bilinc login --api-key <key>` can store a hosted Cloud key without requiring repeated shell exports.
- Added `BILINC_BASE_URL` override support for mock, staging, and docs smoke verification.

### Changed
- Updated the public README to the cloud-only PyPI package surface and removed legacy local `StatePlane` quickstart framing.
- Kept the public package boundary cloud-only: CloudClient, CLI, and Cloud MCP adapter only.

## [2.1.1] — 2026-05-26

### Fixed
- Restored the public PyPI package to the intended cloud-only SDK, CLI, and MCP adapter surface after the accidental `2.1.0` packaging regression.
- Reconfirmed that public artifacts do not ship local `StatePlane`, storage, eval, observability, integration, local MCP server, adaptive, retrieval, security, or jobs internals.

### Notes
- `2.1.0` should be considered a bad public artifact for the cloud-only packaging model. Use `2.1.1` or newer.

## [2.1.0] — 2026-05-26

### Added
- Cognitive runtime primitives for agent turn lifecycle, workspace framing, and runtime handoff.
- Context assembler for prompt-safe memory packets with evidence references.
- Deterministic salience/writeback policy for deciding what should become durable memory.
- Framework-agnostic agent runtime adapter and LangGraph workspace adapter.
- MCP admin/debug workspace preview tools for inspecting assembled runtime state.
- Event ledger for memory operations with append-order hash chaining.
- Eval receipts anchored to event IDs and checkpoint roots.
- Project-isolated Cloud runtime sidecar foundation with service-token auth and snapshot endpoints.
- Repository `AGENTS.md` operating contract for future agent maintainers.

### Changed
- README and package metadata now frame Bilinc as a verifiable agent brain/runtime, not only a memory database.
- Server optional dependency now covers the internal Cloud sidecar path via FastAPI/Uvicorn.

### Security / Safety
- Recursive redaction coverage for secret-like payloads in event/eval surfaces.
- Cloud sidecar requires service-token auth and validates project UUID path segments.

### Caveats
- Hosted Cloud self-serve runtime and billing flow remain separate live-product surfaces; this package release provides the SDK/runtime foundation.

## [Unreleased] — 2026-05-17

### Added
- Evidence-aware recall package on `main`: opt-in retrieval capture/replay, structured attributed claims, read-only contradiction probes, named recall profiles, and conservative entity/backlink projection.
- Public-safe evidence documentation and refreshed LongMemEval competitive benchmark artifacts.

### Changed
- README architecture asset and benchmark framing refreshed to reflect the current `main` capability set.

## [1.2.5] — 2026-05-09

### Changed
- Switched the downloads badge from a pinned daily count to the Pepy all-time downloads badge (`downloads: 3k`) for both GitHub and PyPI rendering.

## [1.2.4] — 2026-05-09

### Changed
- Pinned the README downloads badge to the last observed PyPI downloads/day value because the dynamic Shields/PyPI downloads endpoint is intermittently upstream rate-limited.

## [1.2.3] — 2026-05-09

### Changed
- Refreshed PyPI long description from the current GitHub README.
- Updated README badges to use the refreshed GitHub/PyPI badge set and a non-rate-limited PyPI downloads/day badge.

## [1.2.2] — 2026-05-06

### Fixed
- Hardened audit trail appends against stale multi-process roots by reading the latest persisted root inside a SQLite `BEGIN IMMEDIATE` transaction.
- Added regression coverage for stale multi-instance audit writers sharing one SQLite database.
- MCP `diff` dispatcher now routes through structured argument validation instead of raising `KeyError` when optional timestamps are omitted on audit-backed planes.
- MCP status version now reads installed package metadata instead of returning a stale hardcoded version.

### Changed
- Version bumped to `1.2.2` for the Bilinc audit/MCP hardening release.

## [1.2.1] — 2026-04-17

### Changed
- PyPI package metadata license switched to `BUSL-1.1` (Business Source License 1.1) for distribution clarity.
- Package version bumped to `1.2.1` for the metadata-only release.

## [1.2.0] — 2026-04-17

### Added
- Phase 7 scheduler runtime completed with background jobs and start/stop integration for stdio and HTTP transports.
- New `src/bilinc/jobs/` layer for explicit background job definitions.
- Phase 8 MCP tool expansion:
  - `bilinc_recall_smart`
  - `bilinc_query_analysis`
  - `bilinc_event_segment`
  - `bilinc_summarize`
  - `bilinc_health`
  - `bilinc_benchmark`
  - `bilinc_export`
  - `bilinc_import`
- Full-phase snapshot regression test (`tests/test_phase_full_snapshot.py`) to validate Phase 1-8 behavior on a snapshot copy.

### Changed
- README badges and feature matrix updated for current CI/stars links and 20-tool MCP surface.
- Snapshot-based tests now support CI fallback seeding when local fixture DB is unavailable.

### Fixed
- CI failures caused by missing local snapshot fixture (`tests/fixtures/*.db`) on GitHub runners.

## [1.0.4] — 2026-04-10

### Fixed
- Hermes `commit_mem -> recall` contract now preserves metadata deterministically, including `canonical` and related metadata fields.
- `recall` response contract hardened: `entries[*].metadata` is always an object (falls back to `{}` when empty).
- `snapshot/diff/rollback` chain stabilized by fixing rollback restore path and legacy string-vs-dict audit payload mismatch.
- Rollback restore now validates audit payload schema before reconstructing state to prevent silent corruption.
- Invalid/legacy rollback payloads now return structured failures (`success=false`, stable `error` field) instead of runtime crashes.
- `bilinc hermes bootstrap` smoke flow fixed for async execution and aligned with Hermes integration contract checks.
- Hermes stdio launcher wiring corrected to use the supported MCP server v2 factory signature.
- PostgreSQL DSN exposure closed across health/status payloads via credential redaction.
- HTTP/observability contract hardened so secret-bearing configuration is never emitted in plain text.
- Persistence truthfulness fixed: backend write failures now surface deterministic `persistence_write_failed` errors instead of reporting success.
- `commit_mem` and `revise` now fail fast when durable backend save fails, preventing false-positive success + audit divergence.
- Init failure path hardened: secondary health/audit exceptions no longer mask the original root-cause error.
- SQLite lock handling improved with clearer structured CLI errors (`database_locked`, retryable) and retry-friendly messaging.
- SQLite backend now configures connection timeout + `PRAGMA busy_timeout` to reduce transient lock flakiness.
- CI workflow supply-chain hardening applied: GitHub Actions migrated from floating tags to pinned commit SHAs.
- `commit_sync` async-loop behavior corrected to avoid un-awaited coroutine warnings; full test suite now runs warning-free for this path.

### Added
- CLI failure envelope helper for deterministic JSON errors across `commit`/`recall`/`forget`/`status`/init paths.
- Regression tests for DSN redaction in health/status outputs.
- Regression tests for persistence write-failure contracts (`commit_mem` and `revise`).
- Regression tests for SQLite lock/error envelope behavior in CLI paths.

## [1.0.2] — 2026-04-10

### Added
- Hermes one-command bootstrap flow: `bilinc hermes bootstrap` and `bilinc hermes smoke`
- Standard Hermes stdio launcher (`bilinc.mcp_server.hermes_stdio`)
- Public Hermes documentation and integration contract
- Hermes-focused CI lane and end-to-end integration tests

### Changed
- MCP `commit_mem` now supports Hermes metadata contract: `source`, `session_id`, `canonical`, `priority`, `ttl`
- Recall ordering now prioritizes canonical and high-priority entries when canonical flag is set

## [1.0.1] — 2026-04-08

### Fixed
- `commit_mem` via MCP now persists AGM-backed writes to SQLite/PostgreSQL instead of only mutating in-process belief state
- `recall` now falls back to the persistent backend, so fresh server processes can still see previously committed memories
- `revise` and `forget` now keep backend state synchronized with AGM changes
- `verify` now checks persistent entries even when AGM state has not yet been hydrated

### Added
- Regression coverage for persistent MCP commit/recall/forget flows

### Added
- **Phase 4: MCP Server v2** — 12 tools (commit_mem, recall, forget, revise, status, verify, consolidate, snapshot, diff, rollback, query_graph, contradictions)
- **Phase 4: Rate Limiter** — Token bucket rate limiter with per-client tracking
- **Phase 5: Security Layer** — Input validation (key pattern, value size, path traversal protection, XSS sanitization, resource limits, MCP auth via hmac.compare_digest)
- **Phase 5: Observability** — Prometheus-compatible metrics, HealthCheck, latency tracing, uptime monitoring
- **Phase 5: Benchmark Suite** — Retrieval latency, verification accuracy, consolidation efficiency, AGM stress tests (1000 operations/sec)
- Documentation: Architecture, MCP Server Reference, Security Guide
- `commit_sync()` with automatic in-memory fallback for backend=None
- `recall_all_sync()` for synchronous working memory recall

### Changed
- `StatePlane` now includes `metrics` and `health` components by default
- `commit_sync()` enforces resource limits (max 16 working memory entries)
- AGM engine updated to use `key in beliefs` (BeliefState compatibility fix)
- Knowledge Graph uses `MemoryType.SEMANTIC` (removed deprecated `SYMBOLIC`)
- All core tests migrated from async to sync for reliability

### Fixed
- Async/sync mismatch in StatePlane tests
- Cross-tool path traversal false positives
- MemoryType.SYMBOLIC deprecation → SEMANTIC migration
- BeliefState.has_belief() compatibility fix
- Knowledge Graph node export in MCP responses

---

## [0.4.0a1] — 2026-04-07

### Added
- AGM Belief Revision Engine with Darwiche & Pearl postulates (DP1-DP4)
- Knowledge Graph (NetworkX-backed, entity/relation extraction)
- Multi-Agent Belief Sync (push/pull/merge, consensus, vector clocks)
- MCP Server v1 (5 tools: commit, recall, forget, explain, status)

### Changed
- `core/stateplane.py`: Phase 3 integrations (init_agm, init_knowledge_graph, commit_with_agm)

---

## [0.2.0a1] — 2026-04-05

### Added
- Phase 1: 5 brain-mimetic memory types (episodic, procedural, semantic, working, spatial)
- Phase 2: Z3 SMT Verification Gate
- Phase 2: Merkle Audit Trail
- Phase 2: State Diff / Rollback API
- ContextBudget RL
- Learnable Forgetting (Ebbinghaus decay curves)
- LangGraph Integration
- MCP Server v1 (5 tools)

---

## [0.1.1] — Initial PyPI Release

- Core StatePlane
- Basic commit/recall
- Simple working memory
- Cross-tool translation
