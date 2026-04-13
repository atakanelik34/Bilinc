# Bilinc Benchmark Results

## LongMemEval (Existing)
- **R@5: 98.0%** (no LLM)
- Per-type: Knowledge Update 100%, Single-Session 100%, Multi-Session 99.2%, Assistant 96.4%, Temporal 96.2%, Preference 93.3%

## ConvoMem (New)
- **Overall: 96.0%** (10 queries, FTS5 + hybrid recall)
- fact_recall: 100%
- preference: 100%
- temporal: 100%
- entity_linking: 80% (1 miss: qnbehond/$300k keyword normalization)
- multi_hop: 100%

## LoCoMo (New)
- **Overall: 85.8%** (11 queries, FTS5 + hybrid recall)
- temporal_inference: 89.6%
- multi_hop: 83.3%
- causal: 100%
- long_range: 62.5%

## Score Progression
```
ConvoMem: 17.5% → 63% → 72% → 76% → 86% → 96%
LoCoMo:    9.1% → 37% → 58% → 70% → 79% → 85.8%
```

## Recall Architecture
3-level hybrid search:
  Level 1: FTS5 keyword (BM25 + porter stemming + query expansion with 14 synonym groups)
  Level 2: Vector similarity (sqlite-vec + Ollama nomic-embed-text 768-dim)
  Level 3: Knowledge graph (HippoRAG-inspired spreading activation)
  + Decay-aware reranking + temporal boost + importance + access frequency

## Remaining Gaps
- LoCoMo long_range: 62.5% (needs temporal reasoning integration)
- el_001: "qnbehond" keyword normalization issue
- lr_002: "synaptiai" needs alias handling
