# BILINC — Production Milestones

This file breaks production readiness into practical milestones. Use this to sequence work without losing the critical path.

## Milestone 1 — Persistent Runtime Foundation

### Objective
Move Bilinc from process-bound memory to durable memory.

### Scope
- persistent CLI mode
- SQLite persistence path
- backend contract alignment
- schema versioning

### Key Files
- `src/bilinc/cli/main.py`
- `src/bilinc/core/stateplane.py`
- `src/bilinc/storage/backend.py`
- `src/bilinc/storage/sqlite.py`
- `src/bilinc/storage/postgres.py`

### Exit Criteria
- SQLite persistence works across separate CLI invocations
- backend contracts are aligned
- schema versioning exists
- integration tests cover basic persistence lifecycle

### Risk
- If contract drift remains, SQLite and PostgreSQL will diverge again later

## Milestone 2 — State Semantics Correctness

### Objective
Make state restoration trustworthy.

### Scope
- snapshot semantics
- diff semantics
- rollback implementation
- destructive-operation documentation

### Key Files
- `src/bilinc/core/stateplane.py`
- rollback/snapshot-related tests
- docs for state semantics

### Exit Criteria
- rollback accurately reconstructs target state
- mixed-operation rollback tests pass
- docs explain exact behavior

### Risk
- Incorrect rollback destroys trust in the system faster than any missing feature

## Milestone 3 — Security Enforcement

### Objective
Make auth and rate limiting real where claimed.

### Scope
- HTTP auth if HTTP transport exists
- explicit stdio trust boundary
- real token validation
- client-aware rate limiting
- security test expansion

### Key Files
- `src/bilinc/mcp_server/server_v2.py`
- security modules
- docs/security.md

### Exit Criteria
- negative auth tests pass
- rate limit tests pass
- docs match runtime exactly

### Risk
- Placeholder security behavior creates false confidence

## Milestone 4 — Observability

### Objective
Make the system operable under real load and failure.

### Scope
- structured logs
- metrics
- readiness/liveness
- degraded-state reporting

### Key Files
- observability modules
- core runtime paths
- docs/runbooks

### Exit Criteria
- critical failures are visible
- health distinguishes healthy/degraded/failed
- operators can diagnose common failures

### Risk
- Without observability, production incidents become guesswork

## Milestone 5 — CI/CD and Release Discipline

### Objective
Make quality and shipping repeatable.

### Scope
- expanded GitHub Actions
- artifact build/install checks
- release checklist
- Postgres integration in CI if supported

### Key Files
- `.github/workflows/*`
- release documentation
- packaging config

### Exit Criteria
- CI covers critical paths
- package build works
- package install smoke works
- release process is documented

### Risk
- Manual-only release quality is not production quality

## Milestone 6 — Public Surface Finalization

### Objective
Ensure every visible feature is either supported or explicitly not supported.

### Scope
- export audit
- docs audit
- integration support decisions
- LangGraph decision

### Key Files
- package exports
- integration exports
- README
- docs/*

### Exit Criteria
- no ghost integrations
- no stale claims
- no unsupported exports pretending to be maintained

### Risk
- Public surface drift is a trust problem, not just a cleanup problem

## Suggested Sequence

1. Milestone 1
2. Milestone 2
3. Milestone 3
4. Milestone 4
5. Milestone 5
6. Milestone 6

This order protects the critical path:
- first make data real
- then make data correct
- then make access safe
- then make runtime observable
- then make shipping reliable
- then clean the public surface

## 90-Day Cadence

### Weeks 1-2
- persistent CLI design and implementation
- backend contract cleanup
- SQLite integration tests

### Weeks 3-4
- schema versioning
- migration framework
- persistent CLI verification

### Weeks 5-6
- rollback semantics spec
- rollback implementation
- rollback correctness tests

### Weeks 7-8
- HTTP auth
- client-aware rate limiting
- security negative tests

### Weeks 9-10
- logging
- metrics
- health/readiness
- degraded-state handling

### Weeks 11-12
- CI expansion
- artifact verification
- release checklist
- docs/public surface audit

## Milestone Completion Rule

A milestone is complete only if:
- implementation is merged
- relevant tests exist
- targeted verification commands were run
- docs were updated if behavior changed
- remaining risks were explicitly written down
