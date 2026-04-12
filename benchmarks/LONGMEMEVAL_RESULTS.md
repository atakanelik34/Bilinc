# Bilinc LongMemEval Benchmark Results

**Date:** April 12, 2026  
**System:** Bilinc v1.0.4  
**Mode:** Hybrid retrieval (semantic + keyword re-ranking)  
**LLM Used:** None  
**Embedding Model:** all-MiniLM-L6-v2 (ChromaDB default)

## Results

| Metric | Score |
|--------|-------|
| **R@5** | **98.0%** |
| NDCG@10 | 0.933 |
| Questions | 500/500 |

## Per-Type Breakdown

| Question Type | R@5 | Count |
|--------------|-----|-------|
| Knowledge Update | 100.0% | 78 |
| Single-Session User | 100.0% | 70 |
| Multi-Session | 99.2% | 133 |
| Single-Session Assistant | 96.4% | 56 |
| Temporal Reasoning | 96.2% | 133 |
| Single-Session Preference | 93.3% | 30 |

## Comparison

| System | R@5 | LLM Required |
|--------|-----|--------------|
| MemPalace (hybrid v4 + rerank) | 100% | Haiku |
| MemPalace (hybrid v3 + rerank) | 99.4% | Haiku |
| MemPalace (hybrid v2) | 98.4% | None |
| **Bilinc (hybrid)** | **98.0%** | **None** |
| MemPalace (raw) | 96.6% | None |
| Mastra | 94.87% | GPT-5-mini |
| Hindsight | 91.4% | Gemini-3 |

## Key Findings

1. **Bilinc beats MemPalace raw by 1.4 points** (98.0% vs 96.6%) without any LLM assistance
2. User-turn-only approach is critical — storing all turns dilutes the semantic signal
3. Keyword re-ranking (30% weight) provides significant boost over pure semantic search
4. Weakest categories: preference (93.3%) and assistant (96.4%) — addressable with preference extraction and two-pass retrieval

## Reproduction

```bash
pip install chromadb

# Download dataset
curl -o longmemeval_s_cleaned.json \
  https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json

# Run benchmark
python benchmarks/longmemeval_bench.py longmemeval_s_cleaned.json --mode hybrid
```

## Next Steps

- [ ] Add LLM reranking (Haiku/Sonnet) → target 99%+
- [ ] Add preference extraction (regex patterns) → fix 93.3% preference score
- [ ] Add two-pass retrieval (user + assistant turns) → fix 96.4% assistant score
- [ ] Add temporal date boosting → fix 96.2% temporal score
- [ ] Add Bilinc knowledge graph layer → unique advantage
