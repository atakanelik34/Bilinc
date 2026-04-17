# Bilinc

**Verifiable state plane for autonomous agents**

<p align="center">
  <img src="assets/bilinc-og.png" alt="Bilinc" />
</p>

<p align="center">
  <a href="https://pypi.org/project/bilinc/"><img src="https://img.shields.io/pypi/v/bilinc?style=flat-square&logo=pypi&logoColor=white&color=0073b7" alt="PyPI"></a>
  <a href="https://pypi.org/project/bilinc/"><img src="https://img.shields.io/pypi/dm/bilinc?style=flat-square&logo=pypi&logoColor=white&color=0073b7&label=downloads%2Fmo" alt="Downloads"></a>
  <a href="https://github.com/ReARCLabs/Bilinc/actions/workflows/ci.yml"><img src="https://github.com/ReARCLabs/Bilinc/actions/workflows/ci.yml/badge.svg?style=flat-square" alt="CI"></a>
  <a href="https://pypi.org/project/bilinc/"><img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BSL%201.1-orange?style=flat-square" alt="License: BSL 1.1"></a>
  <a href="tests/"><img src="https://img.shields.io/badge/tests-245%20passing-brightgreen?style=flat-square&logo=pytest&logoColor=white" alt="Tests"></a>
  <a href="https://github.com/ReARCLabs/Bilinc/stargazers"><img src="https://img.shields.io/github/stars/ReARCLabs/Bilinc?style=flat-square&logo=github&color=yellow" alt="Stars"></a>
</p>

```bash
pip install bilinc
```

---

Most agent memory systems are a vector store with a wrapper. Bilinc is a **state plane**: every belief is formally verified before it's stored, logically revised when it conflicts, and cryptographically audited so you can always trace what changed and why.

---

## Why Bilinc

Long-running agents fail in predictable ways: they store contradictions they never catch, overwrite useful context with garbage, and have no way to roll back when something goes wrong.

Bilinc fixes all three:

- **Contradiction-resistant** — Z3 SMT solver checks every write before it lands. Contradictions are caught at commit time, not runtime.
- **Logical revision** — AGM belief revision (EXPAND / CONTRACT / REVISE) resolves conflicts without silent data loss or blind overwrites.
- **Full state history** — snapshot, diff, and rollback let any agent recover from any state.

---

## Features

**Storage & Retrieval**
- 5 brain-inspired memory types (Working, Episodic, Procedural, Semantic, Spatial) with per-type decay curves
- Hybrid recall: FTS5 keyword (BM25) + vector similarity (sqlite-vec) + KG spreading activation, fused via RRF
- Adaptive context budget allocation (ContextBudget RL) across memory types

**Verification & Integrity**
- Z3 SMT formal verification on every commit
- AGM belief revision engine — logical EXPAND / CONTRACT / REVISE
- Cryptographic audit trail (Merkle chain) with full provenance
- Blind spot detection — finds knowledge gaps before they matter

**Infrastructure**
- SQLite (default, zero-dep) and PostgreSQL backends
- MCP server v2 — 20 tools over stdio or authenticated HTTP
- Phase 7 scheduler + background jobs (consolidation, decay, KG maintenance, entity backlog, health report)
- Phase 8 advanced MCP tools (smart recall, query analysis, event segment, summarize, health, benchmark, export/import)
- LangGraph checkpoint adapter (drop-in `BaseCheckpointSaver`)
- Cross-tool memory translation: Claude Code ↔ Cursor ↔ VS Code ↔ OpenClaw
- Prometheus-compatible metrics, health checks, latency tracing
- Rate limiter, input validation, path traversal protection, MCP auth

---

## Quick Start

```python
from bilinc import StatePlane
from bilinc.storage.sqlite import SQLiteBackend

backend = SQLiteBackend("agent_state.db")
sp = StatePlane(backend=backend, enable_verification=True, enable_audit=True)

# Commit a belief — Z3-verified before write
sp.commit_sync("user_preference", {
    "theme": "dark",
    "language": "python"
}, memory_type="semantic", importance=0.9)

# Hybrid recall (FTS5 + vector + KG)
results = sp.recall_all_sync("user preference", limit=5)

# Snapshot → mutate → rollback
snap = sp.snapshot_sync()
sp.commit_sync("user_preference", {"theme": "light"})
sp.rollback_sync(snap)

# Contradiction check
from bilinc.core.verifier import StateVerifier
report = StateVerifier().check(sp)
```

---

## CLI

```bash
# Persist state to SQLite
bilinc --db ./agent.db commit --key USER_PREF --value '{"theme": "dark"}'
bilinc --db ./agent.db recall --key USER_PREF
bilinc --db ./agent.db forget --key USER_PREF
bilinc --db ./agent.db status

# Hermes integration
bilinc hermes bootstrap
bilinc hermes smoke
```

---

## MCP Integration

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

**20 MCP tools:** `commit_mem` · `recall` · `revise` · `forget` · `consolidate` · `contradictions` · `diff` · `snapshot` · `rollback` · `status` · `verify` · `query_graph` · `bilinc_recall_smart` · `bilinc_query_analysis` · `bilinc_event_segment` · `bilinc_summarize` · `bilinc_health` · `bilinc_benchmark` · `bilinc_export` · `bilinc_import`

---

## LangGraph Integration

Use Bilinc as a verified, persistent checkpoint store for LangGraph agents:

```python
from langgraph.graph import StateGraph
from bilinc import StatePlane
from bilinc.storage.sqlite import SQLiteBackend
from bilinc.integrations.langgraph import LangGraphCheckpointer

sp = StatePlane(backend=SQLiteBackend("checkpoints.db"), enable_verification=True)
checkpointer = LangGraphCheckpointer(sp)

builder = StateGraph(...)
graph = builder.compile(checkpointer=checkpointer)
```

Every checkpoint flows through Bilinc's AGM revision and Z3 verification pipeline — LangGraph state is contradiction-resistant by default.

---

## Benchmark Results

| Benchmark | Score | Notes |
|-----------|-------|-------|
| **LongMemEval** | **98.0%** | Fully local, no LLM |
| **ConvoMem** | **98.0%** | 5 categories, real recall pipeline |
| **LoCoMo** | **90.3%** | Temporal · causal · multi-hop |

*ConvoMem progression: 17.5% → 98.0%. LoCoMo: 9.1% → 90.3%*

---

## How Bilinc Compares

| Feature | Bilinc | Mem0 | Zep | Letta |
|---------|:------:|:----:|:---:|:-----:|
| Z3 formal verification | ✅ | ❌ | ❌ | ❌ |
| AGM belief revision | ✅ | ❌ | ❌ | ❌ |
| Cryptographic audit trail | ✅ | ❌ | ❌ | ❌ |
| Snapshot / diff / rollback | ✅ | ❌ | ❌ | ❌ |
| Blind spot detection | ✅ | ❌ | ❌ | ❌ |
| Hybrid decay (exp → power-law) | ✅ | ❌ | ❌ | ❌ |
| FTS5 + vector hybrid recall | ✅ | ❌ | ✅ | ❌ |
| Knowledge graph | ✅ | ❌ | ✅ | ❌ |
| LangGraph checkpoint adapter | ✅ | ❌ | ✅ | ❌ |
| MCP server | ✅ | ❌ | ❌ | ✅ |
| Fully local (no cloud required) | ✅ | ❌ | ❌ | ✅ |

**Others store memories. Bilinc manages truth.**

---

## Architecture

```
StatePlane (orchestrator)
├── WorkingMemory          8 slots, PFC-inspired eviction
├── AGM Engine             EXPAND / CONTRACT / REVISE
├── Dual-Process Arbiter   System 1 (fast) + System 2 (deliberate)
├── StateVerifier          Z3 SMT — contradiction gate
├── AuditTrail             Merkle chain, full provenance
├── KnowledgeGraph         Entities + relations, spreading activation
├── Hybrid Recall          FTS5 → vector → KG → RRF fusion
├── ContextBudgetRL        Adaptive token allocation by memory type
├── Storage                SQLite (FTS5, sqlite-vec) · PostgreSQL
└── MCP Server v2          stdio + authenticated HTTP, 20 tools
```

---

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

---

## License

[BSL 1.1](LICENSE) — free for personal and research use. Commercial SaaS use restricted until 2030, then Apache 2.0.
