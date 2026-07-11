# Benchmark Evidence

Each dated evidence directory contains one or more lane manifests. A manifest
must record the source state, dataset provenance, runner, environment, raw
result hashes, metric semantics and limitations. Validate all manifests with:

```bash
python3 -m benchmarks.validate_evidence
```

The current 2026-07-11 manifest explicitly archives legacy results as
unverifiable historical material; it is not a current performance claim.
