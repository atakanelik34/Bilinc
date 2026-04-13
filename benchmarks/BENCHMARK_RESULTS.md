# Bilinc Benchmark Results

## Existing: LongMemEval
- **R@5: 98.0%** (no LLM)
- Per-type: Knowledge Update 100%, Single-Session 100%, Multi-Session 99.2%, Assistant 96.4%, Temporal 96.2%, Preference 93.3%

## New: ConvoMem (v0.1 — framework baseline)
- **Overall: 17.5%** (10 queries, keyword matcher baseline)
- fact_recall: 16.7%
- preference: 0.0%
- temporal: 0.0%
- entity_linking: 50.0%
- multi_hop: 25.0%

**Note:** Baseline uses simple keyword matching. With real Bilinc recall (semantic + KG + AGM), scores expected to be significantly higher. This establishes the benchmark framework, not final performance.

## New: LoCoMo (v0.1 — framework baseline)
- **Overall: 9.1%** (11 queries, keyword matcher baseline)
- temporal_inference: 0.0%
- multi_hop: 0.0%
- causal: 33.3%
- long_range: 0.0%

**Note:** Same as ConvoMem — baseline framework, not final performance.

## Next Steps
1. Integrate real Bilinc recall (StatePlane + KnowledgeGraph + AGM)
2. Run with semantic search (sqlite-vec + nomic-embed-text)
3. Add hybrid decay verification (does decay preserve important facts?)
4. Target: ConvoMem 85%+, LoCoMo 90%+
