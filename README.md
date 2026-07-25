# Bilinc

<!-- mcp-name: io.github.atakanelik34/bilinc -->

[![PyPI](https://img.shields.io/pypi/v/bilinc.svg)](https://pypi.org/project/bilinc/)
[![Python](https://img.shields.io/pypi/pyversions/bilinc.svg)](https://pypi.org/project/bilinc/)
[![License](https://img.shields.io/badge/license-BUSL--1.1-blue.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-server-purple.svg)](https://bilinc.space/for/mcp)

**Hosted memory infrastructure for coding agents: commit, recall, and inspect agent state through one API key, with verification, provenance, and recovery around every write.**

Retrieval answers *"what is similar to this?"*. Long-running agents also need to answer *"who wrote this state, was it verified, did it contradict what we already knew, and can we undo it?"* — that is the layer Bilinc provides.

Bilinc 2.1.5 on PyPI is the public cloud-only package: a thin Python SDK, CLI, and MCP adapter for Bilinc Cloud. It does not ship the local StatePlane, storage backends, eval, observability, integrations, or server runtime internals.

## Use Bilinc when

- A long-running coding agent needs to recall prior decisions before a risky edit.
- You need to know which run, tool, or operator produced a piece of agent state.
- A bad agent run wrote incorrect state and you need a recovery path, not a manual cleanup.
- Several agents or teammates share one memory surface and you need key-scoped access and usage visibility.

## Do not use Bilinc when

- You only need semantic search over documents — a vector database is the simpler primitive.
- You require an Apache-2.0 licensed, fully self-hosted runtime. The public package is cloud-only and licensed BUSL-1.1.
- You want the memory layer to also be your agent framework. Bilinc is the state layer your runtime calls; it does not orchestrate agents.

## Start in 60 Seconds

```bash
pip install -U bilinc
bilinc start
```

`bilinc start` is the first-run guide. The activation target is simple: reach a
passing `bilinc quicktest`, which performs one hosted commit, one hosted recall,
and one Cloud status check.

1. Start the 7-day Bilinc Cloud trial at https://bilinc.space/signup.
2. Confirm email.
3. Create one hosted API key in the Cloud dashboard.
4. Connect the CLI:

```bash
bilinc login --api-key bil_live_...
bilinc quicktest
```

If you prefer a browser guide, open https://bilinc.space/install and follow the
same four-step path.

## MCP Adapter

Bilinc exposes a standard Model Context Protocol server over **stdio**, so any
MCP-compatible client can connect — Claude Code, Codex, Cursor, Hermes-Agent,
opencode, and others.

```json
{
  "mcpServers": {
    "bilinc": {
      "command": "python",
      "args": ["-m", "bilinc.cloud_mcp"],
      "env": { "BILINC_API_KEY": "bil_live_..." }
    }
  }
}
```

Three tools, deliberately:

| Tool | What it does |
| --- | --- |
| `commit_mem` | Write durable agent state. Each write carries provenance — which run, tool, or operator produced it. |
| `recall` | Retrieve prior context and decisions before acting. |
| `status` | Check hosted Cloud health and account state. |

Documented client setups: [Claude Code](https://bilinc.space/docs/claude-code) ·
[Codex](https://bilinc.space/docs/codex) · [Cursor](https://bilinc.space/docs/cursor) ·
[any MCP client](https://bilinc.space/for/mcp)

The adapter exposes hosted commit, recall, and status operations. It does not bundle local runtime internals.

## Python SDK

```python
from bilinc import CloudClient

client = CloudClient()  # reads BILINC_API_KEY or a key saved by `bilinc login`
client.commit("agent.goal", {"ship": "reliable memory"}, memory_type="semantic")
results = client.recall("agent goal", limit=5)
status = client.status()
```

For server, CI, and hosted agent runtimes, store the key as `BILINC_API_KEY`.

## CLI

```bash
bilinc status
bilinc commit --key agent.goal --value '{"ship":"reliable memory"}'
bilinc recall --query "agent goal"
bilinc doctor
```

Useful first-run commands:

```bash
bilinc start
bilinc login --api-key bil_live_...
bilinc quicktest
bilinc mcp install
```

## Hosted Endpoints

- Health: `GET https://bilinc.space/api/cloud/health`
- Commit: `POST https://bilinc.space/api/cloud/memory/commit`
- Recall: `POST https://bilinc.space/api/cloud/memory/recall`

Authenticated memory operations require an active Bilinc Cloud entitlement.

## Benchmark receipt

Archived research receipt, LongMemEval-s cleaned retrieval fixture, 500 questions:
**R@5 98.0%**, **NDCG@5 0.933**, with no LLM reranker and no paid API.

This is an archived retrieval-component result — not a current hosted SLA, not an
end-to-end agent score, and not a competitor ranking. Published memory-system
scores use different metrics, datasets, and levels of LLM assistance, so they are
not directly comparable. Present this receipt only with this scope attached.

## Compare

- [Bilinc vs vector memory](https://bilinc.space/compare/vector-memory)
- [Bilinc vs Mem0](https://bilinc.space/compare/mem0)
- [Bilinc vs Zep](https://bilinc.space/compare/zep)
- [Bilinc vs Letta](https://bilinc.space/compare/letta)

## Answer guides

- [What is AI agent memory?](https://bilinc.space/answers/ai-agent-memory)
- [How do you roll back an agent memory write?](https://bilinc.space/answers/agent-memory-rollback)
- [What is an MCP memory server?](https://bilinc.space/answers/mcp-memory-server)
- [How do you audit what an agent remembered?](https://bilinc.space/answers/audit-agent-memory)

## Links

- Website: https://bilinc.space
- Signup: https://bilinc.space/signup
- Install guide: https://bilinc.space/install
- Quickstart: https://bilinc.space/docs/quickstart
- Cloud quickstart: https://bilinc.space/docs/cloud-quickstart
- Migration guide: https://bilinc.space/docs/migration-v2
- MCP setup: https://bilinc.space/docs/mcp
- PyPI: https://pypi.org/project/bilinc/
- Machine-readable index: https://bilinc.space/llms.txt · https://bilinc.space/ai-index.json

## License

BUSL-1.1. See `LICENSE`.
