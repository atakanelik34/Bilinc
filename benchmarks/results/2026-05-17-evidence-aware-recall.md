# Evidence-Aware Recall Sprint Result — 2026-05-17

Concern classification: agent-memory + security-critical.

This file records repository-local evidence for the Evidence-Aware Recall + Claim Layer sprint package. It is not a hosted-service benchmark claim.

## Implemented package

- Sprint 1: opt-in retrieval capture and replay metrics
- Sprint 2: structured attributed claim projection
- Sprint 3: read-only contradiction probe
- Sprint 4: recall profiles (`fast`, `balanced`, `verified`, `deep`)
- Sprint 5: conservative entity/backlink projection
- Sprint 6: public-safe evidence and positioning docs

## Verification commands

Focused feature suite:

```bash
python3 -m pytest tests/test_eval_capture.py tests/test_eval_replay.py tests/test_claims.py tests/test_eval_contradictions.py tests/test_recall_profiles.py tests/test_entities.py -q
```

Broader memory-layer suite:

```bash
python3 -m pytest tests/test_eval_capture.py tests/test_eval_replay.py tests/test_claims.py tests/test_eval_contradictions.py tests/test_recall_profiles.py tests/test_entities.py tests/test_knowledge_graph.py tests/test_core.py tests/test_sqlite_integration.py tests/test_mcp_server_v2.py -q
```

Full suite:

```bash
python3 -m pytest -q
```

Packaging smoke:

```bash
python3 -m build
```

## Benchmark caveat

The Sprint 6 plan references:

```bash
python3 benchmarks/longmemeval_bench.py longmemeval_s_cleaned.json --mode hybrid
```

At sprint execution time, `longmemeval_s_cleaned.json` was not present in the repository checkout. No fresh LongMemEval score is claimed from Sprint 6 unless that fixture is restored and the command output is captured.

## Public-safe claim

Bilinc now includes an evidence-aware recall layer with deterministic claim projection, read-only contradiction probes, named recall profiles, replayable recall evals, and conservative entity/backlink projection. Claims should be tied to repository commands and artifacts, not private ReARC memory or hosted-service assumptions.
