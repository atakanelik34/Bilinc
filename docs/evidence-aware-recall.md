# Evidence-Aware Recall + Claim Layer

Status: implemented in repository code, with public claims limited to local/repository verification.

This package adds a deterministic evidence layer around Bilinc recall without requiring an LLM provider:

- opt-in recall capture and replay metrics
- explicit attributed claim projection from structured memory metadata/value envelopes
- read-only contradiction probing over active claims
- recall profiles: `fast`, `balanced`, `verified`, `deep`
- conservative entity/backlink projection for entity-centered recall

## Safety posture

The layer is projection-first. Source memories remain the canonical state. Claims and entity mentions are derived indexes that can be rebuilt, deactivated, or deleted when the source memory changes.

No freeform LLM extraction is used for claims. Entity extraction prefers explicit metadata and relations; the fallback proper-noun heuristic is conservative and bounded.

Verified/deep recall evidence is scoped to returned memory keys only. Same-subject claims from unrecalled memories must not appear in public-facing evidence bundles.

## Reproduction commands

Run the focused feature suite:

```bash
python3 -m pytest \
  tests/test_eval_capture.py \
  tests/test_eval_replay.py \
  tests/test_claims.py \
  tests/test_eval_contradictions.py \
  tests/test_recall_profiles.py \
  tests/test_entities.py \
  -q
```

Run the broader memory-layer suite:

```bash
python3 -m pytest \
  tests/test_eval_capture.py \
  tests/test_eval_replay.py \
  tests/test_claims.py \
  tests/test_eval_contradictions.py \
  tests/test_recall_profiles.py \
  tests/test_entities.py \
  tests/test_knowledge_graph.py \
  tests/test_core.py \
  tests/test_sqlite_integration.py \
  tests/test_mcp_server_v2.py \
  -q
```

Run packaging smoke:

```bash
python3 -m build
```

Optional benchmark command if the LongMemEval fixture is available locally:

```bash
python3 benchmarks/longmemeval_bench.py longmemeval_s_cleaned.json --mode hybrid
```

If `longmemeval_s_cleaned.json` is absent, do not report a fresh LongMemEval score from this sprint. Record the dataset absence as a benchmark caveat instead of inventing a number.

## Public-safe wording

Safe:

> Bilinc now has an evidence-aware recall layer: structured claim projection, read-only contradiction probes, recall profiles, replayable recall evals, and conservative entity/backlink projection. It is deterministic and local-first; benchmark claims are tied to repository commands and artifacts.

Avoid:

- “Bilinc proves truth automatically.”
- “Verified recall means the answer is correct.”
- Hosted-service performance claims unless backed by a current hosted run.
- Private ReARC memory examples or live `/Users/.../bilinc.db` content.

## Operator notes

Use `fast` for latency-sensitive recall, `balanced` for normal agent context, `verified` when evidence metadata matters, and `deep` when recall quality is more important than cost/latency.

For public demos, use synthetic or repository fixture data only. Do not demo against private operator memory stores.
