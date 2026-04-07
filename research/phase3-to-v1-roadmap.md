# Bilinc — Phase 3 → v1.0 Detail Roadmap

> **Created:** April 6, 2026
> **Status:** Phase 1 ✅ (32/32 tests), Phase 2 ✅ (15/15 tests)  
> **Next:** Phase 3 Belief Engine → Phase 4 MCP/Ecosystem → Phase 5 v1.0 Production
> **Total Tests So Far:** 47/47 passing

---

## 📊 CURRENT STATUS (v0.2.0a1)

### ✅ Phase 1: Brain Core (COMPLETE)
| Component | File | Tests | Status |
|-----------|------|-------|--------|
| 5 Memory Types | `core/models.py` | 3/3 | ✅ |
| SQLite Backend | `storage/sqlite.py` | 5/5 | ✅ |
| WorkingMemory (8 slots) | `core/working_memory.py` | 4/4 | ✅ |
| Consolidation (7 phases) | `adaptive/consolidation.py` | 8/8 | ✅ |
| System 1/2 Arbiter | `core/dual_process.py` | 4/4 | ✅ |
| Confidence Estimator | `core/confidence.py` | 3/3 | ✅ |
| Forgetting Engine | `adaptive/forgetting_engine.py` | 3/3 | ✅ |
| StatePlane (integration) | `core/stateplane.py` | 3/3 | ✅ |

### ✅ Phase 2: Verification Layer (COMPLETE)
| Component | File | Tests | Status |
|-----------|------|-------|--------|
| Z3 SMT Verifier (6 invariants) | `core/verifier.py` | 6/6 | ✅ |
| Merkle Audit Trail | `core/audit.py` | 2/2 | ✅ |
| State Diff | `core/stateplane.py` | 1/1 | ✅ |
| Rollback API | `core/stateplane.py` | 1/1 | ✅ |
| Verify Single Entry | `core/stateplane.py` | 1/1 | ✅ |
| Snapshot API | `core/stateplane.py` | 1/1 | ✅ |
| Integration Flow | `core/stateplane.py` | 3/3 | ✅ |

---

## 🧠 PHASE 3: BELIEF ENGINE (AGM → Multi-Agent)

**Goal:** AGM Belief Revision production-ready + multi-agent belief sync + knowledge graph  
**Duration:** ~6-8 saat  
**Target Tests:** 20+ test  
**Expected Version:** v0.3.0

### Adım 3.1: AGM Postulate Engine (2 saat)
**Dosyalar:** `src/bilinc/adaptive/agm_engine.py` (YENİ)

**Detaylar:**
- `AGMEngine` class with full Alchourrón-Gärdenfors-Makinson operators:
  - `expand(key, entry)` → Add belief without consistency check (creates potential conflicts)
  - `contract(key)` → Remove belief while maintaining logical closure (Levi identity)
  - `revise(key, entry)` → Add + resolve conflicts via AGM revision operators
- **Epistemic Entrenchment Ordering:** Total preorder over beliefs (≤)
  - Beliefs ordered by epistemic importance
  - When revising, less entrenched beliefs are dropped first
  - Formal: K ⊢ φ means φ is in the logical closure of belief set K
- **Darwiche & Pearl Iterated Revision:** Postulates for repeated belief change
  - (DP1) If α ⊨ μ, then (K * μ) * α = K * α
  - (DP2) If α ⊨ ¬μ, then (K * μ) * α = K * α
  - (DP3) If α ∈ K * μ and α ⊨ ¬μ, then α ∈ K
  - (DP4) If ¬α ∉ K * μ, then ¬α ∉ (K * μ) * α
- **Conflict Resolution Strategies:**
  - `ENTRENCHMENT`: Drop less entrenched beliefs (default)
  - `RECENCY`: Trust newer over older
  - `VERIFICATION`: Trust verified over unverified
  - `IMPORTANCE`: Trust higher-importance beliefs
- **Explanation Trail:** Every AGM operation logged with:
  - Which beliefs were dropped and why
  - Which strategy was used
  - Epistemic ordering before/after

**Test Plan (6 test):**
1. `test_agm_expand` — Simple addition, no conflict
2. `test_agm_contract` — Removal with closure maintenance
3. `test_agm_revise_conflict` — Add conflicting, resolve via entrenchment
4. `test_agm_darwiche_pearl_postulates` — All 4 DP postulates verified
5. `test_agm_explanation_trail` — Full explanation of revision steps
6. `test_agm_multi_conflict` — Multiple conflicts, different strategies

### Adım 3.2: Knowledge Graph Layer (2 saat)
**Dosyalar:** `src/bilinc/core/knowledge_graph.py` (YENİ)

**Detaylar:**
- Lightweight Knowledge Graph (NetworkX-backed, no external DB required)
- Node types: `Entity`, `Fact`, `Event`, `Skill`
- Edge types: `related_to`, `causes`, `contradicts`, `supports`, `temporal_before`
- `KnowledgeGraph` class:
  - `add_entity(name, entity_type, properties)` → Node
  - `add_relation(source, target, relation_type, weight)` → Edge
  - `query_entity(name)` → Node + relations
  - `traverse(start, max_depth, relation_filter)` → Subgraph
  - `find_contradictions()` → Pairs of conflicting edges
  - `export_to_json()` → Serializable format
- **Semantic Memory Integration:**
  - When semantic entries are committed → auto-extract entities + relations
  - Entity extraction: NLP-based (simple: capitalized words, patterns, metadata)
  - Relation inference: Co-occurrence in same entry, shared metadata keys

**Test Plan (4 test):**
1. `test_kg_basic_ops` — Add/query/traverse
2. `test_kg_contradictions` — Detect conflicting relations
3. `test_kg_semantic_integration` — Auto-extraction from semantic entries
4. `test_kg_serialization` — Export/import roundtrip

### Adım 3.3: Multi-Agent Belief Sync (1.5 saat)
**Dosyalar:** `src/bilinc/core/belief_sync.py` (YENİ)

**Detaylar:**
- `BeliefSyncEngine` — Synchronize beliefs across multiple agent instances
- `AgentIdentity` — Named agent with its own belief state
- **Sync Modes:**
  - `PULL`: Agent pulls updates from shared belief space
  - `PUSH`: Agent pushes its beliefs to shared space
  - `MERGE`: Bidirectional sync with conflict resolution
- **Conflict Resolution:**
  - Same key, different values across agents → AGM revision
  - Consensus-based: Majority vote weighted by agent reliability
  - Authority-based: Designated agents have higher weight
- **Sync Protocol:**
  1. `init_sync(agent_id)` → Register agent, get current shared state
  2. `push_beliefs(agent_id, entries)` → Push with timestamps
  3. `pull_updates(agent_id, since_timestamp)` → Get new/changed beliefs
  4. `merge_sync(agent_id)` → Full bidirectional reconciliation
  5. `get_divergence(agent_a, agent_b)` → List of conflicting beliefs
- **Vector Clock** for causal ordering of belief updates

**Test Plan (5 test):**
1. `test_belief_sync_push_pull` — Basic push/pull roundtrip
2. `test_belief_sync_merge` — Bidirectional reconcile
3. `test_belief_sync_conflict` — Same key, different values → resolution
4. `test_belief_sync_consensus` — Majority vote across 3 agents
5. `test_belief_sync_divergence` — Detect and list conflicts

### Adım 3.4: StatePlane Integration (1 saat)
**Dosyalar:** `src/bilinc/core/stateplane.py` (GÜNCELLEME)
- Add `agm_engine` parameter to StatePlane
- Auto-apply AGM revision on semantic/episodic commit
- Auto-populate knowledge graph from semantic entries
- `stateplane.sync(agent_id)` → belief sync integration
- `stateplane.query_graph(entity)` → KG query

**Test Plan (4 test):**
1. `test_stateplane_agm_integration` — Commit → AGM revision auto-applied
2. `test_stateplane_kg_integration` — Semantic commit → KG populated
3. `test_stateplane_belief_sync` — Full sync cycle
4. `test_phase3_complete_flow` — End-to-end Phase 3

**Phase 3 Total: 19 test → Target: 20+ test**

---

## 🌐 PHASE 4: MCP + ECOSYSTEM (Distribution)

**Goal:** Ship MCP server + adapters + TypeScript SDK for developer adoption  
**Duration:** ~5-7 saat  
**Target Tests:** 15+ test  
**Expected Version:** v0.4.0

### Adım 4.1: MCP Server v2 (2 saat)
**Dosyalar:** `src/bilinc/mcp_server/server.py` (YENİ/GÜNCELLEME)

**Detaylar:**
- Full MCP (Model Context Protocol) server using `mcp` SDK
- Tools exposed:
  - `commit_mem(key, value, type, importance)` → Store memory
  - `recall(key, type)` → Retrieve memory
  - `forget(key)` → Delete memory
  - `status()` → Show stats + verification status
  - `verify(key)` → Run Z3 + audit checks
  - `consolidate()` → Trigger sleep cycle
  - `snapshot()` → Get verifiable state snapshot
  - `diff(ts_a, ts_b)` → State difference
  - `rollback(ts)` → Restore previous state
- Transport: `streamable-http` for production
- Auth: Optional API key (env-based)
- Error handling: Graceful degradation, detailed error messages
- Rate limiting: Per-client token bucket

**Test Plan (5 test):**
1. `test_mcp_commit_recall` — Basic roundtrip
2. `test_mcp_forget` — Delete operation
3. `test_mcp_verify` → Verification check via MCP
4. `test_mcp_consolidate` → Trigger sleep cycle
5. `test_mcp_error_handling` → Invalid inputs handled gracefully

### Adım 4.2: Adapter Layer (1.5 saat)
**Dosyalar:** `src/bilinc/adapters/` (YENİ DİZİN)

**Detaylar:**
- `src/bilinc/adapters/mem0_adapter.py`
  - Wrap mem0ai as STATE PROVIDER for StatePlane
  - `Mem0Provider(mem0_instance)` → StorageBackend interface
  - Auto-sync: mem0 extraction → StatePlane verification
- `src/bilinc/adapters/letta_adapter.py`
  - Letta's core/archival/recall → StatePlane typed storage
  - Import existing Letta memories → StatePlane
- `src/bilinc/adapters/cognee_adapter.py`
  - Cognee's graph pipeline → StatePlane knowledge graph
- **Provider Pattern:**
  ```python
  class MemoryProvider(ABC):
      @abstractmethod
      async def extract(self, text: str) -> List[MemoryEntry]: ...
      @abstractmethod
      async def store(self, entries: List[MemoryEntry]) -> None: ...
      @abstractmethod
      async def retrieve(self, query: str) -> List[MemoryEntry]: ...
  ```

**Test Plan (3 test):**
1. `test_mem0_adapter` — Integration mock
2. `test_letta_adapter` — Import simulation
3. `test_provider_pattern` — Abstract pattern validation

### Adım 4.3: TypeScript SDK (1.5 saat)
**Dosyalar:** `packages/ts-sdk/` (YENİ DİZİN)

**Detaylar:**
- `packages/ts-sdk/src/index.ts` — Main exports
  ```typescript
  import { StatePlane, MemoryType, Arbiter } from '@stateml/core';
  const plane = new StatePlane('sqlite://./state.db');
  await plane.commit('pref', { theme: 'dark' }, MemoryType.SEMANTIC);
  const result = await plane.recall('pref');
  ```
- Classes: `StatePlane`, `WorkingMemory`, `Arbiter`, `ConfidenceEstimator`
- MCP client: `StatemlMCPClient` — Connect to remote MCP server
- Browser/Node compatible (isomorphic)
- Package: `@stateml/core` on npm

**Test Plan (2 test):**
1. `test_ts_sdk_structure` — Exports, types, interfaces
2. `test_mcp_client_mock` — Mock MCP roundtrip

### Adım 4.4: PyPI v0.4.0 Release (0.5 saat)
- `pyproject.toml` update: version = "0.4.0a1"
- `requirements.txt`: Add `z3-solver`, `networkx`, `mcp`
- README update with Phase 3 + 4 features
- PyPI upload
- npm publish (if SDK ready)

**Phase 4 Total: 10 test → Target: 15+ test**

---

## 🚀 PHASE 5: PRODUCTION v1.0

**Goal:** Production-ready, documented, benchmarked, launch-ready  
**Duration:** ~8-10 saat  
**Target Tests:** 30+ test  
**Expected Version:** v1.0.0

### Adım 5.1: Formal Benchmark Suite (2 saat)
**Dosyalar:** `benchmarks/` (YENİ DİZİN)

**Detaylar:**
- **Memory Retrieval Benchmark:**
  - Dataset: 1000 synthetic memories across 5 types
  - Metrics: latency (p50, p95, p99), recall accuracy, precision
  - Comparison vs: mem0ai, Letta, Cognee
- **Verification Benchmark:**
  - Dataset: 500 valid entries + 200 invalid entries
  - Metrics: verification accuracy, false positive rate, false negative rate
  - Compare: with Z3 vs without Z3
- **Consolidation Benchmark:**
  - Dataset: 200 entries, run full sleep cycle
  - Metrics: entries consolidated, entries pruned, time elapsed
  - Memory reduction % (before vs after)
- **Scalability Benchmark:**
  - Dataset: 10K → 100K entries
  - Metrics: query latency at scale, storage growth, verification time
  - SQLite vs PostgreSQL comparison

**Test Plan:** No unit tests needed, benchmark scripts

### Adım 5.2: Observability & Monitoring (1.5 saat)
**Dosyalar:** `src/bilinc/observability/` (YENİ DİZİN)

**Detaylar:**
- `MetricsCollector` — Prometheus-compatible counters/histograms
  - `synaptic_commit_total` (counter, labels: memory_type)
  - `synaptic_consolidation_duration_seconds` (histogram)
  - `synaptic_verification_failures_total` (counter, labels: rule_name)
  - `synaptic_working_memory_usage` (gauge)
  - `synaptic_audit_chain_entries` (gauge)
- `TracingMiddleware` — OpenTelemetry spans for each operation
- `HealthCheck` → `/health` endpoint: DB status, audit integrity, Z3 working
- Structured logging (JSON) with request IDs

**Test Plan (3 test):**
1. `test_metrics_collection` — Prometheus format output
2. `test_tracing` — Spans created for commit/recall/verify
3. `test_health_check` — All components healthy

### Adım 5.3: Production Documentation (2 saat)
**Dosyalar:** `docs/` (YENİ/GÜNCELLEME)

**Detaylar:**
- `docs/index.md` — Overview, getting started, feature matrix
- `docs/architecture.md` — 7-layer diagram, data flow, component interaction
- `docs/memory-types.md` — 5 types, brain analogies, transition rules
- `docs/consolidation.md` — Sleep phases, examples, configuration
- `docs/verification.md` — Z3 invariants, audit trail, diff/rollback
- `docs/mcp-server.md` — MCP setup, tool reference, integration guides
- `docs/adapters.md` — mem0/Letta/Cognee integration guides
- `docs/benchmarks.md` — Benchmark results, comparison tables
- `docs/api-reference.md` — Full API documentation
- `docs/security.md` — Security considerations, data protection

### Adım 5.4: Security Hardening (1.5 saat)
**Dosyalar:** Various updates

**Detaylar:**
- Input validation: All public methods validate input types/sizes
- Resource limits: Max entries per type, max memory size, query rate limits
- Audit integrity: Periodic integrity check scheduler
- Encryption at rest: Optional SQLite encryption (sqlcipher)
- API key auth for MCP server
- Sanitization: All user inputs sanitized before KG insertion
- Audit: Log all failed verification attempts and integrity violations

**Test Plan (5 test):**
1. `test_input_validation` — Invalid inputs rejected
2. `test_resource_limits` — Max entries enforced
3. `test_audit_periodic_check` — Scheduled integrity verification
4. `test_mcp_auth` — Authenticated vs unauthenticated access
5. `test_sanitization` — Malicious inputs handled safely

### Adım 5.5: v1.0 Release (1 saat)
**Checklist:**
- [ ] 100+ test passing (Phase 1+2+3+4+5 combined)
- [ ] Coverage > 80%
- [ ] All 4 benchmarks run successfully
- [ ] MCP server tested with Claude Code + Cursor
- [ ] Docs complete (9 files)
- [ ] Security audit passed
- [ ] `pyproject.toml` version = "1.0.0"
- [ ] CHANGELOG.md complete
- [ ] Git tag v1.0.0
- [ ] PyPI upload
- [ ] npm publish (if SDK ready)
- [ ] GitHub release with changelog
- [ ] HN/Reddit launch posts

**Phase 5 Total: 8 test + benchmarks → Target: 30+ test**

---

## 📈 ROADMAP SUMMARY

### Test Progress
| Phase | Tests | Cumulative |
|-------|-------|------------|
| Phase 1 (complete) | 32/32 | 32 |
| Phase 2 (complete) | 15/15 | 47 |
| **Phase 3 (Belief Engine)** | 20+ | 67+ |
| **Phase 4 (MCP + Ecosystem)** | 15+ | 82+ |
| **Phase 5 (Production v1.0)** | 30+ | 112+ |
| **v1.0.0 Target** | — | **100+** |

### File Growth
| Phase | New Files | Updated Files | Cumulative Total |
|-------|-----------|---------------|------------------|
| Phase 1 | 8 | 3 | 8 |
| Phase 2 | 2 | 2 | 10 |
| Phase 3 | 3 (agm_engine, kg, sync) + test | 1 (stateplane) | 13 |
| Phase 4 | 5 (mcp_server, 3 adapters, ts_sdk) + test | 0 | 18 |
| Phase 5 | 5 (benchmarks, observability, docs×9, security) + test | many | 23+ |

### Key Milestones
- ✅ **v0.2.0a1**: Brain core + Verification (current)
- 🔜 **v0.3.0**: AGM Belief + Knowledge Graph + Multi-agent sync
- 🔜 **v0.4.0**: MCP Server + Adapters + TypeScript SDK
- 🔜 **v1.0.0**: Production-ready, benchmarked, documented
  - 100+ tests, >80% coverage
  - MCP server tested with Claude Code, Cursor
  - Adapters for mem0, Letta, Cognee
  - Security hardened
  - Full documentation (9 files)
  - PyPI + npm published

---

## ⚠️ RISKS & MITIGATION

| Risk | Impact | Mitigation |
|------|--------|------------|
| AGM formal verification too complex | Phase 3 delayed | Start with simplified entrenchment, add DP postulates incrementally |
| KG extraction from natural language | Phase 3 accuracy low | Start with manual entity/relation tags, NLP enhancement in v2.0 |
| MCP SDK compatibility issues | Phase 4 delayed | Test mcp SDK compatibility early in Phase 3 |
| TypeScript SDK type errors | Phase 4 SDK unreliable | Write tests first, isomorphic build tested on both Node + browser |
| Z3 solver performance at scale | Phase 5 benchmarks slow | Cache verification results, batch invariant checking |
| Audit trail size growth | Phase 5 storage bloat | Implement periodic archival + compressed snapshots |

---

## 🎯 POST-v1.0 FUTURE (v2.0+ Vision)

- **v2.0: Neuroplasticity** — Dynamic architecture evolution, self-modifying structure
- **v2.0: Neuromodulation** — Dopamine/Serotonin/Noradrenaline analog for adaptive learning rates
- **v2.0: Spatial Reasoning** — Cognitive maps with navigation, graph-based concept traversal
- **v2.0: Dream Engine** — REM-phase creative recombination with novel insight generation
- **Cloud Service** — Hosted Bilinc with multi-tenant support
- **Enterprise** — RBAC, SSO, compliance (SOC2, HIPAA)

---

*This roadmap is a living document. Updated after each phase completion.*
*Last updated: 2026-04-06 (Phase 2 complete)*
