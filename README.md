# Bilinc

**Verifiable state plane for autonomous agents**

![Bilinc OG](assets/bilinc-og.png)

[![PyPI](https://img.shields.io/pypi/v/bilinc)](https://pypi.org/project/bilinc/)
[![CI](https://github.com/atakanelik34/Bilinc/actions/workflows/ci.yml/badge.svg)](https://github.com/atakanelik34/Bilinc/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-BSL%201.1-yellow)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)

Bilinc manages truth state for long-running AI agents. Not just memory — verified, auditable, contradiction-resistant state.

```bash
pip install bilinc
```

---

## What Bilinc Does

Most agent memory systems are vector search with a wrapper. Bilinc is different:

- **Z3 formal verification** on every state commit (catches contradictions before they're stored)
- **AGM belief revision** (EXPAND/CONTRACT/REVISE) resolves conflicts without silent data loss
- **Hybrid decay model** (exponential → power-law) with LTP protection for important memories
- **Knowledge graph** with spreading activation for multi-hop retrieval
- **FTS5 + vector search** hybrid recall with RRF fusion
- **Blind spot detection** finds knowledge gaps before they matter
- **Rollback, snapshot, diff** — full state history recovery
- **MCP server** over stdio and authenticated HTTP

## Benchmark Results

| Benchmark | Score | Details |
|-----------|-------|---------|
| **LongMemEval** | **98.0%** | No LLM, fully local |
| **ConvoMem** | **98.0%** | 5 categories, real recall pipeline |
| **LoCoMo** | **90.3%** | Temporal + causal + multi-hop |

*Score progression: ConvoMem 17.5% → 98.0%, LoCoMo 9.1% → 90.3%*

## Quick Start

```python
from bilinc import StatePlane

# Create a state plane
sp = StatePlane(backend="sqlite", db_path="agent_state.db")

# Commit a belief (auto-verified)
sp.commit("user_preference", {
    "theme": "dark",
    "language": "python"
}, memory_type="semantic", importance=0.9)

# Recall with hybrid search (FTS5 + vector + KG)
results = sp.recall("user preference", limit=5)

# Check for contradictions
from bilinc import verify
report = verify.check_consistency(sp)

# Snapshot and rollback
snapshot = sp.snapshot()
sp.rollback(snapshot)
```

## Architecture

```
StatePlane (orchestrator)
├── WorkingMemory (8 slots, PFC-inspired)
├── SQLite Backend (persistent, FTS5, sqlite-vec)
├── AGM Belief Revision (EXPAND/CONTRACT/REVISE)
├── Knowledge Graph (entities + relations)
├── Verification Gate (Z3 SMT solver)
├── Audit Trail (full provenance)
└── MCP Server (stdio + HTTP)
```

## Memory Types (5-type taxonomy)

| Type | Decay | Use Case |
|------|-------|----------|
| Working | 24h half-life | Active context buffer |
| Episodic | 7 days | Conversation events |
| Procedural | 30 days | How-to knowledge |
| Semantic | 180 days | Facts and entities |
| Spatial | 90 days | Location/environment |

## Hybrid Recall (3-level)

```
Query → Level 1: FTS5 keyword (BM25 + porter stemming)
      → Level 2: Vector similarity (sqlite-vec + Ollama)
      → Level 3: KG spreading activation (HippoRAG-inspired)
      → RRF fusion → Decay-aware reranking → Results
```

## MCP Integration

Bilinc ships as an MCP server for Claude Code, Cursor, and any MCP-compatible agent:

```json
{
  "mcpServers": {
    "bilinc": {
      "command": "python",
      "args": ["-m", "bilinc.mcp_server.server_v2"],
      "env": {"BILINC_DB_PATH": "~/bilinc.db"}
    }
  }
}
```

**11 MCP tools:** commit_mem, recall, revise, forget, consolidate, contradictions, diff, snapshot, status, verify, query_graph

## Modules (v1.1.0)

| Module | Purpose |
|--------|---------|
| `core/decay.py` | Hybrid decay model + LTP protection |
| `core/blind_spots.py` | Knowledge gap detection |
| `core/consolidation.py` | 3-stage consolidation pipeline |
| `core/vector_search.py` | Hybrid search (FTS5 + vector + RRF) |
| `core/kg_retrieval.py` | KG spreading activation |
| `core/temporal.py` | Temporal reasoning (Allen's interval algebra) |
| `storage/sqlite.py` | SQLite + FTS5 + sqlite-vec |
| `storage/postgres.py` | PostgreSQL backend |

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

**217 tests passing, 0 failures.**

## What Makes Bilinc Different

| Feature | Bilinc | Mem0 | Zep | Letta |
|---------|--------|------|-----|-------|
| Z3 formal verification | ✅ | ❌ | ❌ | ❌ |
| AGM belief revision | ✅ | ❌ | ❌ | ❌ |
| Rollback/snapshot/diff | ✅ | ❌ | ❌ | ❌ |
| Audit trail | ✅ | ❌ | ❌ | ❌ |
| Hybrid decay (exp→power-law) | ✅ | ❌ | ❌ | ❌ |
| Blind spot detection | ✅ | ❌ | ❌ | ❌ |
| FTS5 + vector hybrid | ✅ | ❌ | ✅ | ❌ |
| Knowledge graph | ✅ | ❌ | ✅ | ❌ |
| MCP server | ✅ | ❌ | ❌ | ✅ |
| Fully local (no cloud) | ✅ | ❌ | ❌ | ✅ |

**Others store memories. Bilinc manages truth.**

## License\n\n[BSL 1.1](LICENSE)
