import json, sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

def bilinc_recall_fn(question, entries):
    """Recall with phrase + word + bigram matching."""
    ql = question.lower()
    results = []
    for e in entries:
        k = e.get("key", "")
        v = e.get("value", "")
        if isinstance(v, dict):
            v = json.dumps(v)
        cl = f"{k}: {v}".lower()
        score = 0

        # Phrase matching
        if ql in cl:
            score += 10

        # Word matching with substring fallback
        for qw in ql.split():
            if len(qw) < 2:
                continue
            if qw in cl.split():
                score += 3
            elif qw in cl:
                score += 2

        # Bigram overlap
        qbg = set(ql[i:i+2] for i in range(len(ql)-1))
        cbg = set(cl[i:i+2] for i in range(len(cl)-1))
        score += len(qbg & cbg) * 0.08

        # Importance boost
        imp = e.get("importance", 0.5)
        ac = e.get("access_count", 0)
        score *= (1 + imp * 0.4 + min(ac, 20) * 0.02)

        if score > 0:
            results.append((score, f"{k}: {v}"))

    if not results:
        return "No relevant information found."
    results.sort(key=lambda x: x[0], reverse=True)
    return " | ".join(r[1] for r in results[:2])

def run_all():
    rd = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(rd, exist_ok=True)
    es = [
        {"key": "founder", "value": "Atakan Elik ex PepsiCo FP and A analyst 3 years at PepsiCo as Finance Business Partner Istanbul solo technical founder age 30 M1 MBA", "memory_type": "semantic", "importance": 0.95, "access_count": 20},
        {"key": "rearc_labs", "value": "ReARC Labs Inc Delaware C Corp incorporated via Stripe Atlas contact rearclabs.com founder Atakan Elik mission trust infrastructure for agent economy", "memory_type": "semantic", "importance": 0.95, "access_count": 15},
        {"key": "ares_protocol", "value": "ARES Protocol on chain AI reputation protocol on Base blockchain 11 smart contracts deployed on Base Sepolia testnet 106 Foundry tests passing", "memory_type": "semantic", "importance": 0.9, "access_count": 10},
        {"key": "bilinc", "value": "Bilinc verifiable state plane for autonomous agents Z3 SMT solver formal verification AGM belief revision expand contract revise v1.0.0 98.0 percent LongMemEval R5 without any LLM Knowledge Graph rollback diff snapshot 164 tests passing", "memory_type": "semantic", "importance": 0.95, "access_count": 25},
        {"key": "docly", "value": "Docly document AI SaaS for agents 21 plus document tools Paddle billing with x402 protocol live in production generating revenue docly.work public REST API", "memory_type": "semantic", "importance": 0.9, "access_count": 8},
        {"key": "fintarx", "value": "Fintarx AI CFO for Turkish KOBIs native ERP integration Logo Mikro ETA not Excel upload like competitors FP and A capabilities 600K plus KOBIs in Turkey in development Starter 4990 TL per month", "memory_type": "semantic", "importance": 0.9, "access_count": 5},
        {"key": "seed_round", "value": "Seed round 1.5 million dollars 18M post money cap SAFE plus Token Warrant 80M ARES at 0.005 dollars 6 month cliff 24 month linear vesting 55 percent team 30 percent product 15 percent GTM for ARES mainnet and Fintarx MVP 18 20 month runway 2026 AI seed median 17.9M Anthropic Partner premium", "memory_type": "semantic", "importance": 0.95, "access_count": 12},
        {"key": "model_policy", "value": "Model policy prefer free OpenRouter models use Ollama for local inference with qwen2.5 3b and nomic embed text avoid paid APIs free candidates stepfun step 3.5 flash free z ai glm 4.5 air free qwen qwen3 coder free", "memory_type": "semantic", "importance": 0.85, "access_count": 10},
        {"key": "anthropic_partner", "value": "Anthropic Claude Partner Network approved Karl Kadon contact can use in profile and messages approved April 2026", "memory_type": "episodic", "importance": 0.9, "access_count": 5},
        {"key": "ozge_oz", "value": "Ozge Oz Partner at QNBEYOND Ventures check size 150K to 1M sweet spot 300K pre seed to Series A portfolio HockeyStack Fume Midas ikas Debite FirstBatch meeting April 15 15 00 Zoom co investor Bessemer Venture Partners", "memory_type": "semantic", "importance": 0.9, "access_count": 8},
        {"key": "enis_hulli", "value": "Enis Hulli General Partner at e2vc London Fund III 100M euro thesis Israeli model founders to US 60 portfolio 4 unicorn 3B plus total check up to 1M", "memory_type": "semantic", "importance": 0.85, "access_count": 6},
        {"key": "bilinc_history", "value": "Originally called SynapticAI rebranded to Bilinc with v1.0.0 Phase 1 completed April 7 2026 persistent CLI SQLite schema 19 integration tests Phase 2 5 MCP transports HTTP auth Prometheus metrics 303 entries 14 beliefs 37 KG nodes 33 edges", "memory_type": "episodic", "importance": 0.85, "access_count": 8},
        {"key": "competitors", "value": "Bilinc competitors MemPalace 98.4 percent with LLM 96.6 percent raw Mem0 cloud Zep temporal graphs Letta MemGPT self editing none have Z3 verification or AGM belief revision Docly competitors Parasut no FP and A no ERP Finsmart ai Excel upload English", "memory_type": "semantic", "importance": 0.8, "access_count": 5},
        {"key": "communication", "value": "User preferences Turkish plain text no markdown FULL AUTONOMY mode daytime SSH nighttime Telegram free tools agent reach web search", "memory_type": "procedural", "importance": 0.9, "access_count": 30},
        {"key": "vm_infra", "value": "GCP VM rearc main vm at 34.56.5.182 us central1 c user busecimen project rearc ops runs agent fleet ZEUS HERMES TRITON POSEIDON Bilinc MCP over SSH stdio", "memory_type": "semantic", "importance": 0.8, "access_count": 15},
        {"key": "agent_fleet", "value": "Agent Fleet ATHENA master orchestrator ZEUS weather trading Polymarket HERMES arbitrage 3 strategies TRITON BTC self tuning every 2 hours Claude API POSEIDON whale copy trading ARGOS freelancer agent bootstrap", "memory_type": "semantic", "importance": 0.8, "access_count": 7},
        {"key": "pitch_deck", "value": "Pitch deck PDF 14 slides Gamma 10 slides Turkish key message trust infrastructure for agent economy 4 live products solo founder zero external funding Anthropic Partner", "memory_type": "semantic", "importance": 0.85, "access_count": 4},
    ]

    from benchmarks.convomem_bench import run_convomem_benchmark
    cm = run_convomem_benchmark(bilinc_recall_fn, es)
    print(f"ConvoMem: {cm['overall_score']*100:.1f}%")
    for c, s in cm["category_scores"].items():
        print(f"  {c}: {s*100:.1f}%")
    for r in cm["results"]:
        if r["score"] < 1.0:
            print(f"  FAIL {r['id']}: {r['score']*100:.0f}% missing={r['missing']}")
    with open(os.path.join(rd, "convomem_results.json"), "w") as f:
        json.dump(cm, f, indent=2)

    from benchmarks.locomo_bench import run_locomo_benchmark
    lm = run_locomo_benchmark(bilinc_recall_fn, es)
    print(f"\nLoCoMo: {lm['overall_score']*100:.1f}%")
    for c, s in lm["category_scores"].items():
        print(f"  {c}: {s*100:.1f}%")
    for r in lm["results"]:
        if r["score"] < 1.0:
            print(f"  FAIL {r['id']}: {r['score']*100:.0f}% missing={r['missing']}")
    with open(os.path.join(rd, "locomo_results.json"), "w") as f:
        json.dump(lm, f, indent=2)

    print(f"\n{'='*50}")
    print(f"BENCHMARK SUMMARY")
    print(f"{'='*50}")
    print(f"ConvoMem: {cm['overall_score']*100:.1f}% ({cm['total_queries']} queries)")
    print(f"LoCoMo:   {lm['overall_score']*100:.1f}% ({lm['total_queries']} queries)")

if __name__ == "__main__":
    run_all()
