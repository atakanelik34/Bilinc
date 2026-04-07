# BILINC — Production Readiness Master Prompt for Neo

## Mission

You are working on the **Bilinc** repository.

Bilinc is already:
- installable
- importable
- testable
- alpha-ready

It is **not yet production-ready**.

Your job is to take Bilinc from:
- `installable alpha`

to:
- `production-ready beta / release-candidate quality`

This is an execution task, not a review-only task.

You must:
- inspect
- design
- implement
- test
- verify
- document
- leave the repository in a materially stronger state

Do not optimize for feature count.
Optimize for:
- correctness
- operational safety
- repeatability
- contract clarity
- reliability under failure
- documentation honesty

Ignore unrelated memory/fabric recall noise from other projects.

## Current Known Baseline

As of the latest validated state, the repository already has:
- working package install
- working import path
- green test suite
- lazy imports
- basic CLI
- MCP v2 surface
- CI present
- alpha-level cleanup complete

This means you are not fixing a broken prototype.
You are hardening a working alpha into a production-capable system.

## Primary Objective

Make Bilinc credible for real production use.

That means all of the following must become true:
- persistence is real
- schema behavior is deterministic
- rollback semantics are correct
- auth and rate limiting are real where claimed
- operational telemetry exists
- CI/CD validates critical surfaces
- public documentation matches actual runtime behavior

## Hard Requirements

You are done only when:

### Persistence
- CLI supports persistent mode
- SQLite is usable for real small deployments
- PostgreSQL is contract-aligned and tested
- schema versioning exists
- backend initialization is deterministic

### Data Correctness
- snapshot / diff / rollback have defined semantics
- rollback actually restores target state correctly
- destructive behavior is documented and test-covered

### Security
- stdio vs HTTP trust model is explicit
- HTTP auth is enforced if HTTP transport exists
- rate limiting is real, not placeholder
- input validation is tested against abuse cases

### Reliability
- structured logging exists on critical paths
- metrics exist for key operations and failures
- health/readiness surface exists and distinguishes degraded states

### Delivery
- CI validates critical surfaces
- package artifact build/install is tested
- release process is documented

### Truthfulness
- no stale claims
- no ghost integrations
- no security claims without enforcement

## Non-Goals

Do not spend time on these unless they directly block production readiness:
- marketing copy polish
- speculative new memory features
- UI/branding work
- large integration expansion without support guarantees
- restoring unsupported surfaces just for completeness

If a surface is stale and expensive to repair, prefer:
- deprecate
- remove from exports
- document honestly

## Mandatory Working Style

Work in this order:
1. inspect current repo state
2. summarize exact production gaps
3. group work into phases
4. implement one phase at a time
5. verify after each phase
6. update docs only after code truth exists
7. finish with full fresh-clone verification

Do not claim a fix unless:
- code changed
- tests cover it
- behavior was verified locally

If you make a tradeoff, document it explicitly.

## Phase Plan

### Phase 1 — Persistence and Runtime Contract Hardening

Objective:
- make persistence real and deterministic

Tasks:
- add persistent CLI mode:
  - `--db path/to/file.db`
  - optional `BILINC_DB_URL`
- preserve explicit in-memory default mode
- ensure `commit`, `recall`, `forget`, `status` work against a persistent backend
- audit `StorageBackend`, SQLite, PostgreSQL contracts
- align backend method surfaces exactly
- add schema versioning
- make backend initialization idempotent
- define migration strategy

Acceptance criteria:
- `bilinc --db ./tmp.db commit --key x --value hello`
- `bilinc --db ./tmp.db recall --key x`
- works across separate processes
- SQLite integration tests exist
- PostgreSQL backend matches the abstract backend exactly

### Phase 2 — Snapshot / Diff / Rollback Correctness

Objective:
- make rollback a real, correct state restoration mechanism

Tasks:
- define exact semantics for snapshot, diff, rollback
- implement rollback for persistent storage
- handle create/update/delete/recreate semantics correctly
- document whether rollback emits audit events

Acceptance criteria:
- rollback restores exact target state
- mixed-operation rollback tests pass
- unsupported contexts fail clearly

### Phase 3 — Security Enforcement

Objective:
- move security from docs into runtime behavior

Tasks:
- define stdio trust boundary
- implement HTTP auth if HTTP transport exists
- use constant-time token comparison
- bind rate limiting to real client identity
- expand abuse/input validation tests

Acceptance criteria:
- valid token accepted
- invalid token rejected
- missing token rejected
- rate limit exceeded returns explicit failure
- docs exactly match behavior

### Phase 4 — Observability and Operational Readiness

Objective:
- make Bilinc inspectable in production

Tasks:
- structured logs for critical paths
- metrics for operations, latency, failures
- health/readiness reporting
- degraded-state reporting

Acceptance criteria:
- actionable logs exist on failure paths
- health distinguishes healthy/degraded/failed
- core metrics are exposed or retrievable

### Phase 5 — CI/CD and Release Discipline

Objective:
- make quality and release repeatable

Tasks:
- expand CI:
  - lint
  - tests
  - integration tests
  - package build
  - install smoke
- add PostgreSQL integration in CI if feasible
- add release checklist
- verify wheel/sdist install

Acceptance criteria:
- all critical paths are validated in CI
- artifacts build and install cleanly
- release process is documented enough for another maintainer

### Phase 6 — Public Surface Finalization

Objective:
- ensure every visible surface is trustworthy

Tasks:
- audit exports
- fix / deprecate / remove stale integrations
- make explicit decision on LangGraph:
  - productionize
  - or keep unsupported

Acceptance criteria:
- every documented feature works
- every exported integration is supported or deprecated explicitly

## Required Verification Commands

Run these repeatedly during the work:

```bash
python -m pip install -e '.[dev]'
python -c "import bilinc; print(bilinc.__version__)"
python -c "from bilinc import StatePlane; print(type(StatePlane()).__name__)"
PYTHONPATH=src pytest -q tests/
git ls-files | rg '__pycache__|\\.pyc$|\\.egg-info'
bilinc status
bilinc commit --key smoke_key --value hello
bilinc recall --key smoke_key
python -m build
pip install dist/*.whl
python -c "import bilinc; print(bilinc.__version__)"
```

Future persistent CLI verification:

```bash
bilinc --db ./tmp.db commit --key smoke_key --value hello
bilinc --db ./tmp.db recall --key smoke_key
```

Stale-claim search:

```bash
rg -n "auth enforced|production-ready|108 passed|109 passing|deprecated and broken|3\\.9\\+" README.md docs src tests .github
```

## Implementation Constraints

- Do not break working alpha functionality while hardening
- Do not remove a working surface unless replacing or deprecating clearly
- Do not let docs get ahead of code
- Do not widen claims without verification
- If a surface cannot be made production-worthy, reduce the claim instead of faking completion

## Reporting Format After Each Phase

Return this structure after each phase:

### Phase Name
- objective
- files changed
- what was implemented
- what was intentionally not implemented
- commands run
- exact results
- remaining risks
- next phase recommendation

At the very end, return:

### Final Summary
- current repo state
- what is production-ready now
- what is still beta/alpha only
- exact commands used
- whether the repo is:
  - alpha-ready
  - beta-ready
  - production-ready
- remaining blockers, if any

## Final Gate

Do not declare production-ready until all are true:
- fresh clone works
- editable install works
- artifact install works
- SQLite integration suite passes
- PostgreSQL integration suite passes
- rollback semantics are correct and tested
- auth enforcement is real where claimed
- rate limiting is real where claimed
- logs and metrics exist for critical failures
- release process is documented
- docs match runtime truth exactly
- no critical warnings
- CI validates critical surfaces

## First Move

Start here:
1. inspect current repo and summarize production gaps
2. implement persistent CLI + SQLite persistence
3. harden backend contract + schema/versioning
4. implement true rollback semantics
5. add security enforcement
6. add observability
7. expand CI/release validation
8. finalize docs/public surface
9. run fresh-clone verification before claiming completion

## Final Instruction

Do not stop at planning.
Do not stop at analysis.
Carry the work end-to-end:
- inspect
- implement
- test
- verify
- document
- summarize

If you must choose between "more feature" and "more trust", choose trust.
