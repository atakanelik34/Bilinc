# BILINC — Final Acceptance Gate

Use this only at the very end. If any item below is not true, do not declare Bilinc production-ready.

## Fresh Clone Validation

- [ ] Fresh clone from GitHub succeeds
- [ ] Clean virtual environment created
- [ ] `pip install -e '.[dev]'` succeeds
- [ ] `import bilinc` succeeds
- [ ] `from bilinc import StatePlane` succeeds
- [ ] `PYTHONPATH=src pytest -q tests/` succeeds
- [ ] No critical warnings appear in clean environment

## Package Validation

- [ ] `python -m build` succeeds
- [ ] wheel install succeeds
- [ ] sdist install succeeds if generated
- [ ] post-install import smoke succeeds

## Persistence Validation

- [ ] in-memory mode behavior is documented
- [ ] SQLite persistent mode works across separate processes
- [ ] PostgreSQL backend passes integration tests
- [ ] schema versioning works
- [ ] backend initialization is deterministic

## State Semantics Validation

- [ ] snapshot behavior is documented
- [ ] diff behavior is documented
- [ ] rollback behavior is documented
- [ ] rollback restores exact target state
- [ ] destructive behavior is documented

## Security Validation

- [ ] stdio trust model is explicit
- [ ] HTTP auth is enforced where claimed
- [ ] invalid token path tested
- [ ] missing token path tested
- [ ] rate limit enforcement tested
- [ ] input validation abuse cases tested

## Observability Validation

- [ ] logs exist for critical operations
- [ ] logs exist for critical failures
- [ ] metrics exist for operation and error tracking
- [ ] health/readiness output exists
- [ ] degraded state is distinguishable

## CI / Delivery Validation

- [ ] CI validates all critical paths
- [ ] package artifact build/install is covered
- [ ] integration tests run where appropriate
- [ ] release checklist exists
- [ ] versioning strategy is documented

## Documentation Validation

- [ ] README matches runtime truth
- [ ] docs/security.md matches runtime truth
- [ ] docs do not overclaim production/security guarantees
- [ ] deprecated surfaces are labeled clearly
- [ ] unsupported integrations are not presented as active

## Hygiene Validation

- [ ] `git ls-files | rg '__pycache__|\\.pyc$|\\.egg-info'` returns empty
- [ ] `.gitignore` covers common Python/cache artifacts
- [ ] no stale test-count claims remain
- [ ] no stale Python-version claims remain
- [ ] no stale security claims remain

## Final Commands

Run at the end:

```bash
python -m pip install -e '.[dev]'
python -c "import bilinc; print(bilinc.__version__)"
python -c "from bilinc import StatePlane; print(type(StatePlane()).__name__)"
PYTHONPATH=src pytest -q tests/
git ls-files | rg '__pycache__|\\.pyc$|\\.egg-info'
python -m build
pip install dist/*.whl
python -c "import bilinc; print(bilinc.__version__)"
```

Persistent CLI final smoke:

```bash
bilinc --db ./tmp.db commit --key smoke_key --value hello
bilinc --db ./tmp.db recall --key smoke_key
```

## Final Declaration Template

Use only if every gate passes:

```text
Bilinc is now production-ready under the currently documented feature surface.

Verified:
- fresh clone
- clean install
- full test suite
- artifact install
- persistence path
- backend parity
- rollback correctness
- auth/rate-limit enforcement where claimed
- observability minimum viable surface
- CI and release validation
- documentation truthfulness

If any of the above is not true, do not use this declaration.
```
