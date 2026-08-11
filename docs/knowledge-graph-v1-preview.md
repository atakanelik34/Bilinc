# Bilinc KG v1: Preview-First Product Boundary

Status: `PRODUCT_READY_FOR_PREVIEW`

KG v1 is Bilinc-native and remains on the existing SQLite/StatePlane read path.
It does not add a graph database, change a backend/provider, use LLM entity
extraction, mutate the live database, or claim a public benchmark result.

## Decision

“Önce graph backfill değil, kanıt üreten read-only projection doctor; sonra ölçüm; en son onaylı apply.”

## Read-only APIs

Pure entry preview:

```python
from bilinc.core.graph_doctor import preview_projection

report = preview_projection(entries, now=evaluation_now)
```

StatePlane preview:

```python
report = await plane.preview_graph_projection(
    memory_types=[MemoryType.SEMANTIC],
    limit=1000,
)
```

The returned report is JSON-safe and can be serialized with
`json.dumps(report, sort_keys=True)`. `include_stale=True` is an audit-only
doctor view; it does not authorize apply or backfill.

## Report contract

- `candidate_nodes` and `candidate_edges`: deterministic, sorted candidates.
- Every node and edge metadata object carries `memory_key` and/or
  `provenance_id`.
- `checks.duplicate`: case/whitespace alias collisions.
- `checks.stale`: stale, future, superseded, inactive, and expired findings.
- `checks.secret_like`: suppressed credential-like values; raw values never
  appear in the report.
- `checks.provenance`: explicit provenance and memory-key fallback counts.
- `checks.determinism`: read-only, idempotent, repeatable contract markers.
- `stats`: input, filtered, candidate, claim, secret-suppression, and
  provenance counters.
- `apply_allowed` and `backfill_allowed` are always `false` in this phase.

Projection inputs are limited to explicit claims, memory key metadata,
subject/entity metadata, temporal windows, source/provenance references,
authority, sensitivity, supersession, and contradiction fields. Free-form
semantic values use only the existing deterministic capitalized-token heuristic;
there is no LLM extraction.

## Recall explain envelope

`recall_intelligent(..., explain=True)` now exposes:

- `graph_effect`: bounded entity/projection overlap and RRF contribution.
- `evidence`: supporting active-claim count, provenance-reference presence,
  verification, authority presence, and temporal-validity presence.

The default recall response is unchanged unless `explain=True` is requested.

## Apply gate

No apply/backfill path is included in KG v1 preview. A future apply requires a
separate owner-approved change with a snapshot, rollback procedure, and fresh
doctor/test evidence. This work is not a Cloud growth or Enterprise
`SELLABLE_RC` release blocker.

The stale Cloudflare cache-blocker working-memory record is intentionally not
used as KG evidence and is a separate memory-curation task.
