# Bilinc Public StatePlane Compatibility Sprint 3

## Goal

Close the known legacy test/package boundary blocker around `from bilinc import StatePlane` while preserving Bilinc's cloud-only public package posture.

## Concern classification

- `agent-memory`
- `security-critical`

## Constraints

- No memory backend/provider migration.
- No live `/Users/busecimen/bilinc.db` mutation beyond explicit Bilinc receipt keys.
- No PyPI publish, deploy, package release, or public claim.
- Do not broaden public SDK accidentally beyond the intended compatibility surface.
- Use TDD: reproduce the import/collection failure first, then patch minimally.
- End sprint with both GitHub repos PR/CI/main merge using owner-token rotation.

## Acceptance criteria

1. `tests/test_claims.py` and `tests/test_recall_profiles.py` no longer fail at collection due to `from bilinc import StatePlane`.
2. Top-level `bilinc` public package exposes only the intended compatibility symbols and cloud client symbols.
3. Cloud-only package behavior remains intact for normal imports.
4. Focused tests pass:
   - public export/compat tests
   - claims tests
   - recall profile tests
   - recall explain tests
   - knowledge graph tests
5. `py_compile` and `ruff` pass for changed files.
6. Independent review approves before commit/merge.

## Expected implementation direction

Keep `src/bilinc/__init__.py` cloud-only. Move legacy/internal tests and local-only examples/benchmarks that exercise local StatePlane internals to `from bilinc.core.stateplane import StatePlane` so package-level import remains cloud-only while internal collection stops failing. Any stdio/server launcher that needs local StatePlane should use the same core import and treat missing optional scheduler modules as non-fatal when scheduler startup is enabled but the scheduler module is not shipped.
