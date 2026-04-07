# Changelog

All notable changes to Bilinc.

## [Unreleased] — v1.0.0 (In Development)

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
