# Bilinc LongMemEval Competitive Benchmark

Date: 2026-05-17  
System: Bilinc v1.2.5  
Benchmark: LongMemEval-s cleaned, 500 questions  
Mode: hybrid retrieval, no LLM reranker, no paid API, local ChromaDB default all-MiniLM-L6-v2 embedding model  
Command:

```bash
/tmp/bilinc-benchmark/venv/bin/python -u benchmarks/longmemeval_bench.py \
  /tmp/bilinc-benchmark/longmemeval_s_cleaned.json --mode hybrid
```

## Result

| Metric | Score |
| --- | ---: |
| R@5 | 98.0% |
| NDCG@5 | 0.933 |
| Questions | 500 / 500 |

## Category breakdown

| LongMemEval category | R@5 | n |
| --- | ---: | ---: |
| knowledge-update | 100.0% | 78 |
| single-session-user | 100.0% | 70 |
| multi-session | 99.2% | 133 |
| single-session-assistant | 96.4% | 56 |
| temporal-reasoning | 96.2% | 133 |
| single-session-preference | 93.3% | 30 |

## Competitive comparison

These rows are not all the same metric. Bilinc and MemPalace raw/hybrid are retrieval R@5-style comparisons. Mastra, OMEGA, Zep/Graphiti and Supermemory use LLM-involved answer/evaluation flows or self-reported task accuracy. Keep the public claim precise: Bilinc is a top no-LLM/local retrieval result, not an absolute SOTA claim against LLM-agent benchmark systems.

| System | Reported score | LLM/API dependency | Best fair reading |
| --- | ---: | --- | --- |
| MemPalace hybrid v4 + rerank | 100.0% | Haiku rerank | Highest reported LongMemEval retrieval result, but LLM-assisted and benchmark-specific caveats apply. |
| Supermemory ASMR run 1 | 98.6% | multi-agent LLM ensemble | Experimental/social-experiment run, explicitly not production Supermemory. |
| MemPalace held-out hybrid | 98.4% | none | Slightly above Bilinc on held-out no-LLM retrieval. |
| Bilinc v1.2.5 hybrid | 98.0% | none | Strong no-LLM local retrieval result plus Bilinc's separate verification/state-plane features. |
| MemPalace raw | 96.6% | none | Lower no-LLM raw ChromaDB-style retrieval baseline. |
| OMEGA | 95.4% | GPT-4.1 | LLM-involved task accuracy; not directly retrieval R@5. |
| Mastra Observational Memory | 94.87% | gpt-5-mini | LLM-in-context memory score; not directly retrieval R@5. |
| Zep / Graphiti | 71.2% | GPT-4o | Third-party guide-reported LongMemEval score. |
| RetainDB | 79.0% | unspecified from public snippet | Public benchmark page claim, included as market context only. |

## Positioning

Best public-safe headline:

> Bilinc reaches 98.0% R@5 on LongMemEval-s with no LLM reranker or paid API, placing it in the top no-LLM retrieval tier while adding verification, AGM belief revision, rollback, claims, contradictions, and entity projection that retrieval-only memory systems do not cover.

Do not say:

- "Bilinc is SOTA" without metric scope.
- "Bilinc beats all memory systems" because LLM-assisted systems report higher or different scores.
- "Freshly reproduced" unless this result file and command output are present.

## Sources checked

- LongMemEval paper / project: https://arxiv.org/abs/2410.10813 and https://github.com/xiaowu0162/LongMemEval
- MemPalace benchmark page: https://mempalace.net/benchmarks
- MemPalace GitHub search result summary for raw 96.6% and held-out hybrid 98.4%: https://github.com/mempalace/mempalace
- Vectorize MemPalace analysis: https://vectorize.io/articles/mempalace-benchmarks
- Supermemory ASMR post: https://supermemory.ai/blog/we-broke-the-frontier-in-agent-memory-introducing-99-sota-memory-system/
- Mastra Observational Memory research: https://mastra.ai/research/observational-memory
- OMEGA benchmark/guide pages: https://omegamax.co/benchmarks and https://omegamax.co/guides/ai-agent-memory-benchmarks
- Zep benchmark materials: https://raw.githubusercontent.com/getzep/zep/main/benchmarks/longmemeval/README.md and https://blog.getzep.com/state-of-the-art-agent-memory/

## Local verification artifacts

- Full run log: `/tmp/bilinc-benchmark/longmemeval-2026-05-17.log`
- Dataset used locally: `/tmp/bilinc-benchmark/longmemeval_s_cleaned.json`
- Temporary venv used for benchmark-only ChromaDB dependency: `/tmp/bilinc-benchmark/venv`
