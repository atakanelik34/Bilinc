# Bilinc — Phase 4 Detail Plan: MCP + Ecosystem

> **Created:** 2026-04-07
> **Phase:** 4 — MCP Server v2 + Adapter Layer + TypeScript SDK
> **Expected Version:** v0.4.0
> **Target Tests:** 15+ (plan: 20+)
> **Duration:** ~5-7 saat (marathon session)
> **Pre-requisites:** Phase 1 ✅, Phase 2 ✅, Phase 3 ✅

---

## 🔍 CURRENT STATE ANALYSIS

### What exists (broken/stale):
| Component | File | Issues |
|-----------|------|--------|
| MCP Server v1 | `mcp_server/server.py` | 5 tools, async StatePlane calls not awaited, missing Phase 3 tools |
| MCP __init__.py | `mcp_server/__init__.py` | Empty (only docstring) |
| Tests | `test_integration.py` | 3 tests, all fail (async/coroutine issues, missing methods) |

### What's missing:
| Component | File | Status |
|-----------|------|--------|
| MCP Server v2 | `mcp_server/server_v2.py` (new) | ❌ |
| Adapter Layer | `adapters/__init__.py` | ❌ |
| Mem0 Adapter | `adapters/mem0_adapter.py` | ❌ |
| Letta Adapter | `adapters/letta_adapter.py` | ❌ |
| Cognee Adapter | `adapters/cognee_adapter.py` | ❌ |
| Provider Pattern | `adapters/base.py` | ❌ |
| TypeScript SDK | `packages/ts-sdk/` | ❌ |

### Existing MCP Server tools (v1):
| Tool | Status | Notes |
|------|--------|-------|
| `commit` | ⚠️ Broken | Calls async `plane.commit()` without await |
| `recall` | ⚠️ Broken | Requires `intent` param that doesn't exist |
| `forget` | ⚠️ Broken | Async coroutine, not awaited |
| `explain` | ⚠️ Broken | `explain_forgetting()` doesn't exist |
| `status` | ⚠️ Broken | Uses missing `get_stats()`, `get_drift_report()` |

---

## 📋 STEP-BY-STEP PLAN

### Adım 4.1: MCP Server v2 — Full Rewrite (2 saat)

**Strategy:** YENİ file oluştur (`server_v2.py`), eski `server.py`'yi koru. Yeni server sync StatePlane ile çalışır, Phase 3 tools içerir.

#### 4.1.1: Tool Design (12 tools)

| # | Tool Name | Description | Input Schema | Output |
|---|-----------|-------------|-------------|--------|
| 1 | `commit_mem` | Store memory with auto-AGM revision | `key`, `value`, `memory_type`, `importance`, `source` | AGMResult JSON |
| 2 | `recall` | Retrieve memory by key or type | `key?`, `memory_type?`, `limit`, `min_strength` | MemoryEntry[] JSON |
| 3 | `forget` | Delete memory with reason tracking | `key`, `reason` | `{status, key}` |
| 4 | `revise` | AGM belief revision with conflict resolution | `key`, `value`, `importance`, `strategy?` | AGMResult JSON |
| 5 | `status` | Operational stats + verification status | (none) | Stats JSON |
| 6 | `verify` | Run Z3 + audit verification on key | `key` | VerificationResult JSON |
| 7 | `consolidate` | Trigger sleep consolidation cycle | `memory_type?` | ConsolidationReport JSON |
| 8 | `snapshot` | Get verifiable state snapshot + merkle root | `include_audit?` | Snapshot JSON |
| 9 | `diff` | State diff between two timestamps | `ts_a`, `ts_b` | Diff JSON |
| 10 | `rollback` | Restore state to previous timestamp | `ts` | RollbackResult JSON |
| 11 | `query_graph` | Knowledge graph traversal | `entity`, `max_depth`, `relation_filter?` | Subgraph JSON |
| 12 | `contradictions` | List all detected contradictions | (none) | Contradictions[] JSON |

#### 4.1.2: Architecture Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Transport | `streamable-http` | Production-ready, Claude Code compatible |
| Auth | Optional API key (`STATEMEL_API_KEY` env) | Dev = no auth, Prod = env-based |
| Error handling | Try/except → structured JSON error | Never crash, always return TextContent |
| Rate limiting | Simple in-memory token bucket (10 req/min per caller) | No external deps |
| StatePlane init | Sync mode (no backend async) | MCP tool handlers are async but StatePlane sync works |

#### 4.1.3: Files to Create/Modify

| Action | File | Lines (est) |
|--------|------|-------------|
| CREATE | `src/bilinc/mcp_server/server_v2.py` | ~350 |
| CREATE | `src/bilinc/mcp_server/rate_limiter.py` | ~80 |
| UPDATE | `src/bilinc/mcp_server/__init__.py` | +10 |
| MODIFY | `src/bilinc/core/stateplane.py` | +sync wrappers if needed |

#### 4.1.4: Test Plan (6 tests)

| # | Test Name | What it verifies |
|---|-----------|-----------------|
| 1 | `test_mcp_commit_recall_roundtrip` | Commit → recall returns same value |
| 2 | `test_mcp_forget` | Forget removes entry, status reflects change |
| 3 | `test_mcp_revise_agm` | Revise triggers AGM, conflict resolution logged |
| 4 | `test_mcp_query_graph` | Semantic commit populates KG, query returns subgraph |
| 5 | `test_mcp_contradictions` | Contradiction detection via MCP tool |
| 6 | `test_mcp_error_handling` | Invalid tool name, missing params → graceful error JSON |

---

### Adım 4.2: Adapter Layer — Provider Pattern (1.5 saat)

**Strategy:** Abstract pattern + 3 mock adapters (no real API calls needed for v0.4).

#### 4.2.1: Provider Pattern Design

```python
# adapters/base.py
class MemoryProvider(ABC):
    """Abstract interface for external memory providers."""

    @abstractmethod
    async def extract(self, text: str) -> List[MemoryEntry]:
        """Extract structured memory entries from raw text."""

    @abstractmethod
    async def store(self, entries: List[MemoryEntry]) -> int:
        """Store entries in the external provider. Returns count."""

    @abstractmethod
    async def retrieve(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        """Retrieve entries matching query from external provider."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider credentials/deps are available."""
```

#### 4.2.2: Adapter Specifications

| Adapter | File | What it does | Dependencies | Real or Mock? |
|---------|------|-------------|-------------|-------------|
| Mem0 | `adapters/mem0_adapter.py` | Mem0AI → StatePlane provider | `mem0ai` package | Mock (check import) |
| Letta | `adapters/letta_adapter.py` | Letta core/archival → StatePlane | `letta` SDK | Mock (check import) |
| Cognee | `adapters/cognee_adapter.py` | Cognee graph → StatePlane KG | `cognee` package | Mock (check import) |

#### 4.2.3: Each Adapter Implements

| Method | Behavior (Mock) |
|--------|----------------|
| `extract(text)` | Parse text → MemoryEntry[] using simple regex/NLP |
| `store(entries)` | Return `len(entries)` (pretend stored) |
| `retrieve(query)` | Return empty list or mock entries |
| `is_available()` | Try import, return True/False |

#### 4.2.4: Files to Create

| File | Lines (est) |
|------|-------------|
| `adapters/__init__.py` | ~20 |
| `adapters/base.py` | ~60 |
| `adapters/mem0_adapter.py` | ~80 |
| `adapters/letta_adapter.py` | ~80 |
| `adapters/cognee_adapter.py` | ~80 |

#### 4.2.5: Test Plan (4 tests)

| # | Test Name | What it verifies |
|---|-----------|-----------------|
| 1 | `test_mem0_adapter_mock` | Mock adapter extracts + stores |
| 2 | `test_letta_adapter_mock` | Letta adapter handles import simulation |
| 3 | `test_cognee_adapter_mock` | Cognee adapter maps to KG nodes |
| 4 | `test_provider_pattern_validation` | Abstract base class pattern validates |

---

### Adım 4.3: TypeScript SDK (1.5 saat)

**Strategy:** Monorepo sub-package, HTTP client for MCP server + typed interfaces.

#### 4.3.1: SDK Architecture

```
packages/ts-sdk/
├── package.json
├── tsconfig.json
├── src/
│   ├── index.ts            # Main exports
│   ├── types.ts            # TypeScript interfaces
│   ├── stateplane.ts       # HTTP client for StatePlane
│   ├── mcp-client.ts       # MCP protocol client
│   └── models.ts           # MemoryType, MemoryEntry types
└── tests/
    ├── stateplane.test.ts  # HTTP client tests
    └── types.test.ts       # Type safety tests
```

#### 4.3.2: TypeScript Interfaces

```typescript
export enum MemoryType {
  Episodic = "episodic",
  Procedural = "procedural",
  Semantic = "semantic",
  Working = "working",
  Spatial = "spatial",
}

export interface MemoryEntry {
  id: string;
  key: string;
  value: any;
  memory_type: MemoryType;
  importance: number;
  current_strength: number;
  is_verified: boolean;
  created_at: number;
}

export interface StatePlaneOptions {
  baseUrl?: string;       // Default: http://localhost:8080
  apiKey?: string;
  timeout?: number;       // Default: 5000ms
}

export interface AGMResult {
  operation: "expand" | "contract" | "revise";
  success: boolean;
  conflicts_resolved: number;
  explanation_text: string;
}
```

#### 4.3.3: StatePlane Class

```typescript
export class StatePlane {
  constructor(options?: StatePlaneOptions);

  async commit(key: string, value: any, options?: CommitOptions): Promise<AGMResult>;
  async recall(key: string, options?: RecallOptions): Promise<MemoryEntry | null>;
  async forget(key: string, reason?: string): Promise<boolean>;
  async revise(key: string, value: any, importance: number): Promise<AGMResult>;
  async status(): Promise<StatePlaneStats>;
  async queryGraph(entity: string, maxDepth?: number): Promise<KGSubgraph>;
  async contradictions(): Promise<Contradiction[]>;
}
```

#### 4.3.4: MCP Client

```typescript
export class StatemlMCPClient {
  constructor(url: string);

  async callTool(name: string, args: Record<string, any>): Promise<any>;
  async listTools(): Promise<ToolDefinition[]>;
  async commitMem(key: string, value: any): Promise<any>;
  async recall(key: string): Promise<any>;
}
```

#### 4.3.5: Files to Create

| File | Lines (est) |
|------|-------------|
| `packages/ts-sdk/package.json` | ~30 |
| `packages/ts-sdk/tsconfig.json` | ~20 |
| `packages/ts-sdk/src/index.ts` | ~20 |
| `packages/ts-sdk/src/types.ts` | ~80 |
| `packages/ts-sdk/src/stateplane.ts` | ~150 |
| `packages/ts-sdk/src/mcp-client.ts` | ~80 |

#### 4.3.6: Test Plan (3 tests — TypeScript compilation + type checks)

| # | Test/Check | What it verifies |
|---|-----------|-----------------|
| 1 | TypeScript compilation | `tsc --noEmit` passes |
| 2 | Type safety | MemoryEntry, AGMResult types compile |
| 3 | Export validation | All public exports are present |

---

### Adım 4.4: PyPI v0.4.0 Release Prep (0.5 saat)

| Task | Details |
|------|---------|
| Version bump | `pyproject.toml`: `0.2.0a1` → `0.4.0a1` |
| Dependencies | Add `mcp`, `networkx` to requirements (already present but verify) |
| README update | Add Phase 3 + 4 feature sections |
| PyPI upload | `build` + `twine upload` (if credentials available) |
| Verify | `pip install bilinc==0.4.0a1` locally |

---

## 📊 TEST SUMMARY

| Step | Tests Added | Cumulative |
|------|------------|------------|
| 4.1 MCP Server v2 | 6 | 67 (existing) + 6 = 73 |
| 4.2 Adapter Layer | 4 | 73 + 4 = 77 |
| 4.3 TypeScript SDK | 3 | 77 + 3 = 80 |
| **Total Phase 4** | **13** | **80+ tests** |

## 📁 FILE GROWTH

| Phase | New Files | Updated Files | Cumulative |
|-------|-----------|---------------|------------|
| Phase 1 | 8 | 3 | 8 |
| Phase 2 | 2 | 2 | 10 |
| Phase 3 | 3 | 1 | 13 |
| **Phase 4** | **10** | **2** | **23** |

## ⚠️ RISKS & MITIGATIONS

| Risk | Impact | Mitigation |
|------|--------|------------|
| MCP SDK breaking changes | Server fails to start | Pin `mcp` version in pyproject.toml, test locally first |
| StatePlane async/sync mismatch | Tools return coroutines | Use sync wrapper methods (already added in Phase 3.4) |
| TypeScript SDK npm conflicts | Publish fails | Check `@stateml/core` namespace availability |
| Adapter packages not installed | Import errors | `is_available()` guard, graceful fallback |
| Rate limiter memory leak | Growing dict | Max 1000 entries, TTL eviction |

## 🎯 SUCCESS CRITERIA

- [ ] MCP server starts without errors
- [ ] All 12 MCP tools respond correctly (tested via mock client)
- [ ] 3 adapters compile + mock functionality verified
- [ ] TypeScript SDK compiles with `tsc --noEmit`
- [ ] 13 new tests pass
- [ ] No regressions (Phase 1-3 tests still green)
- [ ] `pyproject.toml` version = `0.4.0a1`
- [ ] README updated with MCP + adapter documentation

---

*Plan created: 2026-04-07. Ready for execution when you say the word.*
