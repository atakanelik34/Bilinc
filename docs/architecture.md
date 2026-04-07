# Architecture

Bilinc is a **Verifiable State Plane** for autonomous AI agents. Unlike traditional memory systems that "dump" context, Bilinc implements a brain-inspired, neuro-symbolic pipeline where every memory is verified, consolidated, and subject to formal belief revision.

## 7-Layer Architecture

```
┌──────────────────────────────────────────────────────────┐
│  LAYER 7: MCP + ECOSYSTEM                               │
│  12 Tools | Claude Code, Cursor, OpenClaw Integration    │
├──────────────────────────────────────────────────────────┤
│  LAYER 6: OBSERVABILITY & SECURITY                      │
│  MetricsCollector | HealthCheck | InputValidator         │
├──────────────────────────────────────────────────────────┤
│  LAYER 5: BELIEF ENGINE                                 │
│  AGM Postulates | Darwiche-Pearl (DP1-DP4)              │
│  Knowledge Graph | Multi-Agent Sync | Consensus          │
├──────────────────────────────────────────────────────────┤
│  LAYER 4: VERIFICATION GATE                             │
│  Recall → Verify (Z3 SMT) → Commit / Reject             │
│  Merkle Audit Trail | State Diff | Rollback              │
├──────────────────────────────────────────────────────────┤
│  LAYER 3: ADAPTIVE BUDGET                               │
│  ContextBudget RL | Learnable Forgetting                │
│  Ebbinghaus Decay Curves | Importance Weighting          │
├──────────────────────────────────────────────────────────┤
│  LAYER 2: STATE PLANE (Core)                            │
│  Context-Independent Typed Storage                      │
│  5 Memory Types | Working Memory (8 slots)               │
├──────────────────────────────────────────────────────────┤
│  LAYER 1: NEURO-SYMBOLIC CORE                           │
│  System 1 (Neural/Fast) | System 2 (Symbolic/Slow)      │
│  SQLite/PostgreSQL Backend | Async/Sync API              │
└──────────────────────────────────────────────────────────┘
```

## Data Flow: Recall → Verify → Commit

```
Agent Action
    │
    ▼
┌──────────────┐
│ Commit/Input │
└──────┬───────┘
       │
    ┌──▼──────────────────┐
    │ Input Validation     │  ← Security Layer
    │ (Key Pattern, XSS)   │
    └──────┬──────────────┘
           │
    ┌──────▼──────────────────┐
    │ Resource Limit Check     │  ← Max entries, Rate limiting
    └──────┬──────────────────┘
           │
    ┌──────▼──────────────────┐
    │ AGM Belief Revision      │  ← Conflict detection & resolution
    │ (Expand/Contract/Revise) │     Entrenchment ordering
    └──────┬──────────────────┘
           │
    ┌──────▼──────────────────┐
    │ Verification Gate        │  ← Z3 SMT invariants
    │ (Valid/Invalid/Reject)   │     Confidence scoring
    └──────┬──────────────────┘
           │
    ┌──────▼──────────────────┐
    │ State Plane Storage      │  ← Working Memory → Long-term
    │ (Typed & Verified)       │     Consolidation (sleep cycle)
    └──────┬──────────────────┘
           │
    ┌──────▼──────────────────┐
    │ Knowledge Graph          │  ← Auto-extraction from semantic
    │ (NetworkX-based)         │     Contradiction detection
    └──────┬──────────────────┘
           │
    ┌──────▼──────────────────┐
    │ Observability            │  ← Prometheus metrics, Health check
    │ (Metrics, Gauges)        │     Latency histograms
    └─────────────────────────┘
```

## Key Components

### LAYER 1: Neuro-Symbolic Core

The foundation. System 1 (Neural) handles fast, episodic memory with sub-50ms retrieval. System 2 (Symbolic) handles slow, semantic reasoning with formal verification via Z3.

- **`StatePlane`**: Context-independent typed storage. The central orchestrator.
- **`WorkingMemory`**: 8-slot LRU buffer for active context.
- **Backends**: SQLite (default) and PostgreSQL for persistent storage.

### LAYER 3: Adaptive Budget

Learnable context allocation across memory types, inspired by ContextBudget RL (arXiv:2604.01664). The system learns which memory types to prioritize based on task requirements and importance distibution.

### LAYER 4: Verification Gate

Every memory passes through a verification gate before being committed. Z3 SMT solver checks formal invariants (temporal consistency, uniqueness, type safety). A Merkle audit trail ensures cryptographic integrity of the entire belief history.

### LAYER 5: Belief Engine

The AGM (Alchourrón-Gärdenfors-Makinson) belief revision system implements formal operations:

- **EXPAND**: Add information (may create conflicts)
- **CONTRACT**: Remove information (maintain closure)
- **REVISE**: Add + resolve conflicts (the core operation)

With Darwiche & Pearl iterated revision postulates (DP1-DP4), Knowledge Graph (NetworkX), and Multi-Agent Belief Sync with consensus mechanism.

### LAYER 6: Observability

Prometheus-compatible metrics, health checks, and latency tracing for production monitoring.

### LAYER 7: MCP Ecosystem

12 MCP (Model Context Protocol) tools for cross-tool memory sharing between Claude Code, Cursor, OpenClaw, and any MCP-compatible agent.

## Research Foundation

| Paper | ArXiv | Contribution |
|-------|-------|--------------|
| ContextBudget | 2604.01664 | RL context allocation (1.6x gain) |
| ACC/CCS | 2601.11653 | Compressed Cognitive State |
| Kumiho AGM | 2603.17244 | Formal belief revision |
| Oblivion | 2604.00131 | Biological forgetting curves |
| StatePlane | 2603.13644 | Context-independent storage |
| SCAT | 2604.03201 | Verifiable action in agents |
| Reflective Context | 2604.0389 | Learnable forgetting |
