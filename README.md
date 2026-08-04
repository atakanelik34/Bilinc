# Bilinc

<!-- mcp-name: io.github.atakanelik34/bilinc -->

[![PyPI](https://img.shields.io/pypi/v/bilinc.svg)](https://pypi.org/project/bilinc/)
[![Python](https://img.shields.io/pypi/pyversions/bilinc.svg)](https://pypi.org/project/bilinc/)
[![License](https://img.shields.io/badge/license-BUSL--1.1-blue.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-server-purple.svg)](https://bilinc.space/for/mcp)
<a href="https://pypi.org/project/bilinc/"><img src="assets/downloads-11k.png" alt="downloads 11k" width="128" height="39"></a>

**Hosted memory infrastructure for coding agents: commit, recall, and inspect agent state through one API key, with verification, provenance, and recovery around every write.**

Retrieval answers *"what is similar to this?"*. Long-running agents also need to answer *"who wrote this state, was it verified, did it contradict what we already knew, and can we undo it?"* — that is the layer Bilinc provides.

Bilinc 2.1.8 on PyPI is the public cloud-only package: a thin Python SDK, CLI, and MCP adapter for Bilinc Cloud. It does not ship the local StatePlane, storage backends, eval, observability, integrations, or server runtime internals.

> **Frozen regression receipt** — LongMemEval-s cleaned retrieval fixture, 500 questions: **Hit@5 98.0%**, **NDCG@5 0.913**, no LLM reranker, no paid API. This is an isolated retrieval guardrail, not a current hosted SLA, end-to-end agent score, or competitor ranking — see [Benchmark receipt](#benchmark-receipt) for the full scope and qualification.

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

Eight tools — the core memory lifecycle, and nothing else:

| Tool | What it does |
| --- | --- |
| `commit_mem` | Write durable agent state. Each write carries provenance — which run, tool, or operator produced it — and returns a version for optimistic concurrency. |
| `recall` | Retrieve prior context and decisions before acting. `profile` selects retrieval quality; smart retrieval is that argument, not a separate tool. |
| `revise` | Deliberately correct something already known. It never creates, so a correction stays distinguishable from an accidental overwrite. |
| `forget` | **Destructive.** Remove obsolete state from active recall. A reason is required and is audited; the deleted value is never returned. |
| `status` | Report the authenticated workspace, plan, capabilities, recall profiles, limits, and usage. Never billed. |
| `snapshot` | Checkpoint a project before risky work, or list existing checkpoints. |
| `diff` | Compare a checkpoint against another checkpoint or current state. Values are redacted by default. |
| `rollback` | **Destructive in execute mode.** Restore a checkpoint through a free preview plus an explicitly confirmed execute. |

Operator and debug tooling — health probes, benchmarks, export/import, workspace replay — stays
local-only, as do the epistemic read tools for claims, contradictions, and graph queries. The hosted
adapter does not bundle local runtime internals.

Documented client setups: [Claude Code](https://bilinc.space/docs/claude-code) ·
[Codex](https://bilinc.space/docs/codex) · [Cursor](https://bilinc.space/docs/cursor) ·
[any MCP client](https://bilinc.space/for/mcp)

## Python SDK

```python
from bilinc import CloudClient

client = CloudClient()  # reads BILINC_API_KEY or a key saved by `bilinc login`

# Write, and keep the version for optimistic concurrency.
written = client.commit("agent.goal", {"ship": "reliable memory"}, memory_type="semantic")
results = client.recall("agent goal", limit=5)

# Correct something you already know. Fails if it does not exist.
client.revise("agent.goal", {"ship": "verifiable memory"},
              reason="scope corrected", expected_version=written["entryVersion"])

# Checkpoint before risky work, then see what changed.
snapshot = client.create_snapshot(label="before-autonomous-run")["snapshot"]
client.diff(snapshot["id"])

# Drop obsolete state. A reason is required and is audited.
client.forget("agent.goal", reason="superseded by the planner service")

# Recover. Preview is free; execute is destructive and needs the token.
preview = client.rollback_preview(snapshot["id"], reason="undo bad agent run")
client.rollback(snapshot["id"], confirmation_token=preview["confirmationToken"],
                reason="undo bad agent run")

client.status()   # what can this key do?
client.health()   # is the service reachable?
```

For server, CI, and hosted agent runtimes, store the key as `BILINC_API_KEY`.

## CLI

```bash
bilinc status                 # authenticated plan, capabilities, limits, usage
bilinc health                 # public service health
bilinc commit --key agent.goal --value '{"ship":"reliable memory"}'
bilinc recall --query "agent goal"
bilinc revise --key agent.goal --value '{"ship":"verifiable memory"}' --reason "scope corrected"
bilinc snapshot create --label before-autonomous-run
bilinc snapshot list
bilinc diff --from-snapshot snap_...
bilinc forget --key agent.goal --reason "superseded by the planner service"
bilinc doctor
```

Rollback is two stages. Execute takes the token from the preview and never prompts interactively,
so it stays safe inside automation:

```bash
bilinc rollback preview --snapshot snap_... --reason "undo bad agent run"
bilinc rollback execute --snapshot snap_... --reason "undo bad agent run" \
  --confirmation-token <token-from-preview>
```

Useful first-run commands:

```bash
bilinc start
bilinc login --api-key bil_live_...
bilinc quicktest
bilinc mcp install
```

## Hosted Endpoints

| Endpoint | Notes |
| --- | --- |
| `GET /api/cloud/health` | Public service health. No key, no billing. |
| `GET /api/cloud/status` | Authenticated capabilities for one key. Never billed. |
| `POST /api/cloud/memory/commit` | Write. |
| `POST /api/cloud/memory/recall` | Read. |
| `POST /api/cloud/memory/revise` | Replace an existing memory. |
| `POST /api/cloud/memory/forget` | Destructive. Reason required. |
| `GET /api/cloud/memory/snapshots` | List checkpoints. Free. |
| `POST /api/cloud/memory/snapshots` | Create a checkpoint. |
| `POST /api/cloud/memory/diff` | Compare checkpoints. Free. |
| `POST /api/cloud/memory/rollback/preview` | Free. Mints a confirmation token. |
| `POST /api/cloud/memory/rollback` | Destructive. Requires that token. |

All hosted endpoints share `https://bilinc.space`. Authenticated memory operations require an
active Bilinc Cloud entitlement.

Send an `Idempotency-Key` header on any write you might retry: the same key with the same payload
replays the original result and is billed once, and the same key with a different payload is
refused with `409 idempotency_conflict`.

## Benchmark receipt

Frozen regression receipt, LongMemEval-s cleaned retrieval fixture, 500 questions:
**Hit@5 98.0%**, **NDCG@5 0.913**, with no LLM reranker and no paid API.

This is a frozen isolated retrieval guardrail — not a current hosted SLA, not an
end-to-end agent score, and not a competitor ranking. Published memory-system
scores use different metrics, datasets, and levels of LLM assistance, so they are
not directly comparable. Present this receipt only with this isolated scope attached.

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
