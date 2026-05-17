# Bilinc LongMemEval Benchmark Results

**Date:** May 17, 2026
**System:** Bilinc v1.2.5
**Mode:** Hybrid retrieval (semantic + keyword re-ranking)
**LLM Used:** None
**Embedding Model:** all-MiniLM-L6-v2 (ChromaDB default)
**Dataset:** LongMemEval-s cleaned, 500 questions

## Results

| Metric | Score |
|--------|-------|
| **R@5** | **98.0%** |
| NDCG@5 | 0.933 |
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

## Competitive Comparison

| System | Reported Score | LLM/API Dependency | Notes |
|--------|-----:|--------------|-------|
| MemPalace hybrid v4 + rerank | 100.0% | Haiku rerank | Highest reported retrieval result; LLM-assisted |
| Supermemory ASMR run 1 | 98.6% | multi-agent LLM ensemble | Experimental/social-experiment run, not production engine |
| MemPalace held-out hybrid | 98.4% | None | Clean no-LLM retrieval number reported by MemPalace |
| **Bilinc v1.2.5 hybrid** | **98.0%** | **None** | Fresh 500-question run; local retrieval, no paid API |
| MemPalace raw | 96.6% | None | Raw no-LLM retrieval baseline |
| OMEGA | 95.4% | GPT-4.1 | LLM-involved task accuracy, not directly retrieval R@5 |
| Mastra Observational Memory | 94.87% | gpt-5-mini | LLM-in-context memory score |
| Zep / Graphiti | 71.2% | GPT-4o | Third-party guide-reported score |

## Key Findings

1. Bilinc reproduces 98.0% R@5 on the full 500-question LongMemEval-s cleaned dataset without an LLM reranker or paid API.
2. The strongest honest public claim is top-tier no-LLM local retrieval, not absolute SOTA across LLM-agent systems.
3. Bilinc beats MemPalace raw by 1.4 points (98.0% vs 96.6%) and trails MemPalace held-out hybrid by 0.4 points (98.0% vs 98.4%).
4. Weakest categories remain preference (93.3%), temporal (96.2%), and assistant (96.4%); likely improvement paths are preference extraction, temporal/date boost, and two-pass retrieval.
5. Bilinc's main differentiation is not just recall: it combines retrieval with AGM belief revision, Z3 verification, snapshot/diff/rollback, claim projection, contradiction probing, and entity/backlink projection.

## Reproduction

```bash
python3 -m venv /tmp/bilinc-benchmark/venv
/tmp/bilinc-benchmark/venv/bin/python -m pip install chromadb
curl -L -k -o /tmp/bilinc-benchmark/longmemeval_s_cleaned.json \
  https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json
/tmp/bilinc-benchmark/venv/bin/python -u benchmarks/longmemeval_bench.py \
  /tmp/bilinc-benchmark/longmemeval_s_cleaned.json --mode hybrid
```

Local verification log from this run:

```text
BILINC LongMemEval: R@5=98.0% NDCG=0.933 n=500
  knowledge-update               100.0% (n=78)
  multi-session                  99.2% (n=133)
  single-session-assistant       96.4% (n=56)
  single-session-preference      93.3% (n=30)
  single-session-user            100.0% (n=70)
  temporal-reasoning             96.2% (n=133)
```

## Public-Safe Claim

Bilinc reaches 98.0% R@5 on LongMemEval-s with no LLM reranker or paid API, placing it in the top no-LLM retrieval tier while adding verification, AGM belief revision, rollback, claims, contradictions, and entity projection that retrieval-only memory systems do not cover.

Do not claim absolute SOTA unless the metric scope is stated.
