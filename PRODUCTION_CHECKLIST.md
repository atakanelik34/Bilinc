# BILINC — Production Checklist

Use this as the execution checklist while working. Do not mark a box complete unless code, tests, and local verification all agree.

## 1. Persistence

- [ ] CLI supports persistent mode via `--db`
- [ ] Optional env-based DB configuration exists if appropriate
- [ ] In-memory mode remains available and clearly labeled ephemeral
- [ ] `commit`, `recall`, `forget`, `status` work against the same persistent backend
- [ ] SQLite initializes automatically on first use
- [ ] SQLite init is idempotent
- [ ] PostgreSQL init is deterministic
- [ ] Schema version tracking exists
- [ ] Migration strategy is documented
- [ ] Persistent CLI works across separate processes

Verification:

```bash
bilinc --db ./tmp.db commit --key k --value hello
bilinc --db ./tmp.db recall --key k
```

## 2. Backend Contract

- [ ] `StorageBackend` declares the full required surface
- [ ] SQLite implements the full surface
- [ ] PostgreSQL implements the full surface
- [ ] No backend-only drifted method names remain
- [ ] Tests cover backend parity expectations

Verification:

```bash
rg -n "class .*Backend|def stats|def load_by_type|def get_stats" src/bilinc/storage
PYTHONPATH=src pytest -q tests/
```

## 3. Snapshot / Diff / Rollback

- [ ] Snapshot semantics documented
- [ ] Diff semantics documented
- [ ] Rollback semantics documented
- [ ] Rollback implemented for persistent backends
- [ ] Rollback correctly handles create/update/delete scenarios
- [ ] Unsupported rollback context fails clearly
- [ ] Rollback is audited or explicitly documented as not audited

Verification:

```bash
PYTHONPATH=src pytest -q tests/ -k "rollback or snapshot or diff"
```

## 4. Security

- [ ] stdio trust model documented explicitly
- [ ] HTTP auth model documented explicitly
- [ ] Auth is enforced where claimed
- [ ] Token comparison uses constant-time comparison where relevant
- [ ] Rate limiting is bound to a real client identity
- [ ] Invalid/missing auth requests fail correctly
- [ ] Input validation covers malicious boundary cases

Verification:

```bash
PYTHONPATH=src pytest -q tests/ -k "auth or rate or validator or security"
rg -n "compare_digest|rate_limiter|auth_token" src docs
```

## 5. Observability

- [ ] Structured logs exist for commit
- [ ] Structured logs exist for recall
- [ ] Structured logs exist for revise
- [ ] Structured logs exist for rollback
- [ ] Structured logs exist for backend failures
- [ ] Metrics exist for operation counts and failures
- [ ] Health/readiness reporting exists
- [ ] Degraded mode is distinguishable from healthy mode

Verification:

```bash
PYTHONPATH=src pytest -q tests/ -k "health or metrics or observability"
```

## 6. CI / Release

- [ ] CI runs tests
- [ ] CI runs smoke checks
- [ ] CI builds package artifacts
- [ ] CI validates install from artifact or editable install
- [ ] Postgres integration is in CI if supported
- [ ] Release checklist exists
- [ ] Package build succeeds locally
- [ ] Wheel install succeeds locally

Verification:

```bash
python -m build
pip install dist/*.whl
python -c "import bilinc; print(bilinc.__version__)"
```

## 7. Public Surface Truthfulness

- [ ] All exported integrations are supported or deprecated explicitly
- [ ] No stale feature claims remain
- [ ] No stale test-count claims remain
- [ ] No stale security claims remain
- [ ] README matches runtime truth
- [ ] Docs match runtime truth

Verification:

```bash
rg -n "auth enforced|production-ready|108 passed|109 passing|3\\.9\\+|deprecated and broken" README.md docs src tests .github
```

## 8. Fresh-Clone Gate

- [ ] Fresh clone works
- [ ] Editable install works from fresh clone
- [ ] Full tests pass from fresh clone
- [ ] No critical warnings in clean environment
- [ ] Basic CLI smoke passes from fresh clone

Verification:

```bash
git clone <repo-url> bilinc-fresh
cd bilinc-fresh
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e '.[dev]'
PYTHONPATH=src pytest -q tests/
bilinc status
```

## Final Declaration Rule

Do not call Bilinc production-ready until every section above is complete.
