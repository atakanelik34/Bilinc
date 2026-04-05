# SynapticAI

## Verifiable State Plane for Autonomous Agents

[![PyPI](https://img.shields.io/pypi/v/synaptic-state)](https://pypi.org/project/synaptic-state/)
[![Tests](https://img.shields.io/badge/tests-18%20passed-green)](https://github.com/atakanelik34/SynapticAI)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9+-blue)](https://pypi.org/project/synaptic-state/)

> **"Remember less. Stay correct longer."**
> *Neuro-Symbolic Memory That Learns What to Forget.*

---

## What is SynapticAI?

SynapticAI is **not a memory database** — it is the **context control plane for long-running agents**.

While other memory systems simply "retrieve and inject" context into the model, SynapticAI implements **Recall → Verify → Commit**: every memory entry passes through a verification gate, gets checked against existing beliefs via formal AGM belief revision, and is only committed if it passes quality checks.

### The Problem

Current agent memory solutions fail because:
- **Vector stores** (Pinecone, Qdrant) — good retrieval, no conflict resolution, no staleness detection
- **Graph databases** (Zep/Graphiti) — powerful but ops-heavy, complex onboarding
- **Session replay** — expensive and unbounded (1M context = 1M tokens to parse)
- **BigTech bundled memory** (ChatGPT, Claude) — siloed, no cross-tool portability

### The SynapticAI Solution

**Bigger context kills weak memory products, not strong memory companies.**

SynapticAI solves what context windows can't:
- ✅ **Verification gate** — "Is this memory still accurate?" before commit
- ✅ **AGM Belief Revision** — formal conflict resolution with mathematical guarantees
- ✅ **State Plane** — context-independent typed state (separate from model prompt)
- ✅ **Budget-aware recall** — learned allocation across memory types
- ✅ **Learnable forgetting** — biological decay curves, not static TTLs
- ✅ **Cross-tool translation** — Claude Code ↔ Cursor ↔ OpenClaw ↔ VS Code via MCP

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│              OBSERVABILITY LAYER                          │
│  Memory Debugger │ Provenance Graph │ Drift Detection     │
├──────────────────────────────────────────────────────────┤
│             ADAPTIVE BUDGET LAYER                         │
│  ContextBudget RL │ Budget-Aware │ Compression            │
├──────────────────────────────────────────────────────────┤
│                 STATE PLANE (Core)                        │
│  Context-independent typed state storage                  │
│  Model prompt receives clean result vectors, not raw data │
├──────────────────────────────────────────────────────────┤
│           NEURO-SYMBOLIC MEMORY CORE                      │
│  System 1 (Neural/Fast) │ System 2 (Symbolic/Slow)        │
│  Episodic │ Procedural  │ Semantic │ Symbolic             │
├──────────────────────────────────────────────────────────┤
│           AGM BELIEF REVISION ENGINE                      │
│  EXPAND │ CONTRACT │ REVISE — formal guarantees           │
├──────────────────────────────────────────────────────────┤
│           LEARNABLE FORGETTING ENGINE                     │
│  Biological forgetting curves │ Importance-based retention│
├──────────────────────────────────────────────────────────┤
│               VERIFICATION GATE                           │
│  Recall → VERIFY (real-world check) → COMMIT / REJECT    │
└──────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Neuro-Symbolic Memory Core
- **System 1 (Neural/Fast):** Episodic + Procedural memory, sub-50ms retrieval via hybrid search
- **System 2 (Symbolic/Slow):** Semantic + Symbolic memory, formal reasoning via knowledge graph

### 2. AGM Belief Revision
- **EXPAND:** Add new information (may create inconsistency)
- **CONTRACT:** Remove information (maintain consistency)
- **REVISE:** Add new info + resolve conflicts (the key operation)

### 3. Verification Gate
- **Recall → Verify → Commit** pipeline
- Staleness detection (temporal + strength-based)
- Conflict detection against existing beliefs
- Confidence scoring with explainable rejections

### 4. Hybrid Retriever
- BM25 (term-frequency) + Vector similarity
- RRF (Reciprocal Rank Fusion) for combining methods
- Lightweight reranker with metadata boost
- Budget-aware allocation across memory types

### 5. ContextBudget RL
- Learned context allocation strategies
- Task-type specific budget distribution
- Epsilon-greedy exploration → PPO in Phase 2

### 6. Learnable Forgetting
- Biological decay curves (Ebbinghaus model)
- Importance-based retention
- Explainable: "Why was this forgotten?"

---

## Quick Start

### Install

```bash
pip install synaptic-state
```

### Basic Usage

```python
from synaptic_state import StatePlane
from synaptic_state.core.models import MemoryType

# Initialize
plane = StatePlane()

# Commit with verification
plane.commit(
    key="user_pref",
    value={"editor": "cursor", "tabs": 2},
    memory_type=MemoryType.SEMANTIC,
    verify=True,
)

# Recall with budget
result = plane.recall(
    intent="editor configuration",
    budget_tokens=2048,
    strategy="rl_optimized",
)

# Explainable forgetting
explanation = plane.explain_forgetting("old_pref")
```

### PostgreSQL Backend

```python
plane = StatePlane(
    backend="postgresql",
    dsn="postgresql://user:pass@localhost/synaptic",
)
```

### LangGraph Integration

```python
from synaptic_state.integrations.langgraph import LangGraphCheckpointer
from langgraph.graph import StateGraph

plane = StatePlane()
checkpointer = LangGraphCheckpointer(plane)
graph = builder.compile(checkpointer=checkpointer)
```

### MCP Server

```python
from synaptic_state.mcp_server.server import create_mcp_server
from synaptic_state import StatePlane

plane = StatePlane()
server = create_mcp_server(plane)
# Now available as MCP tools: commit, recall, forget, explain, status
```

### Cross-Tool Translation

```python
from synaptic_state.integrations.cross_tool import CrossToolTranslator, ToolFormat
from synaptic_state import StatePlane

translator = CrossToolTranslator(StatePlane())

# Import from Claude Code
translator.import_from_tool("CLAUDE.md", ToolFormat.CLAUDE_CODE)

# Export to Cursor
translator.export_to_tool(".cursor/memory.json", ToolFormat.CURSOR)

# Universal MCP format
mcp_json = translator.export_to_tool("", ToolFormat.MCP)
```

### CLI

```bash
synaptic commit --key my_pref --value '{"theme":"dark"}'
synaptic recall --intent "editor settings"
synaptic forget --key old_pref
synaptic explain --key my_pref
synaptic status
```

---

## Research Foundation

SynapticAI combines breakthroughs from multiple research papers:

| Paper | ArXiv | Contribution |
|-------|-------|--------------|
| ContextBudget | 2604.01664 | RL-based context allocation (1.6x gain) |
| ACC/CCS | 2601.11653 | Compressed Cognitive State, bounded drift |
| D-MEM | 2603.14597 | Reward-gated memory consolidation |
| StatePlane | 2603.13644 | Context-independent state storage |
| Kumiho AGM | 2603.17244 | Formal belief revision for agents |
| Oblivion | 2604.00131 | Biological forgetting curves |
| S3-Attention | 2601.17702 | GPU-memory efficient retrieval |
| HippoRAG | 2405.14831 | Neuro-inspired RAG |

---

## Roadmap

| Phase | Features |
|-------|----------|
| **v0.1.0** ✅ | MVP: StatePlane, AGM, Verification, Hybrid Retriever, ContextBudget RL, Learnable Forgetting, LangGraph, MCP, CLI, PyPI |
| **v0.2.0** | Full PPO policy training, SQLite backend, OpenClaw integration |
| **v0.3.0** | Multi-agent memory consensus, OT/CRDT resolution, Cross-tool sync |
| **v1.0.0** | Production-ready: enterprise security, observability dashboard, formal eval suite |

---

## Contributing

Contributions welcome! See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for guidelines.

## License

[MIT](LICENSE)

---

*SynapticAI: Memory is not storage. It is state.*
