"""
ConvoMem Benchmark for Bilinc.

Tests conversational memory recall across 5 categories:
  fact_recall, preference, temporal, entity_linking, multi_hop
"""
import json

CONVOMEM_QUERIES = [
    {"id": "fr_001", "category": "fact_recall",
     "conversation_context": "User worked at PepsiCo as FP&A analyst for 3 years.",
     "question": "Where did the user work and for how long?",
     "expected_keywords": ["pepsico", "fp&a", "3 years"],
     "ground_truth": "PepsiCo, 3 years as FP&A analyst"},
    {"id": "fr_002", "category": "fact_recall",
     "conversation_context": "Startup is ReARC Labs, Delaware C-Corp via Stripe Atlas.",
     "question": "What is the startup name and incorporation?",
     "expected_keywords": ["rearc labs", "delaware", "stripe atlas"],
     "ground_truth": "ReARC Labs, Delaware C-Corp via Stripe Atlas"},
    {"id": "fr_003", "category": "fact_recall",
     "conversation_context": "ARES Protocol has 11 contracts on Base Sepolia testnet.",
     "question": "How many contracts and which network?",
     "expected_keywords": ["11", "base sepolia"],
     "ground_truth": "11 contracts on Base Sepolia testnet"},
    {"id": "pt_001", "category": "preference",
     "conversation_context": "User prefers free tools, avoids paid APIs, uses Ollama.",
     "question": "User preference on paid APIs?",
     "expected_keywords": ["free", "avoid", "paid", "ollama"],
     "ground_truth": "Prefers free tools, avoids paid APIs"},
    {"id": "pt_002", "category": "preference",
     "conversation_context": "User wants FULL AUTONOMY, agent should act without asking.",
     "question": "What autonomy level does user want?",
     "expected_keywords": ["full autonomy", "without asking"],
     "ground_truth": "Full autonomy, no permission needed"},
    {"id": "to_001", "category": "temporal",
     "conversation_context": "Phase 1 completed April 7. Phase 2 had rollback/diff/snapshot.",
     "question": "What order were phases completed?",
     "expected_keywords": ["phase 1", "first", "phase 2", "after"],
     "ground_truth": "Phase 1 first, then Phase 2"},
    {"id": "to_002", "category": "temporal",
     "conversation_context": "Seed round research done, then Anthropic Partner approved.",
     "question": "Which came first?",
     "expected_keywords": ["seed round", "first"],
     "ground_truth": "Seed round research first, then Anthropic Partner"},
    {"id": "el_001", "category": "entity_linking",
     "conversation_context": "Özge Öz is Partner at QNBEYOND, $300K sweet spot, HockeyStack in portfolio.",
     "question": "Who is Özge Öz and her profile?",
     "expected_keywords": ["özge", "qnbehond", "partner", "$300k", "hockeystack"],
     "ground_truth": "Partner at QNBEYOND, $300K, portfolio includes HockeyStack"},
    {"id": "el_002", "category": "entity_linking",
     "conversation_context": "Docly uses Paddle billing, x402 protocol, 21+ tools.",
     "question": "Docly billing and tool count?",
     "expected_keywords": ["paddle", "x402", "21"],
     "ground_truth": "Paddle billing with x402, 21+ tools"},
    {"id": "mh_001", "category": "multi_hop",
     "conversation_context": "4 products. ARES on Base. Seed round for ARES mainnet + Fintarx MVP.",
     "question": "Which products will seed funding support?",
     "expected_keywords": ["ares", "fintarx", "mainnet", "mvp"],
     "ground_truth": "ARES mainnet and Fintarx MVP"},
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