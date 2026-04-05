# SynapticAI: Verifiable State Plane for Autonomous Agents

> **"Remember less. Stay correct longer."**
> *Neuro-Symbolic Memory That Learns What to Forget.*

---

## Overview

SynapticAI is not a memory database. It is the **context control plane for long-running agents**.

### The Problem

Current agent memory is either:
- **Vector stores** (easy but drift/conflict handling weak)
- **Graph databases** (powerful but ops-heavy)
- **Session replay** (expensive and unbounded)

SynapticAI introduces **"Recall → Verify → Commit"** — memory is not storage, it is **state management with verification guarantees**.

### Why This Approach Wins

**Bigger context kills weak memory products, not strong memory companies.**

- 1M context windows commoditize "retrieve & inject"
- But they **don't solve**: verification, staleness, conflict resolution, cross-tool continuity
- SynapticAI solves what context windows can't: **verified, portable, budget-aware state**

---

## Architecture Layers

```
┌──────────────────────────────────────────────────────────┐
│              OBSERVABILITY LAYER                          │
│  Memory Debugger │ Provenance Graph │ "Why forget?"       │
├──────────────────────────────────────────────────────────┤
│             ADAPTIVE BUDGET LAYER                         │
│  ContextBudget RL │ Budget-Aware │ Compression            │
├──────────────────────────────────────────────────────────┤
│                 STATE PLANE (Core)                        │
│  Context-independent typed state storage                  │
├──────────────────────────────────────────────────────────┤
│           NEURO-SYMBOLIC MEMORY CORE                      │
│  System 1 (Neural/Fast) │ System 2 (Symbolic/Slow)        │
│  Episodic │ Procedural  │ Semantic │ Symbolic             │
├──────────────────────────────────────────────────────────┤
│           AGM BELIEF REVISION ENGINE                      │
│  EXPAND │ CONTRACT │ REVISE — formal guarantees           │
├──────────────────────────────────────────────────────────┤
│           LEARNABLE FORGETTING ENGINE                     │
│  Biological decay curves │ Importance-based retention     │
├──────────────────────────────────────────────────────────┤
│               VERIFICATION GATE                           │
│  Recall → VERIFY → COMMIT / REJECT                        │
└──────────────────────────────────────────────────────────┘
```

---

## Quick Start

```python
from synaptic_state import StatePlane

plane = StatePlane(
    neural="vector",
    symbolic="graph",
    backend="postgresql"
)

# Commit with verification
plane.commit(
    key="user_pref",
    value={"editor": "cursor", "tabs": 2},
    verify=True
)

# Recall with budget
memories = plane.recall(
    intent="editor config",
    budget_tokens=2048,
    strategy="rl_optimized"
)
```

---

## Research Foundation

Built on cutting-edge research:
- ContextBudget (2604.01664), ACC/CCS (2601.11653), D-MEM (2603.14597)
- StatePlane (2603.13644), Kumiho AGM (2603.17244), S3-Attention (2601.17702)

---

## License

MIT
