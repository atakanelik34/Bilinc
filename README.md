# Bilinc

Bilinc is a ReARC Labs product for hosted, verifiable AI agent memory.

Bilinc 2.1.4 on PyPI is the public cloud-only package: a thin Python SDK, CLI, and MCP adapter for Bilinc Cloud. It does not ship the local StatePlane, storage backends, eval, observability, integrations, or server runtime internals.

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

## MCP Adapter

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

The adapter exposes hosted commit, recall, and status operations. It does not bundle local runtime internals.

## Hosted Endpoints

- Health: `GET https://bilinc.space/api/cloud/health`
- Commit: `POST https://bilinc.space/api/cloud/memory/commit`
- Recall: `POST https://bilinc.space/api/cloud/memory/recall`

Authenticated memory operations require an active Bilinc Cloud entitlement.

## Links

- Website: https://bilinc.space
- Signup: https://bilinc.space/signup
- Install guide: https://bilinc.space/install
- Quickstart: https://bilinc.space/docs/quickstart
- Cloud quickstart: https://bilinc.space/docs/cloud-quickstart
- Migration guide: https://bilinc.space/docs/migration-v2
- PyPI: https://pypi.org/project/bilinc/

## License

BUSL-1.1. See `LICENSE`.
