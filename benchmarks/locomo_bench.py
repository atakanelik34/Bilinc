import re
"""LoCoMo Benchmark for Bilinc - v0.2"""

LOCOMO_QUERIES = [
    {"id": "ti_001", "category": "temporal_inference",
     "question": "How long between starting ReARC Labs and completing Bilinc Phase 1?",
     "expected_keywords": ["1 month", "march", "april", "33"],
     "ground_truth": "About 1 month"},
    {"id": "ti_002", "category": "temporal_inference",
     "question": "What happened between Anthropic Partner approval and vault reorganization?",
     "expected_keywords": ["anthropic", "partner", "april"],
     "ground_truth": "Anthropic Partner approval then vault reorganization"},
    {"id": "ti_003", "category": "temporal_inference",
     "question": "What was the chronological order of ARES contracts, Bilinc release, and seed round?",
     "expected_keywords": ["ares", "bilinc", "seed round"],
     "ground_truth": "ARES contracts → Bilinc v1.0.0 → Seed round research"},
    {"id": "mh_001", "category": "multi_hop",
     "question": "How does the user's finance background connect to current startup strategy?",
     "expected_keywords": ["pepsico", "finance", "trust", "rearc"],
     "ground_truth": "Finance background led to trust infrastructure for agent economy"},
    {"id": "mh_002", "category": "multi_hop",
     "question": "What is the common thread across all ReARC Labs products?",
     "expected_keywords": ["agent", "infrastructure", "trust", "ecosystem"],
     "ground_truth": "Trust infrastructure ecosystem for agent economy"},
    {"id": "mh_003", "category": "multi_hop",
     "question": "How does tool preference affect model selection strategy?",
     "expected_keywords": ["free", "ollama", "openrouter"],
     "ground_truth": "Free preference leads to Ollama and OpenRouter free models"},
    {"id": "cr_001", "category": "causal",
     "question": "Why does Bilinc score high on benchmarks compared to other memory systems?",
     "expected_keywords": ["z3", "verification", "formal", "consistency"],
     "ground_truth": "Z3 formal verification ensures logical consistency"},
    {"id": "cr_002", "category": "causal",
     "question": "Why is the seed round cap set at $18 million?",
     "expected_keywords": ["median", "17.9", "anthropic", "products"],
     "ground_truth": "$17.9M AI seed median plus premium for 4 products and Anthropic partnership"},
    {"id": "cr_003", "category": "causal",
     "question": "Why is Fintarx positioned differently from competitors?",
     "expected_keywords": ["native", "erp", "excel", "turkish"],
     "ground_truth": "Native ERP vs Excel upload, AI FP&A unique in Turkish market"},
    {"id": "lr_001", "category": "long_range",
     "question": "Did the original vision of a memory system that never forgets get achieved?",
     "expected_keywords": ["yes", "98%", "bilinc", "memory"],
     "ground_truth": "Yes, Bilinc achieved 98% LongMemEval"},
    {"id": "lr_002", "category": "long_range",
     "question": "What was the product evolution from SynapticAI to Bilinc?",
     "expected_keywords": ["synaptiai", "bilinc", "rebrand", "v1.0.0"],
     "ground_truth": "SynapticAI → rebranded to Bilinc → v1.0.0"},
]

def evaluate_response(response, query):
    r = re.sub(r"[^a-z0-9\$%.,\s/]", " ", response.lower())
    r = re.sub(r"\s+", " ", r).strip()
    expected = query["expected_keywords"]
    matches = 0
    missing = []
    for kw in expected:
        kw_norm = re.sub(r"[^a-z0-9\$%.,\s/]", " ", kw.lower()).strip()
        if kw_norm in r:
            matches += 1
        else:
            # Partial match: check if all words in kw are in r
            kw_words = kw_norm.split()
            if len(kw_words) > 1 and all(w in r for w in kw_words):
                matches += 0.75  # Partial credit
            else:
                missing.append(kw)
    score = matches / len(expected) if expected else 0.0
    return score, {"id": query["id"], "category": query["category"],
                   "score": round(score, 3), "matched": round(matches, 2),
                   "total": len(expected),
                   "missing": missing}

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
