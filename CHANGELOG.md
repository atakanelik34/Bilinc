# Changelog

All notable changes to Bilinc.

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
