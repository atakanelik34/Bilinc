# Bilinc

**Verifiable state plane for autonomous agents**

[![PyPI](https://img.shields.io/pypi/v/bilinc)](https://pypi.org/project/bilinc/)
[![CI](https://github.com/atakanelik34/Bilinc/actions/workflows/ci.yml/badge.svg)](https://github.com/atakanelik34/Bilinc/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)

*A trustworthy state layer for long-running AI agents.*

Bilinc helps agents keep state that is durable, reviewable, and safer to evolve over time. It combines persistence, verification, belief revision, rollback tooling, MCP access, and operator-facing health and metrics in a single Python package.

## What Bilinc Is

Bilinc is a **context control plane** for autonomous agents.

Most memory tools focus on storing and retrieving context. Bilinc is built for the harder problem: keeping agent state usable over time when beliefs change, contradictions appear, multiple tools touch the same memory, and operators need to understand what changed and why.

In practice, that means Bilinc provides:

- a `StatePlane` API for memory and state operations
- durable storage backends
- verification and audit-aware state handling
- snapshot, diff, and rollback workflows
- MCP access over stdio and authenticated HTTP
- health and Prometheus-style metrics

## The Problem Bilinc Solves

Long-running agents usually break down in familiar ways:

- they keep stale information too long
- they overwrite useful context without discipline
- they accumulate contradictions
- they expose “memory” without persistence, rollback, auth, or observability

That gap matters. A memory layer that works in a demo but cannot be trusted in a real system quickly becomes operational debt.

Bilinc exists to close that gap.

## Why Bilinc Is Different

Bilinc is not positioned as just another memory library.

It is designed as a **trustworthy state layer** for agents:

- **Verify before commit**
  State can pass through validation and verification logic instead of being blindly stored.
- **Belief revision, not only retrieval**
  Bilinc includes AGM-style belief revision machinery for changing or conflicting state.
- **Durable persistence**
  SQLite persistence is part of the normal workflow, not a side feature.
- **Recovery primitives**
  Snapshot, diff, and rollback exist for persistent state.
- **Operational MCP surface**
  HTTP MCP includes bearer auth, rate limiting, health, and metrics.
- **Operator visibility**
  Bilinc exposes deployment signals through `/health` and `/metrics`.

## Core Capabilities

- **StatePlane core**
  Unified API for commit, recall, forget, snapshot, diff, rollback, and component initialization.
- **Persistent storage**
  SQLite support today, PostgreSQL backend included and CI-validated.
- **Verification and audit**
  Z3-backed verification and audit-aware state reconstruction.
- **Belief revision**
  AGM-style revision workflows for conflicting or changing beliefs.
- **Knowledge graph**
  Semantic memory can be projected into a graph for traversal and contradiction analysis.
- **MCP server**
  12 MCP tools for memory and state operations.
- **HTTP deployment surface**
  Authenticated transport with rate limiting, health, and metrics.
- **Observability**
  In-process metrics plus Prometheus-compatible export.

## Support and Maturity Matrix

| Surface | Status | Notes |
|---|---|---|
| Core `StatePlane` API | Production-capable | Main package surface, covered by tests |
| SQLite persistence | Production-capable | Persistent CLI and backend support |
| MCP stdio transport | Supported | Trusted local process boundary, no request-level auth |
| MCP HTTP transport | Production-capable | Bearer auth, rate limiting, health, metrics |
| Snapshot / diff / rollback | Supported on persistent backends | Intended for durable state workflows |
| `/health` and `/metrics` | Production-capable | Operator-facing HTTP endpoints |
| Knowledge graph | Supported | Included in package and docs |
| AGM belief revision | Supported | Included in package and docs |
| PostgreSQL backend | CI-validated support | Backend integration job exists in CI |
| LangGraph adapter | Not currently a supported public surface | Do not treat as maintained product surface |
| Hosted service / multi-tenant platform | Planned | Not part of this repository today |

## Architecture Overview

Bilinc is organized as a layered agent-state system:

1. **Core state layer**
   `StatePlane` coordinates commits, recall, forgetting, rollback, and component initialization.
2. **Persistence layer**
   SQLite and PostgreSQL backends provide durable storage.
3. **Verification and audit**
   Verification and audit trail logic support correctness and replayable state history.
4. **Belief management**
   AGM-style revision supports controlled state updates under conflict.
5. **Knowledge graph**
   Semantic memory can be represented structurally and queried.
6. **Transport layer**
   MCP is exposed through stdio and HTTP.
7. **Operations layer**
   Health and metrics support deployment and monitoring.

## Install

Basic install:

```bash
pip install bilinc
```

Development install:

```bash
pip install -e '.[dev]'
```

PostgreSQL extras:

```bash
pip install -e '.[dev,postgres]'
```

Server-oriented extras:

```bash
pip install -e '.[server]'
```

Bilinc supports **Python 3.10+**.

## Install with an Agent

If you use an agentic coding assistant, you can let it install and start using Bilinc end-to-end.

Copy this prompt into your agent:

```text
Install and use Bilinc in this environment.

PyPI: https://pypi.org/project/bilinc/
GitHub: https://github.com/atakanelik34/Bilinc
Install command: pip install bilinc

Tasks:
1. Install the latest Bilinc release.
2. Verify that `from bilinc import StatePlane` works.
3. Initialize a local SQLite-backed Bilinc setup.
4. Run a minimal commit/recall smoke test.
5. Use Bilinc as the default state and memory layer for this workspace instead of ad hoc notes or temporary memory.
6. When state changes matter, use snapshot/diff/rollback.
7. Explain what you changed, what keys you stored, and the final working state.
```

Recommended verification steps:
- install the latest Bilinc release
- confirm `from bilinc import StatePlane` works
- create a local SQLite-backed state store
- run a minimal commit/recall smoke test
- show how Bilinc will be used for normal state operations in the workspace
- report any environment issues and how they were resolved

## Quick Start

### Python API

```python
from bilinc import StatePlane

plane = StatePlane()
plane.init()

result = plane.commit_sync(
    key="user.pref.editor",
    value={"name": "cursor", "theme": "dark"},
    memory_type="semantic",
    importance=0.8,
)

print(result.success)
print(len(plane.recall_all_sync()))
```

### With Durable Storage

```python
from bilinc import StatePlane
from bilinc.storage.sqlite import SQLiteBackend

backend = SQLiteBackend("./bilinc.db")
plane = StatePlane(backend=backend)
plane.init()

plane.commit_sync(
    key="team.policy",
    value={"deploy_window": "weekday"},
    memory_type="semantic",
)

entry = plane.working_memory.get("team.policy")
print(entry.value)
```

## Persistent CLI Usage

Bilinc ships with a CLI.

### Ephemeral mode

Without `--db`, the CLI runs in in-memory mode:

```bash
bilinc status
```

This mode is useful for quick inspection and local testing, but it is **not persistent across separate CLI invocations**.

### SQLite-backed persistent mode

```bash
bilinc --db ./bilinc.db commit --key team.owner --value alice
bilinc --db ./bilinc.db recall --key team.owner
bilinc --db ./bilinc.db forget --key team.owner
```

You can also provide the backend through an environment variable:

```bash
export BILINC_DB_URL=./bilinc.db
bilinc commit --key app.mode --value production
bilinc recall --key app.mode
```

## MCP Usage

Bilinc exposes an MCP surface for agent runtimes and tool ecosystems.

### Stdio transport

Use stdio when Bilinc runs as a trusted local process behind an MCP client.

```python
import asyncio
from bilinc import StatePlane
from bilinc.mcp_server.server_v2 import create_mcp_server_v2
from mcp.server.stdio import stdio_server

plane = StatePlane()
plane.init_agm()
plane.init_knowledge_graph()

server = create_mcp_server_v2(plane)

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

asyncio.run(main())
```

**Security note:** stdio is a **trusted local process boundary**. It is intentionally **unauthenticated at the request level**.

### HTTP transport

Use HTTP for production-facing deployments.

```python
from bilinc import StatePlane
from bilinc.mcp_server.server_v2 import create_mcp_http_app

plane = StatePlane()
plane.init_agm()
plane.init_knowledge_graph()

app = create_mcp_http_app(
    plane=plane,
    auth_token="replace-me",
    route_prefix="/mcp",
)
```

Run it with your ASGI server:

```

## Hermes Integration Readiness

Bilinc is already strong enough to plug into Hermes, but the last mile is clearer if we separate what is done from what is still polish.

### Already Done

- ✅ MCP server v2 with the core memory surface
- ✅ stdio transport compatibility for agent runtimes
- ✅ SQLite and PostgreSQL persistence backends
- ✅ rollback, diff, snapshot, verify, and contradiction tooling
- ✅ cross-tool memory translation for agent clients
- ✅ security and rate limiting support

### Still Worth Polishing

- ⏳ one-command Hermes bootstrap / installer
- ⏳ Hermes-specific auth and launcher docs
- ⏳ stricter canonical-vs-session memory priority rules
- ⏳ an end-to-end Hermes smoke test for commit / recall / revise / rollback
- ⏳ a short Hermes quickstart page for new users

This is the shortest honest version of the current state:

> **Bilinc is production-grade for MCP memory. Hermes-specific packaging is the final polish.**

### Hermes Quickstart (One Command)

```bash
pip install bilinc
bilinc hermes bootstrap --hermes-home ~/.hermes --db-path ~/bilinc.db
```

Expected result:

- `~/.hermes/bilinc_stdio_v2.py` launcher exists
- smoke checks pass for `commit/recall/revise/diff/rollback`
- `~/.hermes/bilinc.env` contains runtime defaults

### Done Definition (Public Hermes Pack)

- [x] One-command Hermes bootstrap command in Bilinc CLI
- [x] Standard server_v2-only launcher for Hermes
- [x] Hermes metadata contract (`source`, `canonical`, `priority`, `ttl`, `session_id`)
- [x] Prod-Strict auth policy documented (`stdio` trusted-local, HTTP token required)
- [x] E2E smoke test for `commit/recall/revise/diff/rollback`
- [x] Public Hermes integration docs + troubleshooting

## Phase Progress

Available MCP tools: (feat: complete Hermes public integration pack and prod-strict MCP policy)

HTTP behavior:

- `Authorization: Bearer <token>` is required by default
- missing token: `401`
- invalid token: `401`
- rate-limited client: `429`

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | 7-layer architecture, data flow, component interaction |
| [MCP Server](docs/mcp-server.md) | 12 tool reference, security, error handling |
| [Hermes Integration](docs/hermes-integration.md) | Bootstrap, auth modes, runtime matrix, troubleshooting |
| [Hermes Contract](docs/hermes-integration-contract.md) | Tool order, metadata standard, priority and TTL rules |
| [Security Guide](docs/security.md) | Input validation, resource limits, MCP auth, audit |
| [CHANGELOG](CHANGELOG.md) | Full version history |

Available MCP tools: (feat: complete Hermes public integration pack and prod-strict MCP policy)

- `commit_mem`
- `recall`
- `forget`
- `revise`
- `status`
- `verify`
- `consolidate`
- `snapshot`
- `diff`
- `rollback`
- `query_graph`
- `contradictions`

## Security Model

Bilinc has two deliberate trust boundaries.

### Stdio

- intended for trusted local process use
- no request-level auth
- appropriate when the MCP client and Bilinc run in the same trust domain

### HTTP

- intended as the production-facing transport
- bearer token auth enforced by default
- rate limiting enforced
- health and metrics available through the same deployment surface

Other security-relevant behavior:

- input validation for keys and values
- resource limits for memory and graph growth
- audit support when enabled
- constant-time token comparison for HTTP auth

## Observability, Health, and Metrics

Bilinc includes a real operator surface.

### Health

- `GET /health`
- reports both `liveness` and `readiness`
- uses explicit states:
  - `healthy`
  - `degraded`
  - `failed`

### Metrics

- `GET /metrics`
- Prometheus-compatible
- `bilinc_` metric prefix

Examples of tracked areas:

- commit / recall / forget operation totals and latencies
- snapshot / diff / rollback totals and latencies
- auth failures
- rate limit hits
- backend errors
- readiness/liveness gauges

In-process observability is also available through the Python API.

## Storage Backends

### SQLite

Recommended for:

- local durable usage
- embedded deployments
- single-node setups
- controlled production environments

What exists today:

- persistent CLI support
- schema version tracking
- integration coverage
- rollback, snapshot, and diff support for durable state flows

### PostgreSQL

Recommended for:

- teams that want a database-backed deployment path
- environments where SQLite is not the right operational fit

What exists today:

- backend implementation in the repo
- contract-level integration tests
- CI validation with a PostgreSQL service job

Practical note:

PostgreSQL support is real and tested, but it is still a narrower path than the SQLite experience and should be treated with normal production caution.

## Testing, CI, and Validation

Bilinc’s repository includes:

- Python test matrix
- SQLite persistence coverage
- PostgreSQL integration coverage in CI
- package build validation
- wheel and sdist installation validation
- CLI persistence smoke checks in CI
- HTTP auth/rate-limit coverage
- observability coverage

If you are evaluating Bilinc seriously, the CI pipeline is part of the product contract.

## Documentation Map

- `docs/mcp-server.md`
  MCP surface, transport notes, and tool reference
- `docs/security.md`
  auth, validation, limits, and deployment trust model
- `docs/observability.md`
  health model, readiness/liveness, and metrics
- `docs/runbook.md`
  operator guidance and deployment notes
- `docs/release.md`
  release and publish checklist
- `CHANGELOG.md`
  shipped changes and release history

## Development and Local Setup

Clone the repo and install development dependencies:

```bash
git clone git@github.com:atakanelik34/Bilinc.git
cd Bilinc
python -m pip install -e '.[dev]'
```

Run the full test suite:

```bash
PYTHONPATH=src pytest -q tests/
```

Build distributable artifacts:

```bash
python -m build
```

Run a local persistence smoke:

```bash
bilinc --db ./tmp.db commit --key smoke_key --value hello
bilinc --db ./tmp.db recall --key smoke_key
```

Run PostgreSQL integration tests locally if you have a database ready:

```bash
export BILINC_TEST_POSTGRES_DSN=postgresql://postgres:postgres@127.0.0.1:5432/bilinc_test
PYTHONPATH=src pytest -q tests/test_postgres_integration.py
```

## Roadmap

Near-term priorities:

- keep the shipped surface stable
- continue validating PostgreSQL deployments
- improve official integrations selectively
- tighten operator and release discipline further where needed

Possible future work:

- broader supported integrations
- hosted deployment model
- richer operator tooling
- stronger enterprise deployment paths

## License

[MIT](LICENSE)
