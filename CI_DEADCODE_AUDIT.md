# Bilinc Project: CI/CD, Dead Code & Cross-Module Audit
## Audits 7-10 | 2026-04-13

---

## AUDIT 7: CI/CD Pipeline

### 7.1 CI Workflow Structure (.github/workflows/ci.yml)
Status: GOOD - Well-structured with 5 jobs (test, package, artifact-validation, postgres-integration, hermes-integration).

### 7.2 CI Issues Found

**[CRITICAL] Line 121: PostgreSQL password mismatch**
```
BILINC_DB_URL: postgresql://bilinc:***@localhost:5432/bilinc_test
```
The service defines `POSTGRES_PASSWORD: bilinc_test` (line 97) but the env var uses literal `***` as the password. This will cause CI authentication failures.

**[LOW] No pip caching** - could speed up CI by ~30s per job.

**[OK] Pinned action SHAs** - Good security practice.

### 7.3 Test Path Verification
All test paths verified. 17 test files + smoke tests exist.

### 7.4 Security in CI
OK - No real secrets in plaintext. OK - Action SHAs pinned.

---

## AUDIT 8: Dead Code & Unused

### 8.1 Unused Functions (0 callers in src/)

**[HIGH] ConsolidationEngine** (adaptive/consolidation.py:35) - entire 201-line module unused, never imported anywhere

**[MEDIUM]:**
- temporal.py: `format_duration()`, `temporal_boost()`, `sort_by_temporal()`, `find_temporal_context()` - all 0 callers
- kg_retrieval.py:143 `kg_enhanced_recall()` - 0 callers
- belief_sync.py: `init_sync()`, `push_beliefs()`, `pull_updates()`, `merge_sync()`, `consensus_sync()`, `get_divergence()` - entire class unused

**[LOW]:**
- decay.py: `decay_for_entry()`, `decay_preview()`
- verification.py: `verify_recall()`
- knowledge_graph.py: `query_entity()`, `remove_entity()`, `remove_relation()`, `get_relations()`, `export_to_json()`, `import_from_json()`
- working_memory.py: `on_consolidation()`, `to_entries()`

### 8.2 Unused Imports
- kg_retrieval.py:11 - `Set` imported but never used
- adaptive/consolidation.py:8 - `Callable` imported but never used

### 8.3 Commented-Out Code Blocks
OK - None found. Codebase is clean.

### 8.4 TODO/FIXME/HACK Comments
OK - None found.

### 8.5 Duplicate Code Patterns
**[MEDIUM]** Two consolidation modules: `core/consolidation.py` (3-stage pipeline) and `adaptive/consolidation.py` (NREM/REM). Both have `ConsolidationResult` dataclasses. adaptive version is entirely unused.

---

## AUDIT 9: Cross-Module Integration

### 9.1 decay.py <-> models.py
**CORRECT** - models.py:102 imports `compute_new_strength` via lazy import. No circular deps.

### 9.2 consolidation.py -> decay + blind_spots
**CORRECT** - Lazy imports in method bodies. Error handling present for blind_spots.

### 9.3 vector_search.py <-> sqlite.py FTS5
**MINOR ISSUES** - FTS5 queries use correct syntax but:
- **[MEDIUM]** Missing UPDATE/DELETE triggers. Only INSERT trigger exists (sqlite.py:108-111). FTS5 index goes stale on updates/deletes.
- **[MEDIUM]** `HybridSearch` and `VectorStore` classes defined but never instantiated in src/.

### 9.4 kg_retrieval.py <-> temporal.py
**NOT INTEGRATED** - kg_retrieval.py does NOT import or use temporal.py. The temporal module is written but never wired into the retrieval pipeline.

### 9.5 Module __init__.py Exports
All `__init__.py` files verified correct.

---

## AUDIT 10: Overall Health Score

| Category | Score | Weight |
|----------|-------|--------|
| CI/CD Pipeline | 7/10 | 20% |
| Code Cleanliness | 6/10 | 25% |
| Cross-Module Integration | 7/10 | 25% |
| Test Coverage | 8/10 | 15% |
| Security | 8/10 | 15% |

**Overall Health Score: 7.1/10 (GOOD)**

---

## PRIORITIZED FIX LIST

**P0 - CRITICAL (Fix Immediately):**
1. CI postgres password bug - ci.yml:121 - Change `***` to `bilinc_test`
2. CLI env file placeholder - cli/main.py:449 - `BILINC_RATE_LIMIT_MAX_TOKENS=***` writes literal `***`

**P1 - HIGH (Fix This Sprint):**
3. FTS5 missing UPDATE/DELETE triggers - sqlite.py:101-114
4. Remove unused ConsolidationEngine - adaptive/consolidation.py (201 lines dead code)
5. Wire temporal.py into retrieval or remove unused functions

**P2 - MEDIUM (Next Sprint):**
6. Clean up belief_sync.py - 6 unused public functions
7. Fix kg_retrieval.py json import - move to module level
8. Remove unused imports (Set in kg_retrieval, Callable in adaptive/consolidation)

**P3 - LOW (Backlog):**
9. Add pip caching to CI
10. Document or remove unused API surface (decay_for_entry, decay_preview, kg_enhanced_recall, etc.)

---
Audit completed: 2026-04-13
Files analyzed: 50+ Python source files, 1 CI workflow, 17 test files
