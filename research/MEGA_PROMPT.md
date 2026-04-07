# SYNAPTIC AI — MEGA PROMT (v1.0.0)
**"Context Control Plane for Long-Running AI Agents"**

> Bu doküman, Bilinc'in sıfırdan kodlanması için gerekli **tüm** teknik kararları, mimari prensipleri, dosya yapısını ve implementasyon detaylarını içerir.
> 3 araştırma raporu (ChatGPT Deep Research, Subagent Trio, Grok 4.20) ve Neo'nun analizinin sentezidir.
> Bu promptu bir LLM'e veya kendine verdiğinde, **kelimesi kelimesine** uygulaman gerekir.

---

## 0. ÜRÜN VİZYONU & KONUMLANDIRMA

**Ne Değiliz:** Bir memory database, bir RAG aracı, bir vector store.
**Ne Yazık:** AI Agent'lar için **Context Control Plane**.

**Temel Felsefe:** "Memory artık depolama değil — durum yönetimi."
- Context window artışı, "retrieve & inject" yapanları ezer.
- "Recall, Verify, Commit" yapan stateful katmanı güçlendirir.
- Synaptic AI: **"Remember less. Stay correct longer."**

**Hedef Kitle (Phase 1):** Claude Code / Cursor kullanıcıları (sinir olmuş, session amnesia yaşayan developer'lar).
**Distribution (Phase 1):** MCP Server + CLI + LangGraph adapter.

---

## 1. MİMARİ PRENSİPLER (DEĞİŞMEZ)

1. **State-First:** Her memory girişi 8 boyutlu yapılandırılmış state'tir (serbest metin değil).
2. **Bounded Footprint:** Ne kadar etkileşim olursa olsun, context'e giren state ~2000 token'ı geçmez.
3. **Zero-Default Trust:** Hiçbir bilgi otomatik commit edilmez. DQG Gate'den geçmek zorunda.
4. **Hybrid Retrieval:** Sadece semantic yetmez. BM25 (exact) + Vector (semantic) + RRF (merge) + Rerank (kalite).
5. **Sub-50ms Retrieval:** L1 Redis cache + efficient index. Developer flow'u öldürme.
6. **Portable:** MCP streamable-http üzerinden her agent'a takılabilir.
7. **Self-Documenting:** Her commit'in provenance'ı (kaynak, zaman, güven skoru) loglanır.

---

## 2. TEKNOLOJİ STACKİ

| Katman | Teknoloji | Neden |
|--------|-----------|-------|
| **Core Engine** | Python 3.10+ (Pydantic v2) | Type safety, validation, serialization |
| **Storage** | SQLite (+ JSONB) | Zero-config, local-first, portable |
| **Vector Index** | FAISS (CPU) | Sub-50ms, no infra dependency |
| **Exact Match** | BM25 (rapidfuzz/whoosh) | Keyword recall, version numbers, exact strings |
| **Cache** | In-memory dict + TTL | Basit, hızlı, external dependency yok |
| **Reranker** | Cross-encoder (sentence-transformers, optional) | Kalite artışı, fallback'siz çalışmalı |
| **API** | FastMCP (MCP Protocol) | Universal compatibility |
| **CLI** | Click / argparse | Developer UX |
| **Test** | pytest | Standard, reliable |

**KESİNlikle KULLANILMAYACAK:** Postgres, Redis, Docker (MVP'de). Sıfır dependency kurulumu.

---

## 3. DOSYA YAPISI

```
synaptic-ai/
├── pyproject.toml              # Build system, dependencies
├── README.md                   # "Context Control Plane" positioning
├── LICENSE                     # MIT
│
├── src/synaptic/
│   ├── __init__.py
│   ├── cli.py                  # CLI entrypoint (`synaptic recall`, `synaptic init`)
│   ├── config.py               # Pydantic Settings (paths, thresholds, models)
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── state.py            # Compressed Cognitive State (8-dim schema)
│   │   ├── store.py            # SQLite + FAISS + BM25 storage layer
│   │   └── consolidation.py    # Async background: episodic→semantic, dedup, TTL
│   │
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── retriever.py        # Hybrid pipeline: BM25 + Vector → RRF → Rerank → Top-K
│   │   └── reranker.py         # Cross-encoder fallback (optional)
│   │
│   ├── gate/
│   │   ├── __init__.py
│   │   └── dqg.py              # Decision Qualification Gate (verify/commit/reject)
│   │
│   ├── mcp_server.py           # FastMCP server (recall, verify, commit, forget, audit, state)
│   └── utils/
│       ├── __init__.py
│       ├── logger.py           # Minimal structlog setup
│       └── tokens.py           # Token estimation for bounded footprint
│
├── tests/
│   ├── test_ccs.py             # 8-dim state serialization/deserialization
│   ├── test_retrieval.py       # Hybrid pipeline correctness
│   ├── test_dqg.py             # Gate logic: verify/commit/reject
│   └── test_mcp.py             # MCP tool invocation (mock)
│
└── examples/
    ├── claude_code_integration.py  # How to use with Claude Code
    ├── langgraph_adapter.py        # LangGraph checkpoint adapter
    └── cursor_integration.md       # Cursor setup guide
```

---

## 4. MERKEZİ VERİ YAPILARI

### 4.1 Compressed Cognitive State (8-Dimension)

```python
class CompressedCognitiveState(BaseModel):
    """The core Synaptic AI state — replaces unbounded transcript replay."""
    
    episodic_trace: str = Field(..., description="Özet: Son etkileşimin ne olduğu")
    semantic_gist: dict[str, str] = Field(default_factory=dict, description="Öğrenilen genel bilgiler (kalıcı)")
    focal_entities: dict[str, dict] = Field(default_factory=dict, description="Aktif varlıklar: dosya, proje, kişi")
    relational_map: list[dict] = Field(default_factory=list, description="Varlıklar arası ilişkiler")
    goal_orientation: list[str] = Field(default_factory=list, description="Mevcut hedefler/intentler")
    constraints: dict[str, dict] = Field(default_factory=dict, description="Sınırlar + TTL + stale flag")
    predictive_cue: str = Field(default="", description="Sıradaki olası adım tahmini")
    uncertainty_signals: dict[str, float] = Field(default_factory=dict, description="Nerede emin değil (0.0–1.0)")
    
    # Metadata
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    turn_count: int = 0
    token_estimate: int = 0  # Hedef: ~2000 token max
```

### 4.2 Memory Entry (Ham Veri → State'e Dönüşür)

```python
class MemoryEntry(BaseModel):
    id: str
    type: Literal["episodic", "semantic", "entity", "constraint", "goal"]
    content: str
    source: str  # "user", "tool_output", "agent_decision", "external"
    source_hash: str  # SHA256 — provenance
    confidence: float  # 0.0–1.0
    created_at: datetime
    ttl: int | None  # Seconds to live (None = permanent)
    stale: bool = False
    stale_reason: str | None = None
    superseded_by: str | None = None  # ID of newer conflicting entry
    tags: list[str] = Field(default_factory=list)
```

### 4.3 DQG Decision

```python
class DQGDecision(BaseModel):
    action: Literal["commit", "reject", "update", "flag_conflict"]
    entry_id: str
    reason: str
    confidence_delta: float  # -1.0 to +1.0
    conflict_with: str | None = None  # ID of conflicting entry
    requires_human: bool = False
```

---

## 5. MODÜL SPESİFİKASYONLARI

### 5.1 `core/state.py` — CCS Engine

**Sorumluluk:** 8 boyutlu state yönetimi. Her turn'de state güncellenir.
**Fonksiyonlar:**
- `update_state(state: CCS, new_entry: MemoryEntry) -> CCS`
- `apply_stale_detection(state: CCS) -> CCS` (TTL + conflict check)
- `serialize_for_context(state: CCS, max_tokens: int = 2000) -> str` → LLM context'e enjekte edilecek string
- `token_budget_check(state: CCS) -> bool` → 2000 token aşılırsa compression trigger

**Kritik Kural:** `serialize_for_context` asla 2000 token'ı geçmemeli. Aşılırsa:
1. `uncertainty_signals`'ı koru
2. `constraints`'ı koru
3. `goal_orientation`'ı koru
4. `episodic_trace`'i özetle
5. Semantic gist'den düşük confidence'lıları at

### 5.2 `core/store.py` — Storage Layer

**Sorumluluk:** MemoryEntry'leri SQLite'a yaz, FAISS vector index'ini güncelle, BM25 index'ini güncelle.
**Tablolar:**
- `memory_entries` (id, type, content, source, source_hash, confidence, created_at, ttl, stale, stale_reason, superseded_by, tags, vector_id)
- `ccs_snapshots` (id, turn_count, state_json, created_at)
- `audit_log` (id, entry_id, action, reason, timestamp)

**FAISS:** IndexFlatIP (inner product), dimension 384 (all-MiniLM-L6-v2 embedding).
**BM25:** `whoosh` veya `rapidfuzz` ile content üzerinde full-text search.

### 5.3 `retrieval/retriever.py` — Hybrid Pipeline

**Pipeline (4 Aşama):**

**Aşama 1 — Dual Retrieval (Paralel):**
- Dense: FAISS top-200 (query embedding cosine similarity)
- Sparse: BM25 top-200 (query keyword match)

**Aşama 2 — RRF Merge:**
- `RRF(d) = SUM(1 / (k + rank_d))` for each document, k=60
- Farklı scoring sistemlerini normalize etmeye gerek yok.

**Aşama 3 — Rerank (Opsiyonel ama önerilen):**
- Top-50 → Cross-encoder (sentence-transformers) → Top-10
- Reranker yoksa: RRF Top-10 doğrudan dön.

**Aşama 4 — Context Assembly:**
- Top-10 memory entry'yi türüne göre gruplandır
- `semantic_gist`'e en uygun olanları öne çıkar
- Stale'leri filtrele
- `max_tokens` sınırına göre truncate et

### 5.4 `gate/dqg.py` — Decision Qualification Gate

**Sorumluluk:** Yeni bir bilgiyi mevcut state ile karşılaştır → commit/reject/update/flag kararını ver.

**Karar Matrisi:**

| Yeni Bilgi Durumu | Mevcut State | Aksiyon |
|-------------------|--------------|---------|
| Yeni, conflict yok | Boş veya uyumlu | ✅ COMMIT |
| Yeni, conflict var (aynı entity, farklı değer) | Eski bilgi mevcut | ⚠️ FLAG_CONFLICT → Eski'yi stale yap, yeni'yi commit (human review opsiyonel) |
| Güncelleme (aynı source_hash, farklı confidence) | Mevcut entry var | 🔄 UPDATE → confidence'ı güncelle |
| Duplicate (near-identical content + tags) | Mevcut entry var | ❌ REJECT → Duplicate log |
| Low confidence (<0.3) + no source | - | ❌ REJECT |
| High confidence (>0.8) + constraint violation | Constraint var | ⚠️ FLAG_CONFLICT → Human review required |

**Stale Detection Kuralları:**
1. TTL süresi doldu → `stale=True`, `stale_reason="TTL_EXPIRED"`
2. Aynı entityId'de daha yeni entry var → Eski `superseded_by=Yeni_ID`, `stale=True`
3. Constraint çelişkisi (örn. "Python kullan" vs "Node.js kullan") → İkisini de flag_conflict → Human review
4. Turn_count > 50 ve episodic_trace hiç referans edilmedi → TTL 2x azalt (decay)

### 5.5 `core/consolidation.py` — Background Worker

**Sorumluluk:** Session sonunda (veya idle'da) memory'yi optimize et.
**İşler:**
1. **Episodic → Semantic Konsolidasyon:** 10+ benzer episodic entry'yi tek semantic gist'e özetle.
2. **Entity Resolution:** "user.py", "User class", "the user module" → tek entity'ye merge et.
3. **Deduplication:** Near-duplicate entry'leri birleştir.
4. **Importance Scoring:** `S(m) = α*confidence + β*γ^(t-ti) + δ*recency` (α=0.5, β=0.3, γ=0.95, δ=0.2)
5. **Low-importance pruning:** S(m) < 0.2 ve 5 turn'dür referans edilmeyenleri sil (log'a yaz).

**Async:** `asyncio.create_task()` ile background'da çalışır. Main loop'u bloklamaz.

### 5.6 `mcp_server.py` — MCP Tools

**FastMCP üzerinden 6 tool:**

| Tool | Tanım | Parametreler | Dönüş |
|------|-------|-------------|-------|
| `recall` | Query'ye en ilgili memory'leri getir | `query` (str), `limit` (int, default 5) | String: formatted memory entries |
| `commit` | Yeni bilgiyi state'e ekle | `entry` (MemoryEntry JSON) | String: commit sonucu |
| `verify` | Bir entry'nin valid olup olmadığını kontrol et | `entry_id` (str) | String: verify raporu |
| `forget` | Bir entry'yi stale/sil | `entry_id` (str), `reason` (str) | String: forget sonucu |
| `audit` | Memory değişiklik geçmişini getir | `entry_id` (str, optional), `limit` (int, default 20) | String: audit log |
| `state` | Mevcut CCS durumunu getir | `format` (str: "json"或"text", default "text") | String: current state |

---

## 6. IMPLEMENTATION KURALLARI

1. **Type Hints:** Her fonksiyon parametre ve dönüş tipi belirtilmeli.
2. **Pydantic V2:** Tüm veri yapıları `BaseModel` ile validate edilmeli.
3. **No External APIs:** Hiçbir external API (OpenAI, Anthropic vb.) çağrılmamalı. Her şey local çalışmalı.
4. **Zero-Config Default:** `synaptic init` komutu çalıştırıldığında her şey default ayarlarla başlamalı.
5. **Error Handling:** Her public fonksiyon `try/except` ile wrap edilmeli, hata mesajları kullanıcı dostu olmalı.
6. **Logging:** `structlog` ile JSON log. Her commit/reject/retrieval loglanmalı.
7. **Test-First:** Her modül için en az 3 test yazılmalı (happy path, edge case, error case).

---

## 7. CLI KOMUTLARI

```bash
synaptic init                     # Initialize project (creates ~/.synaptic/, SQLite, indexes)
synaptic recall "query here"      # Retrieve relevant memories
synaptic commit --type semantic --content "..."  # Add new memory
synaptic verify <entry_id>        # Verify entry validity
synaptic state                    # Show current CCS state
synaptic audit [--entry <id>]     # Show audit log
synaptic forget <entry_id>        # Remove memory entry
synaptic health                   # Diagnostics: store size, index health, stale count
```

---

## 8. MİLAT TAŞLARI (SPRINT PLAN)

### Sprint 1 (Gün 1-3): Core Engine
- [x] `core/state.py` — CCS data model + serialization
- [x] `core/store.py` — SQLite setup + FAISS + BM25
- [x] `core/consolidation.py` — Background async worker
- [ ] `tests/test_ccs.py`

### Sprint 2 (Gün 4-7): Retrieval + Gate
- [x] `retrieval/retriever.py` — Hybrid pipeline
- [x] `gate/dqg.py` — Decision gate
- [x] `retrieval/reranker.py` — Cross-encoder fallback (optional)
- [ ] `tests/test_retrieval.py`, `tests/test_dqg.py`

### Sprint 3 (Gün 8-10): MCP + CLI
- [x] `mcp_server.py` — FastMCP server
- [x] `cli.py` — CLI commands
- [ ] `tests/test_mcp.py`
- [ ] `examples/` — Claude Code, Cursor, LangGraph integration guides

### Sprint 4 (Gün 11-14): Polish + Publish
- [ ] README.md — "Context Control Plane" positioning + quickstart
- [ ] pyproject.toml — Build config
- [ ] `examples/claude_code_integration.py` — Working example
- [ ] Publish to MCP Registry + Smithery + Glama

---

## 9. TEST KRİTERLERİ

| Modül | Happy Path | Edge Case | Error Case |
|-------|-----------|-----------|------------|
| CCS | Serialize/deserialize 8-dim state | token_estimate 2000 limitini aşınca truncation | Invalid JSON input |
| Store | MemoryEntry ekle, FAISS + BM25 update | Duplicate entry, TTL expiry | SQLite locked, FAISS index corrupt |
| Retriever | 10 relevant result dönsün | Empty query, no matches | FAISS index empty |
| DQG | Commit, reject, flag_conflict doğru | Conflicting entries, low confidence | Missing required fields |
| MCP | 6 tool çağrılabilir, doğru response | Invalid tool params | Server not started |

---

## 10. PERFORMANS HEDEFLERİ

| Metrik | Hedef | Ölçüm |
|--------|-------|-------|
| Recall Latency (p95) | < 50 ms | `time()` before/after retriever call |
| Token Footprint (serialized state) | < 2000 token | `tiktoken` estimation |
| Memory Size (1000 entries) | < 50 MB | SQLite file size |
| Startup Time | < 1 second | `time()` before/after init |
| FAISS Index Build (1000 entries) | < 2 seconds | `time()` index add |

---

## 11. MONETİZASYON (Gelecek)

**Phase 1 (Şimdi):** OSS Core (MIT) — Distribution
**Phase 2 (Month 2):** x402 MCP Server ($0.02/call) — Agent volume
**Phase 3 (Month 3):** Cloud MCP ($19/mo) — Managed
**Phase 4 (Month 6):** Pro SaaS ($49/mo) — Team + Analytics
**Phase 5 (Month 9):** Enterprise ($199+/mo) — SSO + Audit + SLA

---

## 12. KESİN YASAKLAR

- ❌ External LLM API çağrısı yapma (OpenAI, Anthropic, vb.)
- ❌ Postgres/Redis/Docker bağımlılığı (MVP'de)
- ❌ "Memory database" söylemi (Context Control Plane)
- ❌ 2000 token'ı geçen serialized state
- ❌ Otomatik commit (her şey DQG'den geçmeli)
- ❌ Unbounded growth (TTL + pruning zorunlu)

---

> **NOT:** Bu doküman canlıdır. Code yazıldıkça güncellenmelidir. İlk PR'dan sonra v1.1.0'a revize edilecektir.

**Son Güncelleme:** 5 Nisan 2026
**Yazar:** Neo (Bilinc Architect)
