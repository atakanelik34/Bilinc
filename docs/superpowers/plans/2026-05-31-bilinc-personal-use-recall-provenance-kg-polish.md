# Bilinc Personal-Use Recall / Provenance / KG Polish Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. Treat this as a /goal contract: every sprint starts with Bilinc recall/capture, runs TDD, verifies with focused tests, and records a Bilinc receipt. Do not mutate the live `/Users/busecimen/bilinc.db` except explicit receipt keys created through MCP.

**Goal:** Make personal-use Bilinc more pleasant and trustworthy by surfacing why recall results were returned, previewing graph/projection gaps safely, and strengthening deterministic provenance/claim/KG signals without backend migration.

**Architecture:** Keep Bilinc's current SQLite-first/verifiable state-plane identity. Add read-only explanation and diagnostic primitives first, then optionally wire them into MCP/admin preview surfaces. The first sprint must not backfill live data; it only computes deterministic projections from `MemoryEntry` objects or temp SQLite fixtures.

**Tech Stack:** Python 3.10+, pytest, existing `StatePlane`, `KnowledgeGraph`, `MemoryEntry`, SQLiteBackend, MCP server v2 if/when exposed.

**Current Worktree:** `/Users/busecimen/.config/superpowers/worktrees/Bilinc/personal-use-memory-polish`

**Branch:** `feature/personal-use-memory-polish` from `origin/main` commit `08bacb7 Bilinc 2.1.2 CLI activation`.

**Preserve Existing Dirty Work:** Main repo `/Users/busecimen/Downloads/Projeler/Agent/Bilinc` has unrelated dirty change in `src/bilinc/mcp_server/hermes_stdio.py` on `release/bilinc-2.1.2-activation`. Do not touch, reset, stash, or overwrite it.

---

## Concern Classification

- Primary: `agent-memory`
- Secondary: `security-critical` because memory/provenance/retrieval can leak data if evidence scope is wrong.
- Public-facing: no public claim changes in this sprint.
- Infra-prod: no deploy, no live service mutation.

## Approval Gates

Explicit Atakan approval required before:
- Live `/Users/busecimen/bilinc.db` backfill or destructive mutation.
- Memory/backend/provider/storage architecture change.
- Schema migration against live DB.
- PyPI publish, `bilinc.space` deploy, public README/site claims.
- Enabling LLM-based claim/entity extraction by default.

Allowed without further approval under this /goal:
- Local isolated worktree edits.
- Temp SQLite tests.
- Read-only local code inspection.
- Bilinc MCP receipt/capture keys for this goal.
- Clawifi read-only research.

## Baseline Notes

- `python3 -m pytest tests/test_knowledge_graph.py -q` passes: `23 passed`.
- Broader focused baseline `tests/test_claims.py tests/test_recall_profiles.py` currently fails during collection because current `src/bilinc/__init__.py` cloud-only export set does not expose top-level `StatePlane`, while those tests import `from bilinc import StatePlane`. Treat as pre-existing branch/package-surface issue. Do not hide it; either use core imports in new tests or make a scoped compatibility fix only if directly required.
- Existing `KnowledgeGraph` is in-memory NetworkX, with simple deterministic semantic ingest: capitalized words, key-value pairs, memory-entity index, cross-memory edges.
- Existing `recall_intelligent()` already computes lexical/hybrid/entity signals but does not explain them in human-readable form.
- Existing claims projection only extracts explicit structured claims from `metadata.claims` or `entry.value.claim`.

## Research Distillation

Sources captured in Bilinc key `research:bilinc-personal-use-polish-recall-provenance-kg-2026-05-31`:
- Zep/Graphiti: temporal KG edges with provenance and validity windows.
- Microsoft GraphRAG: separate local entity-neighborhood search from global/community-summary search.
- Mem0 Graph Memory: vector memory and graph memory are complementary, not replacements.
- Company-brain writing: permissioned/versioned memory needs provenance, owner, access, confidence, freshness, and authority tier.

Translate into Bilinc without copying competitor architecture:
- No Neo4j/Kuzu/Graphiti migration.
- No LLM extraction by default.
- No live backfill until read-only doctor proves value.

---

# Sprint 1 — Read-Only Graph Doctor + Projection Preview

**Sprint Goal:** Add deterministic, read-only diagnostics that show how much KG/provenance structure Bilinc could project from existing entries before any mutation. This is the safest first sprint and fixes the observed problem: live KG has only 13 nodes / 12 edges despite 345 memory entries.

**Definition of Done:**
- New tests verify projection preview counts and issue detection on synthetic `MemoryEntry` objects.
- New code does not require backend migration or live DB writes.
- Existing `tests/test_knowledge_graph.py` still passes.
- A temp SQLite or pure in-memory adversarial probe proves no live DB mutation.
- Bilinc receipt records changed files and verification output.

### Task 1.1: Add failing tests for projection preview from metadata claims

**Objective:** Specify how graph doctor should derive candidate nodes/edges from explicit structured metadata without mutating `KnowledgeGraph`.

**Files:**
- Modify: `tests/test_knowledge_graph.py`
- Later modify/create: `src/bilinc/core/graph_doctor.py`

**Test behavior:**
- Given semantic entry:
  - key: `project:bilinc:status`
  - metadata: `product=Bilinc`, `concerns=["agent-memory"]`, `claims=[{holder, subject, claim, kind, provenance_id, confidence, valid_at}]`
- `preview_projection([entry])` returns:
  - `memory_count == 1`
  - candidate node names include memory key, product, concern, claim subject, holder.
  - candidate edges include memory->product, memory->concern, holder->subject claim edge, provenance->claim support edge.
  - every edge has `provenance_id` or `memory_key` metadata.

**RED command:**
`python3 -m pytest tests/test_knowledge_graph.py::TestKGProjectionPreview::test_projection_preview_from_claim_and_metadata -q`

**Expected RED:** ImportError or AttributeError because `bilinc.core.graph_doctor.preview_projection` does not exist.

### Task 1.2: Implement minimal `graph_doctor.preview_projection()`

**Objective:** Provide a pure function returning candidate projection stats and issue hints without mutating the passed entries or any backend.

**Files:**
- Create: `src/bilinc/core/graph_doctor.py`

**API:**
```python
from bilinc.core.models import MemoryEntry

def preview_projection(entries: list[MemoryEntry]) -> dict:
    ...
```

**Return shape:**
```python
{
  "read_only": True,
  "memory_count": 1,
  "candidate_nodes": [
    {"name": "project:bilinc:status", "node_type": "fact", "source": "memory_key"},
    {"name": "Bilinc", "node_type": "entity", "source": "metadata.product"}
  ],
  "candidate_edges": [
    {
      "source": "project:bilinc:status",
      "target": "Bilinc",
      "relation_type": "related_to",
      "metadata": {"memory_key": "project:bilinc:status", "source": "metadata.product"}
    }
  ],
  "issues": [],
  "stats": {
    "candidate_node_count": 2,
    "candidate_edge_count": 1,
    "claim_count": 0,
    "memories_with_projection": 1,
    "memories_without_projection": 0
  }
}
```

**Implementation constraints:**
- Deterministic only: use metadata/key/value parsing, no LLM.
- No imports from MCP server.
- No database writes.
- No external graph DB dependency.
- Deduplicate nodes by normalized name + type + source.
- Deduplicate edges by source + target + relation_type + metadata source.
- Keep unknown/malformed claims as issues, not exceptions.

**GREEN command:**
`python3 -m pytest tests/test_knowledge_graph.py::TestKGProjectionPreview::test_projection_preview_from_claim_and_metadata -q`

### Task 1.3: Add graph doctor issue detection tests

**Objective:** Ensure projection preview surfaces useful “doctor” problems: no projection candidates, malformed claims, duplicate entity aliases, stale temporal windows.

**Files:**
- Modify: `tests/test_knowledge_graph.py`

**Tests:**
1. `test_projection_preview_reports_memories_without_projection`
   - procedural/empty entry produces `memories_without_projection == 1` and issue type `no_projection_candidates`.
2. `test_projection_preview_reports_malformed_claims_without_throwing`
   - metadata claim missing holder/subject/claim becomes issue type `malformed_claim`, no exception.
3. `test_projection_preview_reports_duplicate_alias_candidates`
   - entries with product `Bilinc` and explicit entity alias `bilinc` surface issue type `possible_duplicate_entity`.
4. `test_projection_preview_reports_expired_claim_window`
   - claim with `invalid_at` in the past surfaces issue type `expired_claim` and excludes active claim edge or marks it inactive.

**RED command:**
`python3 -m pytest tests/test_knowledge_graph.py::TestKGProjectionPreview -q`

### Task 1.4: Implement issue detection

**Objective:** Make `preview_projection()` useful enough to run before any live KG backfill.

**Files:**
- Modify: `src/bilinc/core/graph_doctor.py`

**Implementation detail:**
- Use helper functions:
  - `_node(name, node_type, source, metadata=None)`
  - `_edge(source, target, relation_type, memory_key, source_label, metadata=None)`
  - `_coerce_claims(metadata)`
  - `_is_past_timestamp(value, now=None)`
- Return issue entries:
```python
{"type": "malformed_claim", "memory_key": "...", "reason": "missing holder/subject/claim"}
```

**GREEN command:**
`python3 -m pytest tests/test_knowledge_graph.py::TestKGProjectionPreview -q`

### Task 1.5: Wire optional StatePlane helper without MCP exposure

**Objective:** Allow in-process callers to preview backend projection candidates without exposing a new public MCP tool yet.

**Files:**
- Modify: `src/bilinc/core/stateplane.py`
- Test: `tests/test_knowledge_graph.py`

**API:**
```python
async def preview_graph_projection(self, memory_types: Optional[List[MemoryType]] = None, limit: int = 1000) -> Dict[str, Any]:
    """Read-only graph projection preview over backend or working memory entries."""
```

**Behavior:**
- If backend exists: use `_collect_recall_candidates(memory_types=...)`, take up to limit.
- If no backend: use working memory entries.
- Calls `preview_projection(entries)`.
- Adds `read_only=True` and `source="backend" | "working_memory"`.
- Does not call `backend.save`, `save_entity`, `save_claim`, `knowledge_graph.ingest_memory_entry`, or audit log.

**RED/GREEN command:**
`python3 -m pytest tests/test_knowledge_graph.py::TestKGProjectionPreview::test_stateplane_preview_graph_projection_is_read_only -q`

### Task 1.6: Sprint 1 verification

**Commands:**
1. `python3 -m pytest tests/test_knowledge_graph.py -q`
2. `python3 -m pytest tests/test_knowledge_graph.py::TestKGProjectionPreview -q`
3. `python3 -m py_compile src/bilinc/core/graph_doctor.py src/bilinc/core/stateplane.py`
4. `git diff --stat`
5. Secret scan scoped to diff:
   `git diff -- . ':!dist' ':!build' | LC_ALL=C grep -E -i '(api[_-]?key|secret|token|password|bearer[[:space:]]+[A-Za-z0-9._-]{12,}|sk-[A-Za-z0-9]{20,}|pypi-[A-Za-z0-9_-]{20,})' || true`

**Do not commit unless explicitly requested in this sprint.**

---

# Sprint 2 — Recall Explain Envelope

**Sprint Goal:** Make recall results explainable by adding deterministic `why_retrieved`, provenance/freshness/authority metadata, and optional supporting claims when profile includes claims.

### Task 2.1: Add tests for `explain=True` recall output

**Files:**
- Modify: `tests/test_recall_profiles.py` or create `tests/test_recall_explain.py` using core imports.

**API option:**
- Preferred: add optional `explain: bool = False` to `recall_intelligent()` and pass through `recall_reflective()` / `recall_profiled()` only when explicitly requested.
- Backward compatibility: default output unchanged unless `explain=True`, or add `why_retrieved` unconditionally only if tests show no public contract break.

**Expected fields per result:**
- `why_retrieved: list[str]`
- `provenance: {source, memory_type, created_at, updated_at, importance, current_strength, authority, freshness}`
- `risk_flags: list[str]`

### Task 2.2: Implement explanation builder

**Files:**
- Modify: `src/bilinc/core/stateplane.py`

**Helper:**
```python
def _explain_recall_result(self, entry, query, signals, score) -> dict:
    ...
```

**Rules:**
- lexical signal > 0 => "lexical match"
- hybrid signal > 0 => "hybrid/vector match"
- entity signal > 0 => "entity overlap"
- metadata canonical/authority => authority tier
- low strength or old timestamps => risk flags

### Task 2.3: Attach scoped supporting claims for verified/deep profiles

**Files:**
- Modify: `src/bilinc/core/stateplane.py`
- Tests: existing claims/evidence tests or new `tests/test_recall_explain.py`

**Critical safety:** only claims whose `memory_key` is in returned results. No global claim leak.

---

# Sprint 3 — Claim / Provenance Envelope Polish

**Sprint Goal:** Standardize optional claim provenance fields without breaking old claims.

### Task 3.1: Extend claim extraction metadata pass-through

**Files:**
- Modify: `src/bilinc/core/claims.py`
- Tests: `tests/test_claims.py` or new test with core imports if top-level export issue persists.

**Optional fields stored in `Claim.metadata`:**
- `evidence_snippet`
- `source_hash`
- `authority`
- `sensitivity`
- `owner`
- `source_url`
- `source_path`

**Validation:**
- Unknown keys remain accepted under metadata.
- Invalid authority/sensitivity becomes issue or defaults to contextual/internal only if explicitly coded.

### Task 3.2: Recall evidence output includes claim receipt summary

**Behavior:**
- Evidence output groups supporting claims by memory key.
- Each claim includes provenance id and authority tier.

---

# Sprint 4 — Deterministic KG Projection Apply Path (Approval-Gated for Live DB)

**Sprint Goal:** Once doctor preview is stable, add an apply function that can project into an in-memory `KnowledgeGraph` or temp backend. Live DB backfill remains approval-gated.

### Task 4.1: Apply preview into `KnowledgeGraph`

**API:**
```python
def apply_projection_preview(kg: KnowledgeGraph, preview: dict) -> dict:
    ...
```

**Safety:**
- Pure in-memory unless caller passes a graph.
- No backend writes.
- Idempotent by relation dedupe.

### Task 4.2: Optional MCP admin preview tool

Only after Sprint 1/2 pass. MCP tool must be read-only and named clearly, e.g. `workspace_status` pattern:
- `bilinc_graph_projection_preview`
- output includes `admin_debug_only=True`, `read_only=True`

---

## Pre-Mortem / Risk Mitigations

### Tigers Addressed

1. **[TIGER] Evidence leakage through recall explain or claims.**
   - Mitigation: supporting claims must be scoped to returned memory keys only; add regression test.
   - Sprint: 2.

2. **[TIGER] Live DB mutation/backfill during diagnostics.**
   - Mitigation: Sprint 1 is pure function + temp StatePlane only; no live DB path; receipt mutation only via explicit MCP key.
   - Sprint: 1.

3. **[TIGER] Backend/provider architecture creep.**
   - Mitigation: no Neo4j/Kuzu/Graphiti; no new dependencies; pure deterministic projection.
   - Sprint: all.

4. **[TIGER] Existing branch/package baseline instability gets hidden.**
   - Mitigation: record baseline `StatePlane` top-level export failure; avoid pretending full suite is green.
   - Sprint: 1.

5. **[TIGER] LLM extraction creates hallucinated claims.**
   - Mitigation: no LLM extraction. Explicit metadata/value envelopes only.
   - Sprint: all.

### Elephants

1. **[ELEPHANT] Current public/cloud-only package boundary conflicts with local runtime tests importing top-level `StatePlane`.**
   - Decision: do not solve opportunistically unless required. If fixed, do it as a separate compatibility task with explicit tests.

2. **[ELEPHANT] Bilinc has strong primitives but weak visible product UX.**
   - Decision: this plan improves internal agent UX first; public UX later.

### Accepted Risks

1. **Graph doctor may initially over-report candidate nodes.**
   - Accepted because it is read-only and diagnostic; later scoring/filters can tighten it.

2. **Recall explain may slightly increase payload size.**
   - Accepted for personal-use quality; gate behind `explain=True` if needed.

## Operational Loop Per Sprint

1. Bilinc recall/capture: recall current goal and record stage start.
2. RED: write failing test and run exact test.
3. GREEN: minimal implementation.
4. Verify focused tests.
5. Run py_compile and scoped secret scan.
6. Record Bilinc receipt with exact commands/output.
7. Report changed files, verification, caveats.

## Success Criteria for Whole Goal

- Recall results become self-explaining enough that Hermes can calibrate trust without extra inspection.
- Graph doctor reveals why KG projection is sparse before any live backfill.
- Claim/provenance metadata becomes more useful without automatic hallucinated extraction.
- No live memory loss, no backend migration, no provider switch, no public overclaim.
