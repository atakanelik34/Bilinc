<!-- mcp-name: io.github.atakanelik34/bilinc -->

<p align="center">
  <a href="https://bilinc.space"><img src="https://raw.githubusercontent.com/ReARCLabs/bilinc-python/9774f8a97fb16b16cea10b974e9179e6f41df826/docs/assets/readme-hero.jpg" alt="Bilinc: memory you can look back through. Hosted memory for AI agents." width="100%"></a>
</p>

# Bilinc

[![PyPI](https://img.shields.io/pypi/v/bilinc.svg)](https://pypi.org/project/bilinc/)
[![Python](https://img.shields.io/pypi/pyversions/bilinc.svg)](https://pypi.org/project/bilinc/)
[![License](https://img.shields.io/badge/license-BUSL--1.1-blue.svg)](https://github.com/ReARCLabs/bilinc-python/blob/main/LICENSE)
[![MCP](https://img.shields.io/badge/MCP-server-purple.svg)](https://bilinc.space/for/mcp)
<a href="https://pepy.tech/project/bilinc"><img src="https://static.pepy.tech/badge/bilinc" alt="Downloads"></a>

**Hosted memory for AI agents.** Save what your agents learn, recall it before they act, see who wrote each memory and what changed, and roll back when a run goes wrong.

The `bilinc` package on PyPI is the Python SDK, the `bilinc` CLI and the stdio MCP adapter for [Bilinc Cloud](https://bilinc.space). Its source is [ReARCLabs/bilinc-python](https://github.com/ReARCLabs/bilinc-python); the hosted service is not part of the package.

## Start in 60 seconds

**Claude, ChatGPT or Codex, without Python.** In Claude, open **Customize → Connectors → Add custom connector**, name it Bilinc and paste `https://mcp.bilinc.space/mcp`. Sign in and choose read-only or read and write. In Claude Code:

```bash
claude mcp add --transport http --scope user bilinc https://mcp.bilinc.space/mcp
```

The same address works in ChatGPT and Codex: [remote MCP guide](https://bilinc.space/docs/remote-mcp).

**Python, the CLI or any MCP client.**

```bash
pip install -U bilinc
bilinc login        # browser sign-in, free, no card required
bilinc quicktest    # one hosted commit, one recall and a status check
```

`bilinc login` saves an API key for this computer with owner-only permissions; the key never appears in a URL or your terminal. Without a browser, use `bilinc login --device`. For CI and scripts, set `BILINC_API_KEY`.

## Where Bilinc sits

<p align="center"><img src="https://raw.githubusercontent.com/ReARCLabs/bilinc-python/9774f8a97fb16b16cea10b974e9179e6f41df826/docs/assets/where-bilinc-sits.png" alt="Claude, ChatGPT, Codex, Cursor and Python agents connect with a sign-in or an API key to one Bilinc Cloud workspace. Operations: commit, recall, revise, forget; snapshot, diff, rollback; list, history, export, confirm. Every memory keeps who wrote it, every version, why it changed and when it was last confirmed." width="100%"></p>

Every write records where it came from and returns a version you can pass back, so a change is refused if the memory moved since you read it. Forget requires a reason and revise accepts one. In the remote connector, recall shows when each memory was last confirmed and marks entries past their review window as possibly outdated; nothing is hidden or deleted by that check.

## Similar is not the same as current

<p align="center"><img src="https://raw.githubusercontent.com/ReARCLabs/bilinc-python/9774f8a97fb16b16cea10b974e9179e6f41df826/docs/assets/similar-vs-current.png" alt="Search over saved text returns three similar answers to 'where do we deploy?' and cannot say which is current. Bilinc recall returns the key deploy.target with value production, who wrote it, why and when it was confirmed, with its history from v1 staging to v2 production." width="100%"></p>

Use Bilinc when:

- a long-running agent (coding, support, research, a personal assistant) needs earlier decisions before a risky action;
- you need to know which run, tool or person wrote a piece of agent state;
- a bad run wrote wrong state and you need a way back, not a manual cleanup;
- several agents or teammates share one memory and you want per-key access and visible usage.

Reach for something else when you only need semantic search over documents (a vector database is the simpler tool), when you need an Apache-2.0, fully self-hosted runtime (this package is cloud-only and BUSL-1.1), or when you want the memory layer to also be your agent framework.

## Python SDK

```python
from bilinc import CloudClient

client = CloudClient()  # reads BILINC_API_KEY or the key saved by `bilinc login`

# Write, and keep the version for optimistic concurrency.
written = client.commit("agent.goal", {"ship": "reliable memory"}, memory_type="semantic")
results = client.recall("agent goal", limit=5)

# Correct something you already know. Fails if the key does not exist.
client.revise("agent.goal", {"ship": "verifiable memory"},
              reason="scope corrected", expected_version=written["entryVersion"])

# Checkpoint before risky work, then see what changed.
snapshot = client.create_snapshot(label="before-autonomous-run")["snapshot"]
client.diff(snapshot["id"])

# Recover. The preview is free; executing needs its token.
preview = client.rollback_preview(snapshot["id"], reason="undo bad agent run")
client.rollback(snapshot["id"], confirmation_token=preview["confirmationToken"],
                reason="undo bad agent run")

# Review what is stored. Listing, history and export are free reads.
for entry in client.iter_memories(prefix="agent."):
    print(entry["key"], entry["updatedAt"])
client.history("agent.goal")
client.confirm("agent.goal")   # still accurate; costs one write

# Take a memory out of use. A reason is required and recorded.
client.forget("agent.goal", reason="superseded by the planner service")
```

## CLI

```bash
bilinc status                          # plan, capabilities, limits, usage
bilinc commit --key agent.goal --value '{"ship":"reliable memory"}'
bilinc recall --query "agent goal"
bilinc revise --key agent.goal --value '{"ship":"verifiable memory"}' --reason "scope corrected"
bilinc list --prefix agent.            # keys, types, update times, value previews
bilinc history agent.goal              # recorded changes, newest first
bilinc snapshot create --label before-autonomous-run
bilinc diff --from-snapshot snap_...
bilinc export -o bilinc-export.json    # full values; the file is readable only by you
bilinc forget --key agent.goal --reason "superseded by the planner service"
```

Rollback is two steps, and execute never prompts, so it is safe in automation:

```bash
bilinc rollback preview --snapshot snap_... --reason "undo bad agent run"
bilinc rollback execute --snapshot snap_... --reason "undo bad agent run" \
  --confirmation-token <token-from-preview>
```

## MCP adapter

The stdio adapter works with any MCP client: Claude Code, Codex, Cursor, Hermes Agent, opencode and others. After `bilinc login`, let the CLI write the setup:

```bash
bilinc mcp install --client claude-code     # prints a ready `claude mcp add ...` command
bilinc mcp install --client claude-desktop  # prints the config and where Claude Desktop keeps it
bilinc mcp install                          # plain mcpServers JSON for any other client
```

The config carries no key; the adapter reads the one `bilinc login` saved. On a machine without one, add `"env": { "BILINC_API_KEY": "..." }`.

| Tool | What it does |
| --- | --- |
| `commit_mem` | Save durable state with its source; returns a version. |
| `recall` | Find earlier context and decisions before acting. |
| `revise` | Correct an existing memory. It never creates one. |
| `forget` | Take a memory out of use. **Destructive**; a reason is required. |
| `status` | Workspace, plan, capabilities, limits and usage. Never billed. |
| `snapshot` | Save a checkpoint before risky work, or list checkpoints. |
| `diff` | Compare a checkpoint with another one or with now. |
| `rollback` | Restore a checkpoint: a free preview, then a confirmed execute. |
| `list_memories` | Browse what is stored. Free. |
| `history` | One memory's changes, newest first. Free. |
| `confirm` | Record that a memory is still accurate. One write. |

The remote connector at `https://mcp.bilinc.space/mcp` has ten tools; a read-only connection lists only the four read tools. Client guides: [Claude Code](https://bilinc.space/docs/claude-code) · [Codex](https://bilinc.space/docs/codex) · [Cursor](https://bilinc.space/docs/cursor) · [any MCP client](https://bilinc.space/for/mcp).

## Forget and purge

<p align="center"><img src="https://raw.githubusercontent.com/ReARCLabs/bilinc-python/9774f8a97fb16b16cea10b974e9179e6f41df826/docs/assets/forget-and-purge.png" alt="Comparison of forget and forget --purge. Both stop recall and hide earlier values in memory history. After forget, saved checkpoints still contain the memory and the audit trail keeps each change. After purge, the memory is removed from every checkpoint and its values are removed from the audit trail; the key name and a fingerprint of each change stay. Encrypted backups keep earlier copies until they expire in both cases." width="100%"></p>

New in 2.5.0: `client.forget(key, reason=..., purge=True)`, `bilinc forget --key ... --reason ... --purge`, or `"purge": true` in the REST API also removes the memory's stored content from storage and history. It works on a memory you forgot earlier and cannot be undone. See the [privacy policy](https://bilinc.space/privacy) for what is kept and for how long.

## Hosted API

All endpoints live under `https://bilinc.space`. Memory operations need an API key and an active Bilinc Cloud plan; the free plan needs no card.

| Endpoint | Notes |
| --- | --- |
| `GET /api/cloud/health` | Public service health. No key, never billed. |
| `GET /api/cloud/status` | What one key can do. Never billed. |
| `POST /api/cloud/memory/commit` · `recall` · `revise` | Write, read, correct. |
| `POST /api/cloud/memory/forget` | Destructive. Reason required; `"purge": true` also removes stored content. |
| `GET` · `POST /api/cloud/memory/snapshots` | List (free) or create checkpoints. |
| `POST /api/cloud/memory/diff` | Compare checkpoints. Free. |
| `POST /api/cloud/memory/rollback/preview` | Free. Returns a confirmation token. |
| `POST /api/cloud/memory/rollback` | Destructive. Requires that token. |

Send an `Idempotency-Key` header on any write you might retry: the same key with the same payload replays the original result and is billed once; a different payload is refused with `409 idempotency_conflict`. Saves that contain a credential, such as an API key, token or private key, are refused with `secret_detected` and the value is never echoed back.

## What's new in 2.5.0

- **Purge**: forget can also remove a memory's content from storage and history.
- **Secret scan**: hosted saves are checked for credentials before anything is stored.
- **Recall**: hosted search ranks full-text matches by relevance and finds Turkish and other non-ASCII words.

Every release: [changelog](https://bilinc.space/changelog).

## Links

- [bilinc.space](https://bilinc.space) · [Docs](https://bilinc.space/docs) · [Install guide](https://bilinc.space/install) · [Pricing](https://bilinc.space/pricing) (free plan, no card) · [Changelog](https://bilinc.space/changelog) · [Trust](https://bilinc.space/trust)
- Compare: [vector memory](https://bilinc.space/compare/vector-memory) · [Mem0](https://bilinc.space/compare/mem0) · [Zep](https://bilinc.space/compare/zep) · [Letta](https://bilinc.space/compare/letta)
- Guides: [What is AI agent memory?](https://bilinc.space/answers/ai-agent-memory) · [Rolling back an agent memory write](https://bilinc.space/answers/agent-memory-rollback) · [Auditing what an agent remembered](https://bilinc.space/answers/audit-agent-memory)
- For machines: [llms.txt](https://bilinc.space/llms.txt) · [ai-index.json](https://bilinc.space/ai-index.json)

## Feedback and security

Questions, bugs and ideas: [GitHub Issues](https://github.com/ReARCLabs/bilinc-python/issues). Report security issues privately to bilincsupport@rearclabs.com (see [security.txt](https://bilinc.space/.well-known/security.txt)). Please keep memory values, API keys and production logs out of issues and screenshots.

## License

Business Source License 1.1, licensed by ReARC Labs Inc. See [LICENSE](https://github.com/ReARCLabs/bilinc-python/blob/main/LICENSE).
