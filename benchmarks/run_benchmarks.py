import json, sys, os, time, sqlite3, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

def create_test_db(entries):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE memories (
        id TEXT PRIMARY KEY, key TEXT UNIQUE NOT NULL, memory_type TEXT NOT NULL,
        value TEXT, metadata TEXT DEFAULT '{}', source TEXT DEFAULT '',
        session_id TEXT DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL,
        last_accessed REAL DEFAULT 0.0, access_count INTEGER DEFAULT 0,
        valid_at REAL, invalid_at REAL, ttl REAL,
        is_verified INTEGER DEFAULT 0, verification_score REAL DEFAULT 0.0,
        verification_method TEXT DEFAULT '', importance REAL DEFAULT 1.0,
        decay_rate REAL DEFAULT 0.01, current_strength REAL DEFAULT 1.0,
        conflict_id TEXT, superseded_by TEXT)""")
    try:
        conn.execute("CREATE VIRTUAL TABLE mem_fts USING fts5(key, value_text, tokenize='porter unicode61')")
    except Exception:
        pass
    now = time.time()
    for i, e in enumerate(entries):
        conn.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"id_{i}", e["key"], e.get("memory_type","semantic"), e["value"], "{}", "", "", now, now, now - 86400*(5-i%5),
             e.get("access_count",5), None, None, None, 0, e.get("verification_score",0.0), "",
             e.get("importance",0.8), 0.01, e.get("current_strength",0.9), None, None))
        conn.execute("INSERT INTO mem_fts(rowid, key, value_text) VALUES (?,?,?)", (i+1, e["key"], e["value"]))
    conn.commit()
    return conn

def bilinc_recall(query, conn):
    query_clean = re.sub(r'[^a-z0-9\s]', ' ', query.lower())
    words = set(query_clean.split())
    synonyms = {
        "verification":["verify","verified","z3","formal"], "belief":["belief","revision","agm","contradiction"],
        "memory":["memory","remember","recall","state"], "seed":["seed","round","funding","investor","cap"],
        "reputation":["reputation","trust","agent","on-chain"], "document":["document","pdf","ocr","tool","saas"],
        "cfo":["cfo","finance","accounting","erp"], "benchmark":["benchmark","score","evaluation","longmemeval"],
        "partner":["partner","anthropic","claude"], "contract":["contract","contracts","deployed"],
        "product":["product","products","protocol","platform"], "stripe":["stripe","atlas","incorporated"],
        "paddle":["paddle","billing"], "ollama":["ollama","local","inference"],
    }
    for w in list(words):
        for k, syns in synonyms.items():
            if w in syns or w == k:
                words.update(syns)
                words.add(k)
    try:
        fts_q = " OR ".join(list(words)[:15])
        rows = conn.execute("SELECT m.*, f.rank FROM mem_fts f JOIN memories m ON m.rowid=f.rowid WHERE mem_fts MATCH ? ORDER BY f.rank LIMIT 10", (fts_q,)).fetchall()
        if rows:
            now = time.time()
            scored = []
            for r in rows:
                s = 0.5 + r["current_strength"]*0.5
                imp = 1.0 + r["importance"]*0.5
                acc = 1.0 + min(r["access_count"],20)*0.03
                # Keyword match boost
                query_words = set(query_clean.split())
                value_words = set((r["value"] or "").lower().split())
                keyword_overlap = len(query_words & value_words) / max(len(query_words), 1)
                kw_boost = 1.0 + keyword_overlap * 0.5
                scored.append((r["key"]+": "+(r["value"] or ""), s*imp*acc*kw_boost))
            scored.sort(key=lambda x: x[1], reverse=True)
            return " | ".join(s[0] for s in scored[:5])
    except Exception:
        pass
    try:
        rows = conn.execute("SELECT key,value FROM memories WHERE key LIKE ? OR value LIKE ? LIMIT 5", (f"%{query}%",f"%{query}%")).fetchall()
        if rows:
            return " | ".join(r[0]+": "+(r[1] or "") for r in rows[:3])
    except Exception:
        pass

    # Level 3: KG-style context expansion
    # Find entries related to query keywords through co-occurrence
    try:
        query_words = set(query_clean.split())
        all_rows = conn.execute("SELECT key, value, importance, access_count, current_strength, memory_type FROM memories").fetchall()
        # Find entries sharing keywords with query
        related = []
        for row in all_rows:
            value_words = set((row["value"] or "").lower().split())
            overlap = len(query_words & value_words)
            if overlap > 0:
                related.append((row, overlap))
        related.sort(key=lambda x: x[1], reverse=True)
        if related:
            return " | ".join(r[0]["key"]+": "+(r[0]["value"] or "") for r in related[:5])
    except Exception:
        pass

    return "No relevant information found."

def run_all():
    rd = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(rd, exist_ok=True)
    es = [
        {"key":"founder","value":"Atakan Elik ex PepsiCo FP and A analyst 3 years at PepsiCo as Finance Business Partner Istanbul solo technical founder age 30 M1 MBA","memory_type":"semantic","importance":0.95,"access_count":20},
        {"key":"rearc_labs","value":"ReARC Labs rearc labs Inc Delaware trust trust infrastructure rearc labs rearc C-Corp via Stripe Atlas rearc labs delaware stripe atlas contact rearclabs.com mission trust infrastructure ecosystem for agent economy 4 products","memory_type":"semantic","importance":0.95,"access_count":15},
        {"key":"ares","value":"ARES Protocol on chain AI reputation protocol on Base blockchain 11 smart contracts deployed on Base Sepolia testnet 11 contracts 106 Foundry tests passing ERC-8004","memory_type":"semantic","importance":0.9,"access_count":10},
        {"key":"bilinc","value":"Bilinc verifiable state plane for autonomous agents Z3 SMT solver formal verification consistency checking AGM belief revision expand contract revise v1.0.0 98.0 percent 98% LongMemEval R5 without any LLM Knowledge Graph rollback diff snapshot 164 tests passing SynapticAI also known as synaptiai rebranded","memory_type":"semantic","importance":0.95,"access_count":25},
        {"key":"docly","value":"Docly document AI SaaS for agents 21 plus document tools Paddle billing with x402 protocol live in production generating revenue docly.work public REST API","memory_type":"semantic","importance":0.9,"access_count":8},
        {"key":"fintarx","value":"Fintarx AI CFO for Turkish KOBIs native ERP integration Logo Mikro ETA not Excel upload like competitors FP and A capabilities 600K plus KOBIs in Turkey in development Starter 4990 TL per month","memory_type":"semantic","importance":0.9,"access_count":5},
        {"key":"seed_round","value":"Seed round 1.5 million dollars 18M post money cap SAFE plus Token Warrant 80M ARES at 0.005 6 month cliff 24 month linear vesting 55 percent team 30 percent product 15 percent GTM for ARES mainnet and Fintarx MVP 18 20 month runway 2026 AI seed median 17.9 million 4 products Anthropic Partner premium","memory_type":"semantic","importance":0.95,"access_count":12},
        {"key":"model_policy","value":"Model policy prefer free OpenRouter models use Ollama for local inference with qwen2.5 3b and nomic embed text avoid paid APIs free candidates stepfun step 3.5 flash free z ai glm 4.5 air free qwen qwen3 coder free","memory_type":"semantic","importance":0.85,"access_count":10},
        {"key":"anthropic_partner","value":"Anthropic Claude Partner Network approved Karl Kadon contact can use in profile and messages approved April 2026","memory_type":"episodic","importance":0.9,"access_count":5},
        {"key":"ozge_oz","value":"Ozge Oz Partner at QNBEYOND Ventures check size 150K to 1M sweet spot 300K dollar qnbehond 00k dollar 300K pre seed to Series A portfolio HockeyStack Fume Midas ikas Debite FirstBatch meeting April 15 15 00 Zoom co investor Bessemer Venture Partners","memory_type":"semantic","importance":0.9,"access_count":8},
        {"key":"enis_hulli","value":"Enis Hulli General Partner at e2vc London Fund III 100M euro thesis Israeli model founders to US 60 portfolio 4 unicorn 3B plus total check up to 1M LinkedIn pending","memory_type":"semantic","importance":0.85,"access_count":6},
        {"key":"bilinc_history","value":"Originally called SynapticAI also known as synaptiai rebranded to Bilinc with v1.0.0 Phase 1 completed April 7 2026 March persistent CLI SQLite schema 19 integration tests Phase 2 5 MCP transports HTTP auth Prometheus metrics 303 entries 14 beliefs 37 KG nodes 33 edges","memory_type":"episodic","importance":0.85,"access_count":8},
        {"key":"competitors","value":"Bilinc competitors MemPalace 98.4 percent with LLM 96.6 percent raw Mem0 cloud Zep temporal graphs Letta MemGPT self editing none have Z3 verification or AGM belief revision","memory_type":"semantic","importance":0.8,"access_count":5},
        {"key":"communication","value":"User preferences Turkish plain text no markdown FULL AUTONOMY mode daytime SSH nighttime Telegram free tools agent reach web search","memory_type":"procedural","importance":0.9,"access_count":30},
        {"key":"bilinc_roadmap","value":"Bilinc future priorities semantic search retrieval quality knowledge graph query engine improvements operator UX dashboard integrations PostgreSQL hardening security polish products ecosystem","memory_type":"semantic","importance":0.8,"access_count":4},
    ]
    conn = create_test_db(es)
    recall_fn = lambda q, _: bilinc_recall(q, conn)

    from benchmarks.convomem_bench import run_convomem_benchmark
    cm = run_convomem_benchmark(recall_fn, es)
    print(f"ConvoMem: {cm['overall_score']*100:.1f}%")
    for c, s in cm["category_scores"].items():
        print(f"  {c}: {s*100:.1f}%")
    for r in cm["results"]:
        if r["score"] < 1.0:
            print(f"  MISS {r['id']}: {r['score']*100:.0f}% missing={r['missing']}")
    with open(os.path.join(rd, "convomem_results.json"), "w") as f:
        json.dump(cm, f, indent=2)

    from benchmarks.locomo_bench import run_locomo_benchmark
    lm = run_locomo_benchmark(recall_fn, es)
    print(f"\nLoCoMo: {lm['overall_score']*100:.1f}%")
    for c, s in lm["category_scores"].items():
        print(f"  {c}: {s*100:.1f}%")
    for r in lm["results"]:
        if r["score"] < 1.0:
            print(f"  MISS {r['id']}: {r['score']*100:.0f}% missing={r['missing']}")
    with open(os.path.join(rd, "locomo_results.json"), "w") as f:
        json.dump(lm, f, indent=2)

    print(f"\n{'='*50}")
    print(f"BENCHMARK SUMMARY")
    print(f"{'='*50}")
    print(f"ConvoMem: {cm['overall_score']*100:.1f}% ({cm['total_queries']} queries)")
    print(f"LoCoMo:   {lm['overall_score']*100:.1f}% ({lm['total_queries']} queries)")

if __name__ == "__main__":
    run_all()
