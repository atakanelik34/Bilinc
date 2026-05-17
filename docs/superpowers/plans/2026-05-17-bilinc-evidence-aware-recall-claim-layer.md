# Bilinc Evidence-Aware Recall + Claim Layer Implementation Plan

> **For Hermes/Codex:** Execute this plan as `/goal` contracts, one sprint at a time. Use `software-development/test-driven-development` before code changes, `writing-skills/verification-before-completion` before success claims, and `requesting-code-review` before merge/release. Do not change memory provider, model/provider, production deployment, or live `/Users/busecimen/bilinc.db` without Atakan approval.

**Goal:** Turn Bilinc from a strong verifiable memory state plane into a measurable, claim-attributed, evidence-aware agent brain substrate.

**Architecture:** Add capability in layers without replacing Bilinc’s backend or philosophical core: first add opt-in eval capture/replay around existing recall, then add an attributed claims projection, then add a read-only contradiction probe, then expose recall profiles, then add entity/backlink projection. Each sprint must be separately shippable, backward-compatible, and locally verified.

**Tech Stack:** Python 3.10+, SQLite default backend, optional PostgreSQL backend, pytest, MCP server v2, Bilinc StatePlane, existing storage backends, existing AGM/verification/audit/KG modules.

---

## Concern Classification

Primary concern: `agent-memory`.

Secondary concerns:
- `security-critical` if capture/redaction touches secrets or private data.
- `public-facing` only if benchmark/claim results are published later.
- `infra-prod` only if applied to live Hermes/Bilinc production runtime.

Approval gates:
- No memory backend switch.
- No provider/model switch.
- No destructive migration on live DB.
- No mutation of `/Users/busecimen/bilinc.db` beyond normal dev tests without approval.
- No public benchmark or marketing claim without fresh reproduction evidence.

---

## /goal Contract Map

Use this exact operating frame for each sprint.

```yaml
goal:
  objective: "Implement the named Bilinc sprint"
  measurable_done_state: "All sprint tests pass, docs updated, focused verification run recorded, no live DB mutation without approval"
  constraints:
    - "Preserve current Bilinc API compatibility"
    - "SQLite remains default"
    - "Capture features are opt-in and off by default"
    - "No model/provider switch"
    - "No destructive data changes"
    - "No secret leakage in logs, eval exports, or reports"
  allowed_tools:
    - "file edits in Bilinc repo"
    - "pytest/ruff/local CLI"
    - "read-only Bilinc/Vault recall"
  risk_class: "medium"
  approval_gates:
    - "pause before live DB migration"
    - "pause before provider/model-backed judging"
    - "pause before publishing benchmark claims"
  budget:
    max_runtime_minutes: 240
    max_cost_usd: 0
  verification:
    - "targeted pytest for changed modules"
    - "full related pytest slice"
    - "CLI smoke where applicable"
    - "MCP handler smoke where applicable"
  final_receipt:
    output: "changed files + commands + results + caveats"
```

---

## Strategic 1-3-1

**Problem:** Bilinc has strong truth-management primitives but needs productized retrieval measurement, attributed claims, and evidence-aware contradiction workflows to become the obvious verifiable agent brain.

### Option A: Eval-first hardening

Implement retrieval capture/replay before touching recall or claims.

Pros:
- Lowest architectural risk.
- Gives immediate regression protection.
- Helps every future recall/claim/contradiction change.
- Public-safe proof surface later.

Cons:
- Does not immediately create the “who believes what” differentiator.
- Less exciting as a product feature.

### Option B: Claim-layer-first differentiation

Implement first-class attributed `claims` projection before eval machinery.

Pros:
- Biggest strategic moat.
- Directly strengthens Bilinc positioning against GBrain/Mem0/Zep.
- Unlocks better contradiction and provenance stories.

Cons:
- Higher schema/API design risk.
- More migration/test surface.
- Without replay harness, retrieval changes can regress silently.

### Option C: Full-stack vertical slice

Implement minimal versions of capture, claims, contradiction probe, and recall profiles in one branch.

Pros:
- Fastest demo path.
- Shows whole product story end-to-end.
- Useful for narrative and roadmap validation.

Cons:
- Highest risk of shallow implementation.
- Harder to test cleanly.
- More likely to introduce incompatible abstractions.

### Recommendation

Choose Option A first, then Option B. The correct sequence is: protect recall with capture/replay, then add claim projection, then contradiction probe. Bilinc’s moat is truth; the engineering discipline must match that claim.

---

## Sprint Overview

### Sprint 0: Baseline + safety harness

Purpose: establish current behavior and prevent accidental live-state damage.

Deliverables:
- baseline test command inventory
- repo state check
- no-live-DB test rule documented
- fixtures for temp SQLite StatePlane

Definition of Done:
- focused baseline tests pass or failures are documented as pre-existing
- plan saved in repo
- no live DB modified

### Sprint 1: Retrieval capture/replay

Purpose: add opt-in regression harness for recall behavior.

Deliverables:
- eval capture schema/storage
- capture wrapper around recall/smart-recall paths
- export JSONL
- replay JSONL
- metrics: mean Jaccard@k, top-1 stability, latency delta, top regressions

Definition of Done:
- capture is off by default
- tests prove no rows are captured unless explicitly enabled
- replay catches a deliberate result-order regression in a fixture

### Sprint 2: Claim projection layer

Purpose: make Bilinc first-class for attributed epistemic state.

Deliverables:
- `Claim` model
- SQLite/Postgres claim storage
- deterministic claim extraction from structured metadata/value
- claim list/search/entity APIs
- MCP tools for claims

Definition of Done:
- claims can be projected from memories without replacing memory entries
- holder/subject/kind/confidence/validity/provenance are queryable
- claims are active/superseded without deleting evidence

### Sprint 3: Read-only contradiction probe

Purpose: measure contradictions surfacing in recall and claims before mutation.

Deliverables:
- pair generator
- deterministic contradiction rules for structured claims
- optional judge seam, disabled by default
- report with hot keys/entities and suggested actions
- no automatic revise/forget

Definition of Done:
- probe is read-only except eval report table/file
- Wilson CI shown when n is sufficient
- suggested actions are strings, not executed operations

### Sprint 4: Recall profiles

Purpose: expose quality/cost/safety modes in Bilinc-native language.

Deliverables:
- `fast`, `balanced`, `verified`, `deep` profiles
- profile resolver
- MCP/CLI parameter support
- profile-specific metadata in results

Definition of Done:
- existing calls preserve current default behavior
- profile behavior is tested and documented
- verified/deep profiles include provenance/contradiction metadata where available

### Sprint 5: Entity/backlink projection

Purpose: make KG recall compound automatically from actual memory content.

Deliverables:
- entities table/projection
- entity_mentions table/projection
- aliases
- entity-centric recall helpers
- KG seed integration

Definition of Done:
- memory commits can project entity mentions
- entity recall returns source keys with provenance
- KG spreading can use entity seeds

### Sprint 6: Public-safe benchmark and positioning package

Purpose: produce reproducible engineering proof without overclaiming.

Deliverables:
- reproducible benchmark commands
- updated README/docs if approved
- secret-safe evidence receipt
- public-safe language draft

Definition of Done:
- claims backed by command output and artifacts
- no private ReARC memory leaked
- Atakan approval before publishing

---

## Detailed Implementation Tasks

## Sprint 0: Baseline + Safety Harness

### Task 0.1: Record repo and test baseline

**Objective:** Establish a clean starting point before implementation.

**Files:**
- Read-only: repo state
- Create: `docs/superpowers/plans/2026-05-17-bilinc-evidence-aware-recall-claim-layer.md` already contains this plan

**Step 1: Check git state**

Run:
```bash
git status --short --branch
git rev-parse --show-toplevel
git branch --show-current
```

Expected:
- working tree state understood before code changes
- branch intentionally selected

**Step 2: Run focused baseline tests**

Run:
```bash
python3 -m pytest tests/test_core.py tests/test_sqlite_integration.py tests/test_mcp_server_v2.py -q
```

Expected:
- PASS or documented pre-existing failures

**Step 3: Run style baseline**

Run:
```bash
python3 -m ruff check src/bilinc tests
```

Expected:
- PASS or documented pre-existing issues

### Task 0.2: Add eval fixture helpers

**Objective:** Provide isolated temp StatePlane fixtures for eval tests.

**Files:**
- Modify: `tests/conftest.py` if present, otherwise create helpers inside new test modules
- Test: `tests/test_eval_capture.py`

**Step 1: Inspect existing fixture style**

Run:
```bash
python3 -m pytest --fixtures -q | grep -i bilinc || true
```

Expected:
- know whether shared fixtures exist

**Step 2: Prefer local fixtures over global mutation**

If no suitable fixture exists, each new eval test should instantiate:

```python
from bilinc import StatePlane
from bilinc.storage.sqlite import SQLiteBackend

async def make_temp_plane(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "test.db"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.initialize()
    return plane
```

Expected:
- every test uses `tmp_path`
- no test touches `/Users/busecimen/bilinc.db`

---

## Sprint 1: Retrieval Capture/Replay

### Task 1.1: Add eval capture data model

**Objective:** Define stable in-memory/dataclass shapes for captured recall rows and replay results.

**Files:**
- Create: `src/bilinc/eval/__init__.py`
- Create: `src/bilinc/eval/capture.py`
- Test: `tests/test_eval_capture.py`

**Step 1: Write failing tests**

Add tests for:
- capture disabled by default
- config/env enables capture
- secret-looking query is redacted/scrubbed
- retrieved keys are deduped and serialized as JSONL

Suggested test names:
```python
def test_eval_capture_disabled_by_default(tmp_path): ...
def test_eval_capture_enabled_by_env(tmp_path, monkeypatch): ...
def test_eval_capture_scrubs_secret_like_values(): ...
def test_eval_capture_serializes_jsonl_row(): ...
```

**Step 2: Run RED**

Run:
```bash
python3 -m pytest tests/test_eval_capture.py -q
```

Expected:
- FAIL because module does not exist

**Step 3: Implement minimal capture module**

Add:
```python
@dataclass
class EvalCaptureRow:
    schema_version: int
    tool_name: str
    query: str
    retrieved_keys: list[str]
    retrieved_scores: list[float]
    memory_types: list[str]
    latency_ms: int
    created_at: float
    detail: dict[str, Any]
```

Functions:
- `capture_enabled(config: dict | None = None) -> bool`
- `scrub_query(query: str) -> str`
- `row_to_jsonl(row: EvalCaptureRow) -> str`
- `row_from_jsonl(line: str) -> EvalCaptureRow`

Secret scrub rules:
- replace `sk-...`, `tp-...`, bearer-looking tokens, GitHub `ghp_...`, long hex/api tokens with `[REDACTED]`
- cap query length

**Step 4: Run GREEN**

Run:
```bash
python3 -m pytest tests/test_eval_capture.py -q
```

Expected:
- PASS

### Task 1.2: Add capture storage table/file abstraction

**Objective:** Persist capture rows in SQLite without coupling to live DB.

**Files:**
- Modify: `src/bilinc/storage/sqlite.py`
- Create or modify: `src/bilinc/eval/capture.py`
- Test: `tests/test_eval_capture.py`

**Step 1: Write failing storage tests**

Tests:
- `eval_candidates` table exists after backend init
- insert/list export works
- old rows can be filtered by timestamp

Expected schema:
```sql
CREATE TABLE IF NOT EXISTS eval_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  schema_version INTEGER NOT NULL DEFAULT 1,
  tool_name TEXT NOT NULL,
  query TEXT NOT NULL,
  retrieved_keys TEXT NOT NULL DEFAULT '[]',
  retrieved_scores TEXT NOT NULL DEFAULT '[]',
  memory_types TEXT NOT NULL DEFAULT '[]',
  latency_ms INTEGER NOT NULL DEFAULT 0,
  detail TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL
)
```

**Step 2: Run RED**

Run:
```bash
python3 -m pytest tests/test_eval_capture.py::test_eval_candidates_table_exists tests/test_eval_capture.py::test_eval_capture_insert_and_export -q
```

Expected:
- FAIL

**Step 3: Implement storage methods**

In `SQLiteBackend.init()` create table.

Add methods:
- `record_eval_candidate(row)`
- `list_eval_candidates(since: float | None = None, limit: int | None = None)`

Keep methods optional: if other backends do not implement them, capture fails closed with no impact on recall.

**Step 4: Run GREEN**

Run:
```bash
python3 -m pytest tests/test_eval_capture.py -q
```

Expected:
- PASS

### Task 1.3: Capture recall and smart recall results

**Objective:** Wrap existing recall paths with opt-in capture.

**Files:**
- Modify: `src/bilinc/core/stateplane.py`
- Modify: `src/bilinc/mcp_server/server_v2.py` if smart recall is MCP-only
- Test: `tests/test_eval_capture.py`

**Step 1: Locate recall functions**

Search:
```bash
python3 - <<'PY'
from pathlib import Path
for p in Path('src/bilinc').rglob('*.py'):
    s=p.read_text(errors='ignore')
    if 'def recall' in s or 'recall_smart' in s or 'bilinc_recall_smart' in s:
        print(p)
PY
```

**Step 2: Write failing tests**

Tests:
- committing 3 memories and calling recall with capture off writes 0 rows
- enabling capture writes 1 row with retrieved keys
- smart recall capture includes reflection metadata if available

**Step 3: Run RED**

Run:
```bash
python3 -m pytest tests/test_eval_capture.py::test_recall_capture_off_by_default tests/test_eval_capture.py::test_recall_capture_records_retrieved_keys -q
```

Expected:
- FAIL

**Step 4: Implement capture wrapper**

Implementation rule:
- measure latency around recall call
- build row after results are known
- swallow capture errors, never break recall
- include tool_name: `recall` or `bilinc_recall_smart`

**Step 5: Run GREEN**

Run:
```bash
python3 -m pytest tests/test_eval_capture.py -q
```

Expected:
- PASS

### Task 1.4: Add export/replay CLI

**Objective:** Make captured recall behavior replayable from command line.

**Files:**
- Modify: `src/bilinc/cli/main.py`
- Create: `src/bilinc/eval/replay.py`
- Test: `tests/test_cli_error_paths.py` or create `tests/test_eval_replay.py`

**Step 1: Write failing tests**

CLI expectations:
```bash
bilinc --db ./test.db eval export --since 7d
bilinc --db ./test.db eval replay --against baseline.jsonl
```

Replay output JSON shape:
```json
{
  "schema_version": 1,
  "summary": {
    "rows_total": 0,
    "rows_replayed": 0,
    "mean_jaccard": 1.0,
    "top1_stability_rate": 1.0,
    "mean_latency_delta_ms": 0
  },
  "regressions": []
}
```

**Step 2: Implement metrics**

Functions:
- `jaccard(a: list[str], b: list[str]) -> float`
- `top1_same(a, b) -> bool`
- `replay_rows(plane, rows, limit=None) -> ReplayReport`

**Step 3: Add CLI subcommands**

Keep CLI minimal:
- `eval export`: prints JSONL to stdout
- `eval replay`: prints JSON summary

**Step 4: Verify**

Run:
```bash
python3 -m pytest tests/test_eval_capture.py tests/test_eval_replay.py -q
```

Expected:
- PASS

### Sprint 1 Verification Gate

Run:
```bash
python3 -m pytest tests/test_eval_capture.py tests/test_eval_replay.py tests/test_sqlite_integration.py -q
python3 -m ruff check src/bilinc/eval src/bilinc/storage/sqlite.py src/bilinc/core/stateplane.py src/bilinc/cli/main.py
```

Acceptance:
- capture off by default
- capture opt-in works
- replay metrics stable
- no live DB mutation

---

## Sprint 2: Claim Projection Layer

### Task 2.1: Add Claim model

**Objective:** Define first-class claim shape without changing MemoryEntry semantics.

**Files:**
- Modify: `src/bilinc/core/models.py`
- Test: `tests/test_claims.py`

**Step 1: Write failing tests**

Test required fields:
- id
- memory_key
- holder
- subject
- claim
- kind
- confidence
- valid_at/invalid_at
- source
- provenance_id
- active
- superseded_by

Kinds:
```python
class ClaimKind(str, Enum):
    FACT = "fact"
    BELIEF = "belief"
    PREFERENCE = "preference"
    COMMITMENT = "commitment"
    PREDICTION = "prediction"
    HUNCH = "hunch"
```

**Step 2: Run RED**

Run:
```bash
python3 -m pytest tests/test_claims.py::test_claim_model_defaults -q
```

Expected:
- FAIL

**Step 3: Implement model**

Add `Claim` dataclass or Pydantic-compatible class using existing project style.

**Step 4: Run GREEN**

Run:
```bash
python3 -m pytest tests/test_claims.py -q
```

Expected:
- PASS

### Task 2.2: Add SQLite claim storage

**Objective:** Persist claims as derived projection from memories.

**Files:**
- Modify: `src/bilinc/storage/sqlite.py`
- Test: `tests/test_claims.py`

Schema:
```sql
CREATE TABLE IF NOT EXISTS claims (
  id TEXT PRIMARY KEY,
  memory_key TEXT NOT NULL,
  holder TEXT NOT NULL,
  subject TEXT NOT NULL,
  claim TEXT NOT NULL,
  kind TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.5,
  valid_at REAL,
  invalid_at REAL,
  source TEXT DEFAULT '',
  provenance_id TEXT DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  superseded_by TEXT,
  metadata TEXT DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
)
```

Indexes:
- `(memory_key)`
- `(holder, active)`
- `(subject, active)`
- `(kind, active)`
- FTS5 over claim/subject/holder if available

**Step 1: Write failing tests**

- table exists
- save/list/search claims
- supersede claim marks old inactive and links `superseded_by`

**Step 2: Implement methods**

Add to SQLite backend:
- `save_claim(claim)`
- `list_claims(holder=None, subject=None, kind=None, active=True, limit=100)`
- `search_claims(query, limit=10)`
- `supersede_claim(old_id, new_claim)`

**Step 3: Verify**

Run:
```bash
python3 -m pytest tests/test_claims.py -q
```

Expected:
- PASS

### Task 2.3: Add deterministic claim projector

**Objective:** Project structured claims from memory metadata/value without relying on LLMs.

**Files:**
- Create: `src/bilinc/core/claims.py`
- Modify: `src/bilinc/core/stateplane.py`
- Test: `tests/test_claims.py`

Input patterns:
1. Explicit metadata:
```json
{
  "claims": [
    {"holder":"user", "subject":"ReARC", "claim":"ReARC uses Bilinc", "kind":"fact", "confidence":0.9}
  ]
}
```

2. Explicit value envelope:
```json
{
  "claim": "Atakan prefers concise answers",
  "holder": "atakan",
  "subject": "atakan",
  "kind": "preference"
}
```

No freeform LLM extraction in this sprint.

**Step 1: Write failing tests**

- metadata claims become stored claims after commit
- invalid kind rejected or skipped with warning
- duplicate claim for same memory_key/claim does not create duplicate rows

**Step 2: Implement projector**

Functions:
- `extract_claims_from_entry(entry) -> list[Claim]`
- `normalize_claim_kind(value) -> ClaimKind | None`
- `claim_id_for(memory_key, claim_text, holder, subject) -> stable hash`

**Step 3: Wire to StatePlane commit**

After successful memory save, project claims best-effort.

Do not let claim projection failure break commit unless strict mode is later added.

**Step 4: Verify**

Run:
```bash
python3 -m pytest tests/test_claims.py tests/test_core.py -q
```

Expected:
- PASS

### Task 2.4: Add MCP claim tools

**Objective:** Expose claims through MCP without replacing existing recall.

**Files:**
- Modify: `src/bilinc/mcp_server/server_v2.py`
- Test: `tests/test_mcp_server_v2.py` and/or `tests/test_claims.py`

Tools:
- `claims_list`
- `claims_search`
- `claims_for_entity`
- optional `claims_supersede` only if clearly non-destructive and tested; otherwise defer

**Step 1: Add tool schemas**

Properties:
- holder
- subject/entity
- kind
- active
- limit
- query

**Step 2: Add handlers**

Return JSON with:
- tool
- success
- count
- claims

**Step 3: Verify**

Run:
```bash
python3 -m pytest tests/test_claims.py tests/test_mcp_server_v2.py -q
```

Expected:
- PASS

### Sprint 2 Verification Gate

Run:
```bash
python3 -m pytest tests/test_claims.py tests/test_core.py tests/test_sqlite_integration.py tests/test_mcp_server_v2.py -q
python3 -m ruff check src/bilinc tests/test_claims.py
```

Acceptance:
- claims are projection, not replacement
- no LLM/provider dependency
- no live DB migration without approval

---

## Sprint 3: Read-Only Contradiction Probe

### Task 3.1: Add contradiction pair model and deterministic rules

**Objective:** Represent contradiction candidates without mutating belief state.

**Files:**
- Create: `src/bilinc/eval/contradictions.py`
- Test: `tests/test_eval_contradictions.py`

Models:
- `ContradictionPair`
- `ContradictionFinding`
- `ContradictionReport`

Deterministic rules v1:
- same holder + same subject + mutually exclusive normalized claim values if metadata provides `predicate`/`object`
- same subject + kind fact + active claims with conflicting exact scalar values
- validity windows overlap before flagging

**Step 1: Write failing tests**

- no contradiction when validity windows do not overlap
- contradiction when same predicate has different active scalar values
- debate/opinion claims are lower severity than facts

**Step 2: Implement deterministic detector**

No LLM judge in v1.

**Step 3: Verify**

Run:
```bash
python3 -m pytest tests/test_eval_contradictions.py -q
```

Expected:
- PASS

### Task 3.2: Generate pairs from recall results and claims

**Objective:** Probe contradictions that would actually surface during recall.

**Files:**
- Modify: `src/bilinc/eval/contradictions.py`
- Test: `tests/test_eval_contradictions.py`

Pair sources:
- top-K memory results from query
- active claims linked to those memory keys
- claims sharing subject/entity

**Step 1: Write failing tests**

- seed memories and claims
- query returns top-K
- probe creates memory-vs-claim and claim-vs-claim pairs

**Step 2: Implement pair generation**

Inputs:
- `plane`
- `queries: list[str]`
- `top_k: int = 5`

**Step 3: Verify**

Run:
```bash
python3 -m pytest tests/test_eval_contradictions.py -q
```

Expected:
- PASS

### Task 3.3: Add report metrics and Wilson CI

**Objective:** Make contradiction rate statistically honest.

**Files:**
- Modify: `src/bilinc/eval/contradictions.py`
- Test: `tests/test_eval_contradictions.py`

Report fields:
- queries_evaluated
- queries_with_contradiction
- total_pairs
- total_findings
- contradiction_rate
- wilson_ci_95_low/high when n >= 30
- small_sample_note when n < 30
- hot_keys
- hot_subjects
- suggested_actions

**Step 1: Write failing tests**

- Wilson interval known values
- small sample note for n < 30
- hot subjects sorted by count/severity

**Step 2: Implement report**

Use pure Python math; no new dependency.

**Step 3: Verify**

Run:
```bash
python3 -m pytest tests/test_eval_contradictions.py -q
```

Expected:
- PASS

### Task 3.4: Add CLI/MCP read-only surface

**Objective:** Let operators run contradiction probe without mutation.

**Files:**
- Modify: `src/bilinc/cli/main.py`
- Modify: `src/bilinc/mcp_server/server_v2.py`
- Test: `tests/test_eval_contradictions.py`, `tests/test_mcp_server_v2.py`

CLI:
```bash
bilinc --db ./agent.db eval contradictions --query "payment state" --top-k 5 --json
bilinc --db ./agent.db eval contradictions --queries queries.txt --top-k 5 --json
```

MCP tool:
- `bilinc_contradiction_probe`

**Step 1: Write failing tests**

- CLI returns JSON
- MCP returns JSON text with `success: true`
- no memory rows are modified

**Step 2: Implement**

Ensure all handlers say read-only in description.

**Step 3: Verify**

Run:
```bash
python3 -m pytest tests/test_eval_contradictions.py tests/test_mcp_server_v2.py -q
```

Expected:
- PASS

### Sprint 3 Verification Gate

Run:
```bash
python3 -m pytest tests/test_eval_contradictions.py tests/test_claims.py tests/test_core.py tests/test_mcp_server_v2.py -q
python3 -m ruff check src/bilinc/eval src/bilinc/mcp_server/server_v2.py src/bilinc/cli/main.py
```

Acceptance:
- probe is read-only
- deterministic rules work without provider/model
- suggested actions are not executed

---

## Sprint 4: Recall Profiles

### Task 4.1: Add recall profile resolver

**Objective:** Define Bilinc-native recall modes.

**Files:**
- Create: `src/bilinc/core/recall_profiles.py`
- Test: `tests/test_recall_profiles.py`

Profiles:
```python
fast = {
  "kg": False,
  "reflection": False,
  "verification_trace": False,
  "contradiction_preview": False,
}

balanced = {
  "kg": True,
  "reflection": True,
  "max_reflections": 2,
}

verified = {
  "kg": True,
  "reflection": True,
  "verification_trace": True,
  "contradiction_preview": True,
}

deep = {
  "kg": True,
  "reflection": True,
  "max_reflections": 3,
  "verification_trace": True,
  "contradiction_preview": True,
  "entity_expansion": True,
}
```

**Step 1: Write failing tests**

- known profiles resolve
- unknown profile errors clearly
- default preserves current behavior

**Step 2: Implement resolver**

Function:
- `resolve_recall_profile(profile: str | None, overrides: dict | None = None) -> RecallProfile`

**Step 3: Verify**

Run:
```bash
python3 -m pytest tests/test_recall_profiles.py -q
```

Expected:
- PASS

### Task 4.2: Thread profile into smart recall

**Objective:** Make profile influence smart recall without breaking existing API.

**Files:**
- Modify: `src/bilinc/core/stateplane.py`
- Modify: `src/bilinc/mcp_server/server_v2.py`
- Test: `tests/test_recall_profiles.py`, `tests/test_mcp_server_v2.py`

**Step 1: Write failing tests**

- `profile="fast"` uses no reflections
- `profile="verified"` includes verification/contradiction metadata in payload if available
- omitted profile matches current default

**Step 2: Implement**

Thread profile as optional parameter.

Do not change default behavior silently.

**Step 3: Verify**

Run:
```bash
python3 -m pytest tests/test_recall_profiles.py tests/test_mcp_server_v2.py -q
```

Expected:
- PASS

### Task 4.3: Document profiles

**Objective:** Make profile semantics clear for operators and agents.

**Files:**
- Modify: `README.md`
- Modify or create: `docs/recall-profiles.md`

**Step 1: Add docs**

Include:
- when to use each profile
- cost/safety semantics
- examples

**Step 2: Verify docs references**

Run:
```bash
python3 -m pytest tests/test_recall_profiles.py -q
```

Expected:
- PASS

### Sprint 4 Verification Gate

Run:
```bash
python3 -m pytest tests/test_recall_profiles.py tests/test_mcp_server_v2.py tests/test_core.py -q
python3 -m ruff check src/bilinc/core/recall_profiles.py src/bilinc/core/stateplane.py src/bilinc/mcp_server/server_v2.py
```

Acceptance:
- existing behavior preserved
- profiles are visible in result metadata
- verified/deep add evidence metadata, not magical truth claims

---

## Sprint 5: Entity/Backlink Projection

### Task 5.1: Add entity models and storage

**Objective:** Track entities and memory mentions as a projection.

**Files:**
- Create: `src/bilinc/core/entities.py`
- Modify: `src/bilinc/storage/sqlite.py`
- Test: `tests/test_entities.py`

Tables:
```sql
CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY,
  canonical_name TEXT NOT NULL,
  entity_type TEXT NOT NULL DEFAULT 'unknown',
  aliases TEXT NOT NULL DEFAULT '[]',
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
)

CREATE TABLE IF NOT EXISTS entity_mentions (
  id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL,
  memory_key TEXT NOT NULL,
  mention_text TEXT NOT NULL,
  source TEXT DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0.5,
  created_at REAL NOT NULL
)
```

**Step 1: Write failing tests**

- create entity
- add alias
- add mention
- list memories for entity

**Step 2: Implement storage**

Add backend methods:
- `save_entity`
- `save_entity_mention`
- `find_entity`
- `list_entity_mentions`

**Step 3: Verify**

Run:
```bash
python3 -m pytest tests/test_entities.py -q
```

Expected:
- PASS

### Task 5.2: Add deterministic entity extraction

**Objective:** Extract useful entity mentions without LLM dependency.

**Files:**
- Modify: `src/bilinc/core/entities.py`
- Modify: `src/bilinc/core/stateplane.py`
- Test: `tests/test_entities.py`

Extraction sources:
- metadata `entities` list
- metadata `relations`
- claim subject/holder
- conservative capitalized phrase heuristic only if safe and tested

**Step 1: Write failing tests**

- metadata entities create mentions
- claim subject creates entity mention
- boring lowercase text does not create noisy entities

**Step 2: Implement projector**

Function:
- `extract_entities_from_entry(entry) -> list[EntityMention]`

**Step 3: Verify**

Run:
```bash
python3 -m pytest tests/test_entities.py tests/test_claims.py -q
```

Expected:
- PASS

### Task 5.3: Integrate entity seeds with KG recall

**Objective:** Use entity projection to improve graph recall.

**Files:**
- Modify: `src/bilinc/core/kg_retrieval.py`
- Modify: `src/bilinc/core/stateplane.py`
- Test: `tests/test_entities.py`, `tests/test_knowledge_graph.py`

**Step 1: Write failing test**

- commit memory mentioning entity A
- query entity A
- recall returns memory through entity mention even if keyword signal is weak

**Step 2: Implement entity seed expansion**

Keep bounded:
- max entity seeds 5
- max mentions per entity 20
- no recursive explosion

**Step 3: Verify**

Run:
```bash
python3 -m pytest tests/test_entities.py tests/test_knowledge_graph.py -q
```

Expected:
- PASS

### Sprint 5 Verification Gate

Run:
```bash
python3 -m pytest tests/test_entities.py tests/test_claims.py tests/test_knowledge_graph.py tests/test_core.py -q
python3 -m ruff check src/bilinc/core/entities.py src/bilinc/core/kg_retrieval.py src/bilinc/storage/sqlite.py
```

Acceptance:
- entity projection is conservative
- no noisy stubs
- entity recall returns provenance/source memory keys

---

## Sprint 6: Public-Safe Benchmark + Positioning Package

### Task 6.1: Reproduce local benchmarks

**Objective:** Generate fresh evidence before any public claim.

**Files:**
- Read-only: benchmark scripts
- Create: `benchmarks/results/2026-05-XX-evidence-aware-recall.md` if benchmark path exists, otherwise Vault only

Run:
```bash
python3 -m pytest tests/test_eval_capture.py tests/test_claims.py tests/test_eval_contradictions.py tests/test_recall_profiles.py tests/test_entities.py -q
python3 benchmarks/longmemeval_bench.py longmemeval_s_cleaned.json --mode hybrid
```

Expected:
- test suite pass
- benchmark output captured with command/date/environment

If dataset is missing, do not fake results. Record missing dataset as blocker.

### Task 6.2: Update docs only after evidence

**Objective:** Keep README claims safe and reproducible.

**Files:**
- Modify: `README.md`
- Create: `docs/evidence-aware-recall.md`

Rules:
- State repository benchmark, not hosted-service claim.
- Include reproduction commands.
- Separate implemented features from roadmap.

### Task 6.3: Save Bilinc/Vault receipts

**Objective:** Preserve durable project state.

**Files/systems:**
- Bilinc semantic memory
- Vault note under `00-Meta/Agent-Workflows/` or product docs

Capture:
- changed files
- tests run
- benchmark outputs
- caveats
- next sprint

---

## Sprint Receipts
### Final Sprint 1-3 Audit/Fix Receipt — 2026-05-17 12:15 +03, updated after post-fix review

Audit result:
- Sprint 1, Sprint 2, and Sprint 3 are complete after final hardening pass.
- Independent review initially found replay, projection, forget/privacy, stale-claim, detail-redaction, and PostgreSQL parity gaps.
- A post-handoff independent review then found four additional release-blocking/high-risk issues: rollback left stale projected claims, replay could self-capture when eval capture was enabled, inactive/expired claims could leak through search/list/contradiction surfaces, and `retrieved_keys` were not redacted.
- All release-blocking/high-risk findings were fixed.
- Final independent post-fix review found no release-blocking or high-risk issues.

Additional fixes after initial sprint receipts:
- Replay now preserves captured `memory_type` recall semantics instead of falling back to key lookup.
- Eval capture recursively scrubs nested `detail` payloads, including smart-recall query expansions.
- Eval capture now also scrubs secret-shaped `retrieved_keys` before persistence/export.
- Replay suppresses eval capture side effects while replaying rows, then restores the previous suppression state.
- MCP `commit_mem` / AGM commit path now projects structured claims.
- Updating a source memory deactivates stale projected claims for the same `memory_key`.
- Deleting/forgetting a source memory deletes its projected claims from SQLite/PostgreSQL storage paths.
- Rollback now deletes/reprojects projected claims to match the restored source memory state.
- Active claim list/search and contradiction probes now exclude inactive, future-valid, and expired claims by default.
- Malformed claim confidence skips only the bad structured claim rather than suppressing all claims for an entry.
- PostgreSQL parity added for claim storage and eval capture/listing methods.
- CLI read-only contradiction probe added under `bilinc eval contradictions`, including query-linked probe mode.

Final verification:
- RED blocker regression tests before fixes: 5 failing tests covering retrieved-key redaction, replay capture side effects, inactive/expired claim filtering, rollback stale claims, and expired contradiction suppression.
- Blocker regression retest after fixes: `5 passed in 0.57s`.
- Focused sprint suite: `python3 -m pytest tests/test_eval_capture.py tests/test_eval_replay.py tests/test_eval_contradictions.py tests/test_claims.py tests/test_core.py tests/test_sqlite_integration.py tests/test_mcp_server_v2.py tests/test_postgres_integration.py -q` → `124 passed, 5 skipped in 1.85s`.
- Full test suite: `python3 -m pytest -q` → `296 passed, 5 skipped in 52.20s`.
- Changed-path ruff: `python3 -m ruff check src/bilinc/eval src/bilinc/storage/postgres.py src/bilinc/storage/sqlite.py src/bilinc/core/models.py src/bilinc/core/claims.py src/bilinc/core/stateplane.py src/bilinc/mcp_server/server_v2.py src/bilinc/cli/main.py tests/test_eval_capture.py tests/test_eval_replay.py tests/test_eval_contradictions.py tests/test_claims.py tests/test_postgres_integration.py tests/conftest.py` → `All checks passed!`.
- `git diff --check` → clean.
- `python3 -m build` → built `bilinc-1.2.5.tar.gz` and `bilinc-1.2.5-py3-none-any.whl`.
- Adversarial SQLite probe covering stale update, delete cleanup, rollback cleanup, replay no-self-capture, retrieved-key redaction, and contradiction sanity → `{"active_after_update": ["S status A2"], "contradictions_count": 0, "delete_claims_remaining": [], "ok": true, "redacted_key": "[REDACTED]", "replay_capture_rows_written": 0, "rollback_claims_remaining": []}`.
- Final independent review: no release-blocking/high-risk issues found; reviewer also ran `49 passed` focused regression suite and an independent SQLite rollback/expiry/replay probe.

Remaining caveat:
- Full repo ruff still reports pre-existing unrelated lint issues in legacy files outside the changed-path gate.

### Sprint 4 Recall Profiles — 2026-05-17 12:50 +03

Changed files:
- `src/bilinc/core/stateplane.py`
- `src/bilinc/mcp_server/server_v2.py`
- `src/bilinc/cli/main.py`
- `tests/test_recall_profiles.py`

Implemented:
- Named recall profiles: `fast`, `balanced`, `verified`, and `deep`.
- `StatePlane.resolve_recall_profile()` with stable profile parameters.
- `StatePlane.recall_profiled()` wrapping reflective recall without changing default legacy calls.
- `fast` profile disables reflection loop.
- `verified`/`deep` profiles attach read-only evidence metadata from projected claims and contradiction reports where available.
- MCP `bilinc_recall_smart` accepts `profile` while preserving explicit legacy `max_reflections`/`adequacy_threshold` behavior when no profile is supplied.
- CLI `bilinc recall --query ... --profile ... --json` emits full profile metadata and results.

Verification:
- RED first: `python3 -m pytest tests/test_recall_profiles.py -q` → 5 failing tests for missing resolver/profiled recall/MCP profile/CLI args.
- Independent review found two high-risk issues before commit: verified/deep evidence could disclose contradiction details from unrecalled same-subject memories, and MCP `profile` could override explicit `max_reflections`/`adequacy_threshold` when clients sent a default profile.
- Added RED regression tests for both blockers: evidence scope leak and explicit-parameter precedence failed before fixes.
- GREEN: `python3 -m pytest tests/test_recall_profiles.py -q` → `7 passed in 0.89s`.
- Related suite: `python3 -m pytest tests/test_recall_profiles.py tests/test_eval_contradictions.py tests/test_claims.py tests/test_core.py tests/test_mcp_server_v2.py -q` → `86 passed in 2.15s`.
- Full suite: `python3 -m pytest -q` → `303 passed, 5 skipped in 53.63s`.
- Changed-path ruff: `python3 -m ruff check src/bilinc/core/stateplane.py src/bilinc/mcp_server/server_v2.py src/bilinc/cli/main.py tests/test_recall_profiles.py` → `All checks passed!`.
- `git diff --check` → clean.
- `python3 -m build` → built `bilinc-1.2.5.tar.gz` and `bilinc-1.2.5-py3-none-any.whl`.
- Adversarial SQLite/MCP probe for recalled-key-scoped evidence, no unrecalled object/key leakage, MCP explicit-parameter precedence, and build smoke → `{"contradiction_count": 0, "leaks_unrecalled_key": false, "leaks_unrecalled_object": false, "mcp_adequacy_threshold": 0.99, "mcp_max_reflections": 0, "mcp_queries_tried_len": 1, "ok": true, "result_keys": ["mem:target"]}`.

Caveats:
- Profile evidence uses deterministic projected claims only; no LLM/provider-backed judging was added.
- No live `/Users/busecimen/bilinc.db` mutation was performed during Sprint 4.

### Sprint 3 Read-Only Contradiction Probe — 2026-05-17 11:38 +03

Changed files:
- `src/bilinc/eval/__init__.py`
- `src/bilinc/eval/contradictions.py`
- `src/bilinc/mcp_server/server_v2.py`
- `tests/test_eval_contradictions.py`
- `tests/test_claims.py`

Implemented:
- `ContradictionPair`, `ContradictionFinding`, and `ContradictionReport` as read-only eval/reporting models.
- Deterministic contradiction detection over active projected claims with same holder, subject, and metadata `predicate`, conflicting scalar metadata `object`, and overlapping validity windows.
- Severity weighting by claim kind, so hunch/opinion-level conflicts are lower severity than fact conflicts.
- Wilson 95% CI helper and small-sample suppression note when evaluated query count is under 30.
- Hot-subject aggregation and suggested-action strings; no automatic revise/forget/supersede operation.
- MCP read-only surface: `claim_contradictions`, backed by projected SQLite claims and returning `read_only: true`.

Verification:
- RED first: `python3 -m pytest tests/test_eval_contradictions.py -q` failed with `ModuleNotFoundError: No module named 'bilinc.eval.contradictions'` before implementation.
- MCP RED: `python3 -m pytest tests/test_claims.py::test_mcp_claim_contradictions_reports_read_only_findings -q` failed with `ImportError: cannot import name '_handle_claim_contradictions'` before MCP wiring.
- `python3 -m pytest tests/test_eval_contradictions.py -q` → `6 passed in 0.02s`
- `python3 -m pytest tests/test_claims.py::test_mcp_claim_contradictions_reports_read_only_findings -q` → `1 passed in 0.60s`
- `python3 -m pytest tests/test_eval_contradictions.py tests/test_claims.py tests/test_core.py tests/test_mcp_server_v2.py -q` → `66 passed in 0.85s`
- `python3 -m pytest tests/test_eval_capture.py tests/test_eval_replay.py tests/test_eval_contradictions.py tests/test_claims.py tests/test_core.py tests/test_sqlite_integration.py tests/test_mcp_server_v2.py -q` → `105 passed in 1.46s`
- `python3 -m ruff check src/bilinc/eval src/bilinc/mcp_server/server_v2.py src/bilinc/cli/main.py tests/test_eval_contradictions.py tests/test_claims.py` → `All checks passed!`
- `git diff --check` → clean
- Adversarial bad-input probe: `PYTHONPATH=src python3 - <<'PY' ... detect_claim_contradictions(...) ... PY` with nested dict object returned `{'findings': 0}`, proving non-scalar objects are ignored rather than flagged/crashing.

Caveats:
- Probe v1 only uses structured projected claim metadata (`predicate`/`object`). It does not infer contradictions from freeform text.
- The operational surface is available through MCP (`claim_contradictions`) and CLI (`bilinc eval contradictions`).
- PostgreSQL claim storage and eval capture/listing methods are implemented in the final hardening pass.
- No live `/Users/busecimen/bilinc.db` mutation was performed beyond the explicit Sprint 3 receipt capture key `bilinc:sprint:evidence-aware-recall:sprint3-receipt`.

### Sprint 2 Claim Projection Layer — 2026-05-17 11:28 +03

Changed files:
- `src/bilinc/core/models.py`
- `src/bilinc/core/claims.py`
- `src/bilinc/storage/sqlite.py`
- `src/bilinc/core/stateplane.py`
- `src/bilinc/mcp_server/server_v2.py`
- `tests/test_claims.py`

Implemented:
- `ClaimKind` enum and `Claim` dataclass as a derived projection linked to source `memory_key`.
- Deterministic claim extraction from explicit metadata claims and explicit value envelopes only.
- Stable claim IDs to prevent duplicate rows for the same source claim.
- Additive SQLite `claims` table with save/list/search/supersede methods.
- Best-effort claim projection after `StatePlane.commit`; projection failures do not break memory commit.
- MCP claim handlers and tool schemas: `claims_list`, `claims_search`, `claims_for_entity`.

Verification:
- RED first: `python3 -m pytest tests/test_claims.py -q` failed with `ModuleNotFoundError: No module named 'bilinc.core.claims'` before implementation.
- `python3 -m pytest tests/test_claims.py tests/test_core.py tests/test_sqlite_integration.py tests/test_mcp_server_v2.py -q` → `85 passed in 1.73s`
- `python3 -m pytest tests/test_eval_capture.py tests/test_eval_replay.py tests/test_claims.py tests/test_core.py tests/test_sqlite_integration.py tests/test_mcp_server_v2.py -q` → `98 passed in 1.52s`
- `python3 -m ruff check src/bilinc/core/models.py src/bilinc/core/claims.py src/bilinc/storage/sqlite.py src/bilinc/core/stateplane.py src/bilinc/mcp_server/server_v2.py tests/test_claims.py tests/conftest.py` → `All checks passed!`
- `git diff --check` → clean
- Adversarial bad-input probe: `tests/test_claims.py::test_extract_claims_from_value_envelope_skips_invalid_kind` → invalid claim kind is skipped; `1 passed in 0.77s`

Caveats:
- Claim extraction is deterministic and structured-only; no LLM/provider dependency was added.
- Claims are projections, not replacement source-of-truth memories.
- SQLite and PostgreSQL parity are implemented for projected claim storage.
- No live `/Users/busecimen/bilinc.db` mutation was performed.

### Sprint 1 Retrieval Capture/Replay — 2026-05-17 11:21 +03

Changed files:
- `src/bilinc/eval/__init__.py`
- `src/bilinc/eval/capture.py`
- `src/bilinc/eval/replay.py`
- `src/bilinc/storage/sqlite.py`
- `src/bilinc/core/stateplane.py`
- `src/bilinc/mcp_server/server_v2.py`
- `src/bilinc/cli/main.py`
- `tests/conftest.py`
- `tests/test_eval_capture.py`
- `tests/test_eval_replay.py`

Implemented:
- Opt-in eval capture model with query redaction and JSONL serialization.
- Additive SQLite `eval_candidates` table plus record/list methods.
- Best-effort recall capture through `StatePlane.recall` and MCP smart recall handler.
- `bilinc eval export` JSONL CLI and `bilinc eval replay` JSON summary CLI.
- Replay metrics: mean Jaccard, top-1 stability, mean latency delta, top regressions.

Verification:
- `python3 -m pytest tests/test_eval_capture.py tests/test_eval_replay.py tests/test_sqlite_integration.py -q` → `39 passed in 2.07s`
- `python3 -m ruff check src/bilinc/eval src/bilinc/storage/sqlite.py src/bilinc/core/stateplane.py src/bilinc/cli/main.py tests/test_eval_capture.py tests/test_eval_replay.py tests/conftest.py` → `All checks passed!`
- `git diff --check` → clean

Caveats:
- Capture remains disabled by default through `BILINC_EVAL_CAPTURE` opt-in.
- No live `/Users/busecimen/bilinc.db` mutation was performed.
- Full repo ruff still has pre-existing issues outside this sprint's changed-path gate unless separately cleaned.

---

## Risk Mitigations Pre-Mortem

### Tigers Addressed

1. **Capture leaks secrets or private content.**
   - Severity: high
   - Mitigation: capture off by default, scrub tokens, cap query length, tests for redaction, no public export without review.
   - Added to: Sprint 1

2. **Claim layer becomes a second source of truth that conflicts with memories.**
   - Severity: high
   - Mitigation: claims are derived projections linked to `memory_key` and provenance; source memory remains canonical evidence.
   - Added to: Sprint 2

3. **Contradiction probe mutates state automatically and damages memory.**
   - Severity: high
   - Mitigation: read-only by design; suggested actions are strings; no `revise`/`forget` execution.
   - Added to: Sprint 3

4. **Recall profiles silently change default behavior.**
   - Severity: medium/high
   - Mitigation: omitted profile preserves current behavior; profile metadata in output; regression tests.
   - Added to: Sprint 4

5. **Entity extraction creates noisy graph garbage.**
   - Severity: medium
   - Mitigation: start with metadata/claims only; conservative heuristic later; no stub creation without evidence.
   - Added to: Sprint 5

6. **Public claims overstate benchmark results.**
   - Severity: high
   - Mitigation: fresh commands required; label repo benchmark; Atakan approval before public-facing update.
   - Added to: Sprint 6

### Accepted Risks

1. **Initial claim extraction is not LLM-powered.**
   - Accepted because provider/model changes are approval-gated and deterministic projection is safer for v1.

2. **SQLite gets new tables.**
   - Accepted because this is additive and backward-compatible if migrations are idempotent.

3. **PostgreSQL parity may lag one sprint.**
   - Accepted only if documented clearly and SQLite default remains correct. Prefer adding Postgres methods in the same sprint when simple.

### Pre-Mortem Run

- Mode: deep
- Tigers: 6
- Elephants: 1

Elephant: Bilinc’s strategic story is stronger than its productized ergonomics. This plan deliberately spends early effort on boring eval/projection surfaces because that is what makes the truth-plane claim credible.

---

## Final Merge Checklist

Before merging any sprint:

```bash
git diff --check
python3 -m pytest <focused tests> -q
python3 -m ruff check <changed paths>
```

Before release/public claim:

```bash
python3 -m pytest tests -q
python3 -m ruff check src/bilinc tests
python3 -m build
```

If tests are skipped or warnings appear, record what they are and whether they matter. Do not report only counts.

---

## Recommended Execution Order

Start with Sprint 1, not Sprint 2.

Reason: claim projection is the bigger strategic differentiator, but retrieval capture/replay is the guardrail that lets us safely evolve recall and later prove the improvement.

Immediate next `/goal`:

```text
/goal Implement Bilinc Sprint 1 retrieval capture/replay
until capture is off by default, opt-in capture writes recall rows, export/replay works, and focused tests pass
while preserving existing recall behavior and not touching live /Users/busecimen/bilinc.db
using only local repo edits and pytest/ruff
pause before any provider/model/backend/live DB change
verify by tests/test_eval_capture.py, tests/test_eval_replay.py, tests/test_sqlite_integration.py, and ruff on changed paths
record progress in this plan and final receipt in Bilinc/Vault
```
