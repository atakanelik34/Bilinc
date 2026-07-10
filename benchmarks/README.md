# Benchmark Evidence Contract

Benchmark outputs are not product claims by default. Each committed result must
declare its lane, clean source SHA, dataset source/license/hash, exact command and
metric definitions.

## Lanes

- `product-core`: the supported StatePlane or public product path without
  benchmark-specific behavior.
- `component`: an isolated retrieval/index component.
- `calibrated`: benchmark-specific tuning, aliases, caches or supervision.
- `historical`: superseded methodology or past result.
- `invalid`: mathematically or methodologically invalid output retained only for
  audit context.

`Hit@K` means at least one relevant item appeared in the top K. `Recall@K` means
the fraction of relevant evidence retrieved by K. `NDCG@K` must be normalized and
always fall in the inclusive range `[0, 1]`.

Local scratch outputs belong in `benchmarks/runs/` and must not be committed.

## Evidence status

The files under `benchmarks/results/` predate this contract. Their archived
classification and checksums live in `benchmarks/evidence/2026-07-11/historical/`.
They are retained for audit only and cannot support a current product claim. Run
`python3 -m benchmarks.validate_evidence` to verify committed manifests.
