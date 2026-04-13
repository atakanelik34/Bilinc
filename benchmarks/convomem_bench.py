"""ConvoMem Benchmark for Bilinc - v0.2"""
import json

CONVOMEM_QUERIES = [
    {"id": "fr_001", "category": "fact_recall",
     "question": "Where did the user work and for how long?",
     "expected_keywords": ["pepsico", "fp&a", "3 years"],
     "ground_truth": "PepsiCo, 3 years as FP&A analyst"},
    {"id": "fr_002", "category": "fact_recall",
     "question": "What is the startup name and how was it incorporated?",
     "expected_keywords": ["rearc labs", "delaware", "stripe atlas"],
     "ground_truth": "ReARC Labs, Delaware C-Corp via Stripe Atlas"},
    {"id": "fr_003", "category": "fact_recall",
     "question": "How many contracts are deployed and on which network?",
     "expected_keywords": ["11", "base sepolia"],
     "ground_truth": "11 contracts on Base Sepolia testnet"},
    {"id": "pt_001", "category": "preference",
     "question": "What is the user's preference regarding paid APIs?",
     "expected_keywords": ["free", "ollama", "avoid"],
     "ground_truth": "Prefers free tools, avoids paid APIs, uses Ollama locally"},
    {"id": "pt_002", "category": "preference",
     "question": "What level of autonomy does the user want?",
     "expected_keywords": ["full autonomy"],
     "ground_truth": "Full autonomy, agent should act without asking permission"},
    {"id": "to_001", "category": "temporal",
     "question": "In what order were the phases of Bilinc completed?",
     "expected_keywords": ["phase 1", "phase 2", "april"],
     "ground_truth": "Phase 1 first (April 7), then Phase 2"},
    {"id": "to_002", "category": "temporal",
     "question": "Which came first: Anthropic Partner approval or seed round research?",
     "expected_keywords": ["seed round", "anthropic"],
     "ground_truth": "Seed round research, then Anthropic Partner approval"},
    {"id": "el_001", "category": "entity_linking",
     "question": "Who is Ozge Oz and what is her investment profile?",
     "expected_keywords": ["ozge", "qnbehond", "partner", "$300k", "hockeystack"],
     "ground_truth": "Ozge Oz, Partner at QNBEYOND Ventures, $300K sweet spot"},
    {"id": "el_002", "category": "entity_linking",
     "question": "What billing system does Docly use and how many tools?",
     "expected_keywords": ["paddle", "x402", "21"],
     "ground_truth": "Paddle billing with x402 protocol, 21+ document tools"},
    {"id": "mh_001", "category": "multi_hop",
     "question": "Which products will the seed funding support?",
     "expected_keywords": ["ares", "fintarx", "mainnet", "mvp"],
     "ground_truth": "ARES mainnet and Fintarx MVP development"},
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

def run_convomem_benchmark(recall_fn, entries):
    results = []
    cat_scores = {}
    for q in CONVOMEM_QUERIES:
        resp = recall_fn(q["question"], entries)
        score, details = evaluate_response(resp, q)
        results.append(details)
        cat = q["category"]
        cat_scores.setdefault(cat, []).append(score)
    overall = sum(r["score"] for r in results) / len(results) if results else 0.0
    return {"benchmark": "ConvoMem", "overall_score": round(overall, 4),
            "category_scores": {c: round(sum(s)/len(s), 4) for c, s in cat_scores.items()},
            "total_queries": len(CONVOMEM_QUERIES), "results": results}
