# Bilinc Recall Explain Envelope Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to review this plan/task, but implement in this controller only when faster and still TDD-compliant.

**Goal:** Add an optional read-only explain envelope to Bilinc recall results so personal-use agents can see why a memory was retrieved, where it came from, and what caution flags apply.

**Architecture:** Preserve existing ranking and default output. Add `explain=False` parameters to `recall_intelligent`, `recall_reflective`, and `recall_profiled`; when enabled, each result gets `why_retrieved`, `provenance`, `risk_flags`, and `supporting_claims`. Add `explain` to the MCP `bilinc_recall_smart` schema/handler.

**Tech Stack:** Python, pytest, SQLiteBackend, existing deterministic claim/entity projection utilities.

---

## Acceptance Criteria

1. Default recall behavior and ranking remain unchanged when `explain` is omitted/false.
2. `recall_intelligent(..., explain=True)` adds per-result:
   - `why_retrieved`: human-readable signal reasons from lexical/hybrid/entity/importance/canonical.
   - `provenance`: source, session_id, memory_type, timestamps, validity, verification, source_hash if present.
   - `risk_flags`: at least `low_strength`, `unverified`, `stale_possible`, `expired`, `sensitive_metadata` where applicable.
   - `supporting_claims`: active claims for the memory key, redacted to claim/provenance-safe fields.
3. `recall_reflective(..., explain=True)` and `recall_profiled(..., explain=True)` propagate the explain flag without changing reflection/ranking.
4. MCP `bilinc_recall_smart` accepts optional `explain` boolean and forwards it.
5. No live DB mutation, no schema migration, no backend/provider change.
6. TDD RED/GREEN verified.

## Tasks

### Task 1: RED tests

Create `tests/test_recall_explain.py` with focused tests:

- default `recall_intelligent` has no explain envelope
- explain mode includes why/provenance/risk/supporting claims
- reflective/profiled/MCP propagation includes explain envelope
- secret/sensitive metadata is not copied wholesale into provenance/supporting claims

Expected first run: fail because `explain` argument does not exist.

### Task 2: GREEN implementation

Modify only:

- `src/bilinc/core/stateplane.py`
- `src/bilinc/mcp_server/server_v2.py`
- `tests/test_recall_explain.py`

Implementation notes:

- Add helper `_explain_recall_result(query, entry, score, signals, supporting_claims)`.
- Add helper `_active_claims_by_memory_key(memory_keys)` using `backend.list_claims(active=True, limit=1000)` when available.
- Add helper `_safe_claim_dict(claim)` that avoids arbitrary claim metadata.
- Add helper `_risk_flags_for_entry(entry)`.
- Do not include raw `entry.metadata` in the explain envelope.

### Task 3: Verification

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_recall_explain.py -q
PYTHONPATH=src python3 -m pytest tests/test_recall_explain.py tests/test_knowledge_graph.py -q
python3 -m py_compile src/bilinc/core/stateplane.py src/bilinc/mcp_server/server_v2.py
python3 -m ruff check src/bilinc/core/stateplane.py src/bilinc/mcp_server/server_v2.py tests/test_recall_explain.py
```

Adversarial probe:

- memory has `metadata={"private": "token-123", "sensitivity": "secret"}`
- explain output must include `sensitive_metadata` risk flag
- explain output must not include `token-123`

## Risk Mitigations

### Tigers Addressed

1. **Leaking metadata/secrets through provenance**
   - Mitigation: only allowlisted provenance fields; no raw metadata copy.

2. **Changing ranking behavior accidentally**
   - Mitigation: explain is computed after ranking and does not feed fused scores.

3. **MCP schema drift**
   - Mitigation: add explicit `explain` boolean and test handler path.

### Accepted Risks

1. **Claim support is memory-key scoped only** — acceptable for Sprint 2; entity-neighborhood claim support can be Sprint 3.
