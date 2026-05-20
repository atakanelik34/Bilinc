# Bilinc

Cloud-only memory SDK and MCP adapter for autonomous agents.

Bilinc 2.0 on PyPI is intentionally thin: it does not ship the local StatePlane, storage backends, evaluation harness, or server internals. The public package connects agents to hosted Bilinc Cloud at https://bilinc.space.

```bash
pip install bilinc
export BILINC_API_KEY=bil_live_...
```

Start a 7-day trial at https://bilinc.space/signup, create an API key, then use the SDK, CLI, or MCP adapter from your agent runtime.

## Python SDK

```python
import os
from bilinc import CloudClient

client = CloudClient(api_key=os.environ["BILINC_API_KEY"])

client.commit(
    "agent.intent",
    {"goal": "ship reliable memory"},
    memory_type="semantic",
    importance=0.9,
)

results = client.recall("reliable memory", profile="balanced", limit=5)
status = client.status()
```

## CLI

```bash
bilinc signup
bilinc commit --key USER_PREF --value '{"theme":"dark"}'
bilinc recall --query "user preference" --profile balanced --limit 5
bilinc status
```

All commands use `BILINC_API_KEY` unless `--api-key` is passed explicitly.

## MCP adapter

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

## What is included in 2.0

- `bilinc.CloudClient`
- `bilinc.Bilinc` alias
- `bilinc` CLI for hosted commit, recall, status, and signup
- `bilinc.cloud_mcp` adapter entrypoint

## What is not included

- Local `StatePlane`
- SQLite/PostgreSQL storage backends
- Z3/networkx local runtime dependencies
- Local MCP server internals
- Evaluation, observability, and integration packages

Those internals remain separate from the public PyPI install path. Use Bilinc Cloud for hosted storage, retention, audit, API keys, and billing-backed entitlements.

## License

[BUSL-1.1](LICENSE).
