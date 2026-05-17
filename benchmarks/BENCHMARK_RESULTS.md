# Bilinc Benchmark Results

## LongMemEval (Existing)
- **R@5: 98.0%** (no LLM)
- Per-type: Knowledge Update 100%, Single-Session 100%, Multi-Session 99.2%, Assistant 96.4%, Temporal 96.2%, Preference 93.3%

## ConvoMem (New)
- **Overall: 98.0%** (10 queries, FTS5 + hybrid recall)
- fact_recall: 100%
- preference: 100%
- temporal: 100%
- entity_linking: 90% (1 miss: `$300k` normalization)
- multi_hop: 100%

## LoCoMo (New)
- **Overall: 90.35%** (11 queries, FTS5 + hybrid recall)
- temporal_inference: 97.92%
- multi_hop: 83.3%
- causal: 100%
- long_range: 75.0%

## Score Progression
```
ConvoMem: 17.5% → 63% → 72% → 76% → 86% → 96% → 98%
LoCoMo:    9.1% → 37% → 58% → 70% → 79% → 85.8% → 90.35%
```

## Recall Architecture
3-level hybrid search:
  Level 1: FTS5 keyword (BM25 + porter stemming + query expansion with 14 synonym groups)
  Level 2: Vector similarity (sqlite-vec + Ollama nomic-embed-text 768-dim)
  Level 3: Knowledge graph (HippoRAG-inspired spreading activation)
  + Decay-aware reranking + temporal boost + importance + access frequency

## Remaining Gaps
- LoCoMo long_range: 75.0% (`lr_001` misses `yes`, `memory`)
- LoCoMo multi_hop: 83.3% (`mh_001` misses `trust`, `rearc`)
- ConvoMem entity_linking: 90.0% (`el_001` misses `$300k`)

## Current Source Artifacts
- `benchmarks/results/convomem_results.json`
- `benchmarks/results/locomo_results.json`
- `benchmarks/results/longmemeval_results.json`
