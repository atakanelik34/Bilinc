"""
LoCoMo Benchmark for Bilinc.

Long-term conversational memory with temporal inference,
multi-hop reasoning, causal reasoning, long-range recall.
"""

LOCOMO_QUERIES = [
    {"id":"ti_001","category":"temporal_inference",
     "context":"March 5: Started ReARC Labs. April 7: Bilinc Phase 1 completed.",
     "question":"How long between starting ReARC Labs and Bilinc Phase 1?",
     "expected_keywords":["1 month","march","april"],"ground_truth":"About 1 month"},
    {"id":"ti_002","category":"temporal_inference",
     "context":"April 10: Anthropic Partner approved. April 13: Vault reorganization done.",
     "question":"What happened between April 10 and April 13?",
     "expected_keywords":["anthropic","partner","vault","reorganization"],"ground_truth":"Partner approval then vault reorganization"},
    {"id":"ti_003","category":"temporal_inference",
     "context":"ARES contracts before Bilinc v1.0.0. Bilinc before seed round.",
     "question":"Chronological order of events?",
     "expected_keywords":["ares","first","bilinc","seed round","last"],"ground_truth":"ARES→Bilinc→Seed round"},
    {"id":"mh_001","category":"multi_hop",
     "context":"User at PepsiCo finance. Started ReARC Labs. ARES on Base. Seed for mainnet.",
     "question":"How does finance background connect to startup strategy?",
     "expected_keywords":["finance","pepsico","rearc","trust","ares"],"ground_truth":"Finance led to trust infrastructure"},
    {"id":"mh_002","category":"multi_hop",
     "context":"Bilinc=memory, ARES=reputation, Docly=documents, Fintarx=ERP. All under ReARC Labs.",
     "question":"What is the common thread across all products?",
     "expected_keywords":["agent","infrastructure","trust","ecosystem"],"ground_truth":"Trust infrastructure for agent economy"},
    {"id":"mh_003","category":"multi_hop",
     "context":"User prefers free tools. Uses Ollama. Model policy: free OpenRouter.",
     "question":"How does tool preference affect model selection?",
     "expected_keywords":["free","ollama","openrouter","avoid","paid"],"ground_truth":"Free preference→Ollama+OpenRouter free models"},
    {"id":"cr_001","category":"causal",
     "context":"Bilinc has Z3 verification. Others don\'t. Bilinc scores 98% LongMemEval no LLM.",
     "question":"Why does Bilinc score high?",
     "expected_keywords":["z3","verification","formal","consistency"],"ground_truth":"Z3 formal verification ensures consistency"},
    {"id":"cr_002","category":"causal",
     "context":"Seed $1.5M/$18M cap. AI median $17.9M. 4 products + Anthropic Partner.",
     "question":"Why $18M cap?",
     "expected_keywords":["median","4 products","anthropic","premium"],"ground_truth":"$17.9M median + premium for products/partnership"},
    {"id":"cr_003","category":"causal",
     "context":"Fintarx native ERP. Competitors Excel upload. No AI FP&A in Turkey.",
     "question":"Why is Fintarx different?",
     "expected_keywords":["native","erp","excel","unique"],"ground_truth":"Native ERP vs Excel, plus AI FP&A unique in Turkey"},
    {"id":"lr_001","category":"long_range",
     "context":"30 days ago: wanted memory system that never forgets. Today: Bilinc 98% LongMemEval.",
     "question":"Did the vision get achieved?",
     "expected_keywords":["yes","98%","memory","bilinc"],"ground_truth":"Yes, 98% LongMemEval"},
    {"id":"lr_002","category":"long_range",
     "context":"Week 1: SynapticAI. Week 4: rebranded to Bilinc. Week 8: v1.0.0.",
     "question":"Product evolution timeline?",
     "expected_keywords":["synaptiai","bilinc","rebrand","v1.0.0"],"ground_truth":"SynapticAI→Bilinc rebrand→v1.0.0"},
]

def evaluate_response(response, query):
    r = response.lower()
    expected = query["expected_keywords"]
    matches = sum(1 for kw in expected if kw.lower() in r)
    score = matches / len(expected) if expected else 0.0
    return score, {"id": query["id"], "category": query["category"],
                   "score": round(score, 3), "matched": matches,
                   "total": len(expected),
                   "missing": [kw for kw in expected if kw.lower() not in r]}

def run_locomo_benchmark(recall_fn, entries):
    results = []
    cat_scores = {}
    for q in LOCOMO_QUERIES:
        resp = recall_fn(q["question"], entries)
        score, details = evaluate_response(resp, q)
        results.append(details)
        cat = q["category"]
        cat_scores.setdefault(cat, []).append(score)
    overall = sum(r["score"] for r in results) / len(results) if results else 0.0
    return {"benchmark": "LoCoMo", "overall_score": round(overall, 4),
            "category_scores": {c: round(sum(s)/len(s), 4) for c, s in cat_scores.items()},
            "total_queries": len(LOCOMO_QUERIES), "results": results}