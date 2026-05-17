# Bilinc

**Verifiable state plane for autonomous agents.**

<p align="center">
  <img src="https://raw.githubusercontent.com/atakanelik34/Bilinc/main/assets/bilinc-architecture.png" alt="Bilinc architecture diagram showing the Bilinc State Plane connected to memory types, AGM belief revision, LangGraph checkpointing, MCP server integration, hybrid recall, SQLite/PostgreSQL storage, Z3 verification, and a Merkle audit trail." />
</p>

<p align="center">
  <a href="https://pypi.org/project/bilinc/"><img src="https://img.shields.io/pypi/v/bilinc?style=flat-square&logo=pypi&logoColor=white&color=0073b7" alt="PyPI"></a>
  <a href="https://pypi.org/project/bilinc/"><img src="https://img.shields.io/pepy/dt/bilinc?style=flat-square&logo=pypi&logoColor=white&color=0073b7&label=downloads" alt="All-time downloads"></a>
  <a href="https://github.com/atakanelik34/Bilinc/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/atakanelik34/Bilinc/ci.yml?branch=main&style=flat-square&logo=githubactions&logoColor=white&label=ci" alt="CI"></a>
  <a href="https://github.com/atakanelik34/Bilinc/tags"><img src="https://img.shields.io/github/v/tag/atakanelik34/Bilinc?sort=semver&style=flat-square&logo=github&label=tag" alt="GitHub tag"></a>
  <a href="https://pypi.org/project/bilinc/"><img src="https://img.shields.io/pypi/pyversions/bilinc?style=flat-square&logo=python&logoColor=white" alt="Python versions"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BSL%201.1-orange?style=flat-square" alt="License: BSL 1.1"></a>
  <a href="tests/"><img src="https://img.shields.io/badge/tests-247%20passing-brightgreen?style=flat-square&logo=pytest&logoColor=white" alt="Tests"></a>
  <a href="https://github.com/atakanelik34/Bilinc/stargazers"><img src="https://img.shields.io/github/stars/atakanelik34/Bilinc?style=flat-square&logo=github&color=yellow" alt="Stars"></a>
</p>

```bash
pip install bilinc
```

Most agent memory systems are a vector store with a wrapper. Bilinc is a **state plane**: every belief can be verified before it lands, logically revised when it conflicts, and audited so an agent can explain what changed and why.

**Others store memories. Bilinc manages truth.**

## Why Bilinc

Long-running agents fail in predictable ways:

- They store contradictions they never catch.
- They overwrite useful context with noisy recency.
- They cannot roll back when memory or tool state goes bad.

Bilinc gives agents a state layer with verification, belief revision, provenance, and rollback built in.

## Core capabilities

| Area | What Bilinc provides |
| --- | --- |
| Memory model | Working, episodic, procedural, semantic, and spatial memory with per-type decay curves |
| Recall | FTS5 BM25 + vector similarity + knowledge-graph/entity signals, fused with RRF |
| Evidence-aware recall | Opt-in recall replay, structured claim projection, read-only contradiction probes, named recall profiles, and conservative entity/backlink projection |
| Belief revision | AGM-style EXPAND / CONTRACT / REVISE for conflict-aware updates |
| Verification | Z3 SMT checks at the commit gate |
| Auditability | Merkle-chain provenance, snapshots, diffs, and rollback |
| Agent integration | MCP server, LangGraph checkpoint adapter, Claude Code / Cursor / VS Code / OpenClaw translation |
| Storage | SQLite by default, PostgreSQL optional |

## Quick start

```python
from bilinc import StatePlane
from bilinc.storage.sqlite import SQLiteBackend

backend = SQLiteBackend("agent_state.db")
sp = StatePlane(backend=backend, enable_verification=True, enable_audit=True)

# Commit a belief: verification and audit happen before write.
sp.commit_sync(
    "user_preference",
    {"theme": "dark", "language": "python"},
    memory_type="semantic",
    importance=0.9,
)

# Recall across FTS5, vector, and graph signals.
results = sp.recall_all_sync("user preference", limit=5)

# Snapshot, mutate, rollback.
snapshot_id = sp.snapshot_sync()
sp.commit_sync("user_preference", {"theme": "light"})
sp.rollback_sync(snapshot_id)
```

## CLI

```bash
bilinc --db ./agent.db commit --key USER_PREF --value '{"theme": "dark"}'
bilinc --db ./agent.db recall --key USER_PREF
bilinc --db ./agent.db forget --key USER_PREF
bilinc --db ./agent.db status

# Hermes integration
bilinc hermes bootstrap
bilinc hermes smoke
```

## MCP integration

Bilinc ships as an MCP server for Claude Code, Cursor, and any MCP-compatible agent:

```json
{
  "mcpServers": {
    "bilinc": {
      "command": "python",
      "args": ["-m", "bilinc.mcp_server.server_v2"],
      "env": { "BILINC_DB_PATH": "~/bilinc.db" }
    }
  }
}
```

MCP tools include: `commit_mem`, `recall`, `revise`, `forget`, `consolidate`, `contradictions`, `diff`, `snapshot`, `rollback`, `status`, `verify`, `query_graph`, `bilinc_recall_smart`, `bilinc_query_analysis`, `bilinc_event_segment`, `bilinc_summarize`, `bilinc_health`, `bilinc_benchmark`, `bilinc_export`, and `bilinc_import`.

## LangGraph checkpointing

Use Bilinc as a verified persistent checkpoint store for LangGraph agents:

```python
from langgraph.graph import StateGraph
from bilinc import StatePlane
from bilinc.storage.sqlite import SQLiteBackend
from bilinc.integrations.langgraph import LangGraphCheckpointer

sp = StatePlane(backend=SQLiteBackend("checkpoints.db"), enable_verification=True)
checkpointer = LangGraphCheckpointer(sp)

graph = StateGraph(...).compile(checkpointer=checkpointer)
```

Every checkpoint can flow through Bilinc's revision and verification pipeline, making long-running LangGraph state inspectable and rollback-capable.

## Architecture

```text
StatePlane
├── WorkingMemory          PFC-inspired active slots and eviction
├── AGM Engine             EXPAND / CONTRACT / REVISE
├── Dual-Process Arbiter   fast path + deliberate verification path
├── StateVerifier          Z3 SMT contradiction gate
├── AuditTrail             Merkle chain and provenance
├── KnowledgeGraph         entities, relations, spreading activation
├── Hybrid Recall          FTS5 → vector → KG → RRF fusion
├── ContextBudgetRL        adaptive token allocation by memory type
├── Storage                SQLite / PostgreSQL
└── MCP Server v2          stdio + authenticated HTTP
```

## Benchmarks

| Benchmark | Score | Notes |
| --- | ---: | --- |
| LongMemEval-s | 98.0% R@5 | Fresh 2026-05-17 full 500-question run, no LLM reranker / no paid API |
| ConvoMem | 98.0% | 5 categories, repository recall pipeline |
| LoCoMo | 90.3% | Temporal, causal, and multi-hop recall |

Benchmark receipts and public-safe competitive positioning live under `benchmarks/results/`, including the 2026-05-17 LongMemEval competitive report. These are benchmark records, not hosted-service claims; public comparisons must preserve metric scope because competitor scores mix retrieval R@5 and LLM-involved task accuracy.

## Comparison

| Feature | Bilinc | Mem0 | Zep | Letta |
| --- | :---: | :---: | :---: | :---: |
| Z3 formal verification | ✅ | ❌ | ❌ | ❌ |
| AGM belief revision | ✅ | ❌ | ❌ | ❌ |
| Cryptographic audit trail | ✅ | ❌ | ❌ | ❌ |
| Snapshot / diff / rollback | ✅ | ❌ | ❌ | ❌ |
| Blind spot detection | ✅ | ❌ | ❌ | ❌ |
| Hybrid decay | ✅ | ❌ | ❌ | ❌ |
| FTS5 + vector hybrid recall | ✅ | ❌ | ✅ | ❌ |
| Knowledge graph | ✅ | ❌ | ✅ | ❌ |
| LangGraph checkpoint adapter | ✅ | ❌ | ✅ | ❌ |
| MCP server | ✅ | ❌ | ❌ | ✅ |
| Fully local mode | ✅ | ❌ | ❌ | ✅ |

## Installation

```bash
# Core
pip install bilinc

# PostgreSQL backend
pip install "bilinc[postgres]"

# HTTP MCP server
pip install "bilinc[server]"

# Development
pip install -e ".[dev]"
pytest tests/ -v
```

## License

[BSL 1.1](LICENSE) — free for personal and research use. Commercial SaaS use is restricted until 2030, then Apache 2.0.
