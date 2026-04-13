import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

def recall(q, entries):
    ql = q.lower()
    qw = set(ql.split())
    best, bs = "", 0
    for e in entries:
        k, v = e.get("key",""), e.get("value","")
        if isinstance(v, dict): v = json.dumps(v)
        c = f"{k} {v}".lower()
        o = len(qw & set(c.split()))
        if o > bs: bs, best = o, f"{k}: {v}"
    return best or "No relevant information found."

def run_all():
    rd = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(rd, exist_ok=True)
    es = [
        {"key":"founder","value":"Atakan Elik, ex-PepsiCo FP&A analyst, Istanbul solo founder","memory_type":"semantic","importance":0.95,"access_count":20},
        {"key":"rearc_labs","value":"ReARC Labs Inc., Delaware C-Corp via Stripe Atlas","memory_type":"semantic","importance":0.95,"access_count":15},
        {"key":"ares","value":"ARES Protocol: on-chain AI reputation on Base, 11 contracts on Sepolia testnet","memory_type":"semantic","importance":0.9,"access_count":10},
        {"key":"bilinc","value":"Bilinc: verifiable state plane, Z3 verification, AGM belief revision, v1.0.0, 98% LongMemEval, no LLM","memory_type":"semantic","importance":0.95,"access_count":25},
        {"key":"docly","value":"Docly: document AI SaaS, 21+ tools, Paddle billing, x402 protocol, live, revenue","memory_type":"semantic","importance":0.9,"access_count":8},
        {"key":"fintarx","value":"Fintarx: AI CFO Turkish KOBIs, native ERP Logo Mikro ETA, in development","memory_type":"semantic","importance":0.9,"access_count":5},
        {"key":"seed","value":"$1.5M seed, $18M cap, SAFE + Token Warrant, 80M ARES at $0.005","memory_type":"semantic","importance":0.95,"access_count":12},
        {"key":"model_policy","value":"Free OpenRouter preferred, Ollama local inference, avoid paid APIs","memory_type":"semantic","importance":0.85,"access_count":10},
        {"key":"anthropic","value":"Anthropic Claude Partner Network approved, Karl Kadon","memory_type":"episodic","importance":0.9,"access_count":5},
        {"key":"ozge","value":"Ozge Oz, Partner QNBEYOND Ventures, $300K sweet spot, HockeyStack portfolio","memory_type":"semantic","importance":0.9,"access_count":8},
    ]
    from benchmarks.convomem_bench import run_convomem_benchmark
    cm = run_convomem_benchmark(recall, es)
    print(f"ConvoMem: {cm['overall_score']*100:.1f}%")
    for c, s in cm["category_scores"].items():
        print(f"  {c}: {s*100:.1f}%")
    with open(os.path.join(rd, "convomem_results.json"), "w") as f:
        json.dump(cm, f, indent=2)

    from benchmarks.locomo_bench import run_locomo_benchmark
    lm = run_locomo_benchmark(recall, es)
    print(f"\nLoCoMo: {lm['overall_score']*100:.1f}%")
    for c, s in lm["category_scores"].items():
        print(f"  {c}: {s*100:.1f}%")
    with open(os.path.join(rd, "locomo_results.json"), "w") as f:
        json.dump(lm, f, indent=2)

    print(f"\n{'='*50}")
    print(f"BENCHMARK SUMMARY")
    print(f"{'='*50}")
    print(f"ConvoMem: {cm['overall_score']*100:.1f}% ({cm['total_queries']} queries)")
    print(f"LoCoMo:   {lm['overall_score']*100:.1f}% ({lm['total_queries']} queries)")

if __name__ == "__main__":
    run_all()
