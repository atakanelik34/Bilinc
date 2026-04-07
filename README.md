# Bilinc

## Verifiable State Plane for Autonomous Agents

[![PyPI](https://img.shields.io/pypi/v/bilinc)](https://pypi.org/project/bilinc/)
[![Tests](https://img.shields.io/badge/tests-124%20passed-brightgreen)](https://github.com/atakanelik34/Bilinc/actions)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)

> **Remember less. Stay correct longer.**
> *Neuro-Symbolic Memory That Learns What to Forget.*

---

## What is Bilinc?

Bilinc is the **context control plane for long-running AI agents**.

While other memory systems simply "retrieve and inject" context into models, Bilinc implements **Recall → Verify → Commit**: every memory passes through a verification gate, gets checked against existing beliefs via formal AGM belief revision, and is committed only if it passes quality checks.

### The Problem

| Memory System | Strength | Fatal Flaw |
|--------------|----------|------------|
| Vector DBs (Pinecone, Qdrant) | Fast retrieval | No conflict resolution, no staleness detection |
| Graph DBs (Zep/Graphiti) | Structured knowledge | Ops-heavy, complex onboarding |
| Session replay | Simple | Unbounded, expensive (1M tokens to parse) |
| BigTech bundled (ChatGPT, Claude) | Convenient | Siloed, no cross-tool portability |

### The Bilinc Solution

**Bigger context kills weak memory products, not strong memory companies.**

- ✅ **AGM Belief Revision** — Expand, Contract, Revise with formal guarantees + Darwiche & Pearl iterated revision
- ✅ **Knowledge Graph** — NetworkX-backed entity/relation extraction from semantic memory
- ✅ **Multi-Agent Belief Sync** — Push/Pull/Merge with consensus, vector clocks, divergence detection
- ✅ **Verification Gate** — Z3 SMT invariant checking + Merkle audit trail
- ✅ **Budget-Aware Recall** — Learned allocation across 5 memory types (ContextBudget RL)
- ✅ **Learnable Forgetting** — Biological decay curves (Ebbinghaus), not static TTLs
- ✅ **MCP Server** — 12 tools for Claude Code, Cursor, OpenClaw, any MCP client
- ✅ **Cross-Tool Translation** — Claude Code ↔ Cursor ↔ VS Code via MCP

---

## Architecture

```
┌────────────────────────────────────────────┐
│          MCP SERVER (12 tools)              │
│  commit_mem │ recall │ revise │ query_graph  │
├────────────────────────────────────────────┤
│       MULTI-AGENT BELIEF SYNC               │
│  Push/Pull/Merge │ Consensus │ Vector Clocks│
├────────────────────────────────────────────┤
│         KNOWLEDGE GRAPH (NetworkX)          │
│  Entity extraction │ Contradiction detection│
├────────────────────────────────────────────┤
│      AGM BELIEF REVISION ENGINE             │
│  EXPAND │ CONTRACT │ REVISE │ DP1-DP4       │
├────────────────────────────────────────────┤
│             STATE PLANE (Core)              │
│  5 Memory Types │ SQLite/PostgreSQL backend  │
├────────────────────────────────────────────┤
│     NEURO-SYMBOLIC MEMORY CORE              │
│  System 1 (Neural) │ System 2 (Symbolic)     │
├────────────────────────────────────────────┤
│         VERIFICATION GATE                   │
│  Z3 SMT invariants │ Merkle audit chain      │
└────────────────────────────────────────────┘
```

---

## Quick Start

### Install

```bash
pip install bilinc
```

### Basic Usage

```python
from bilinc import StatePlane
from bilinc.core.models import MemoryType

# Initialize with Phase 3 components
plane = StatePlane()
plane.init_agm()
plane.init_knowledge_graph()
plane.init_belief_sync()

# Commit with automatic AGM revision
result = plane.commit_with_agm(
    key="user_pref",
    value={"editor": "cursor", "theme": "dark"},
    memory_type="semantic",
    importance=0.8,
)
print(f"Success: {result.success}, Conflicts: {result.conflicts_resolved}")

# Revise a belief (with conflict resolution)
plane.commit_with_agm("user_pref", {"editor": "zed", "theme": "monokai"}, importance=0.9)

# Query the knowledge graph
graph = plane.query_graph("user_pref", max_depth=2)

# Check for contradictions
contradictions = plane.get_contradictions()
```

### MCP Server (Claude Code, Cursor, OpenClaw)

```python
from bilinc.mcp_server.server_v2 import create_mcp_server_v2
from bilinc import StatePlane

plane = StatePlane()
plane.init_agm()
plane.init_knowledge_graph()

server = create_mcp_server_v2(plane)
# 12 tools available: commit_mem, recall, forget, revise, status,
# verify, consolidate, snapshot, diff, rollback, query_graph, contradictions

# Run with stdio transport (Claude Code compatible)
import asyncio
from mcp.server.stdio import stdio_server

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

asyncio.run(main())
```

### Sync Across Agents

```python
from bilinc.core.belief_sync import BeliefSyncEngine

sync = plane.belief_sync
sync.init_sync("agent_alpha", reliability=0.9)
sync.init_sync("agent_beta", reliability=0.7)

# Alpha pushes beliefs
sync.push_beliefs("agent_alpha", [your_entries])

# Beta pulls updates
sync.pull_updates("agent_beta")

# Or full bidirectional merge
sync.merge_sync("agent_alpha", "agent_beta")
```

---

## Phase Progress

| Phase | Version | Components | Tests |
|-------|---------|------------|-------|
| **Phase 1: Brain Core** | v0.2.0 | 5 Memory Types, SQLite, Working Memory, Consolidation, System 1/2, Confidence, Forgetting | 32 |
| **Phase 2: Verification** | v0.2.0 | Z3 SMT Verifier, Merkle Audit, State Diff/Rollback | 15 |
| **Phase 3: Belief Engine** | — | AGM + DP Postulates, Knowledge Graph, Multi-Agent Sync, StatePlane Integration | 58 |
| **Phase 4: MCP + Ecosystem** | v0.4.0a1 | MCP Server v2 (12 tools), Rate Limiter | 16 |
| **Phase 5: Production** | — | Security Hardening, Observability, Benchmarks, Docs | 13 |
| **Total** | | | **124 passing** |

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | 7-layer architecture, data flow, component interaction |
| [MCP Server](docs/mcp-server.md) | 12 tool reference, security, error handling |
| [Security Guide](docs/security.md) | Input validation, resource limits, MCP auth, audit |
| [CHANGELOG](CHANGELOG.md) | Full version history |

---

## Research Foundation

Bilinc combines breakthroughs from multiple research papers:

| Paper | ArXiv | Contribution |
|-------|-------|--------------|
| ContextBudget | 2604.01664 | RL context allocation (1.6x gain) |
| ACC/CCS | 2601.11653 | Compressed Cognitive State |
| Kumiho AGM | 2603.17244 | Formal belief revision for agents |
| Oblivion | 2604.00131 | Biological forgetting curves |
| StatePlane | 2603.13644 | Context-independent state storage |
| SCAT | 2604.03201 | Verifiable action in agentic AI |
| Reflective Context | 2604.03189 | Learnable forgetting |

---

## Contributing

Contributions welcome! Key areas:
- Phase 5: Production v1.0 — benchmarks, observability, security hardening
- SQLite/PostgreSQL persistent storage layer
- Real mem0ai/Letta/Cognee adapters

See `research/phase4-detail-plan.md` for the roadmap.

## License

[MIT](LICENSE)

---

*Bilinc — Memory is not storage. It is state.*
