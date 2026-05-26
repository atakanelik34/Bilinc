# Bilinc

**Cloud-only memory SDK, CLI, and MCP adapter for autonomous agents.**

<p align="center">
  <a href="https://pypi.org/project/bilinc/"><img src="https://img.shields.io/pypi/v/bilinc?style=flat-square&logo=pypi&logoColor=white&color=0073b7" alt="PyPI"></a>
  <a href="https://pypi.org/project/bilinc/"><img src="https://img.shields.io/pepy/dt/bilinc?style=flat-square&logo=pypi&logoColor=white&color=0073b7&label=downloads" alt="All-time downloads"></a>
  <a href="https://github.com/ReARCLabs/Bilinc/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/ReARCLabs/Bilinc/ci.yml?branch=main&style=flat-square&logo=githubactions&logoColor=white&label=ci" alt="CI"></a>
  <a href="https://github.com/ReARCLabs/Bilinc/tags"><img src="https://img.shields.io/github/v/tag/ReARCLabs/Bilinc?sort=semver&style=flat-square&logo=github&label=tag" alt="GitHub tag"></a>
  <a href="https://pypi.org/project/bilinc/"><img src="https://img.shields.io/pypi/pyversions/bilinc?style=flat-square&logo=python&logoColor=white" alt="Python versions"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BUSL--1.1-orange?style=flat-square" alt="License: BUSL 1.1"></a>
</p>

```bash
pip install bilinc
```

Bilinc 2.1.1 is the current public package. It is intentionally thin: install from PyPI, start a 7-day Bilinc Cloud trial, create a hosted API key, then use the Python SDK, CLI, or MCP adapter against hosted Bilinc Cloud.

Start here: [https://bilinc.space/signup](https://bilinc.space/signup)

## Public package boundary

The public PyPI package ships only the cloud-facing surface:

- `CloudClient`
- `Bilinc` alias
- `BilincApiKeyRequired`
- `BilincCloudError`
- `bilinc` CLI
- `bilinc.cloud_mcp` hosted MCP adapter

It does not ship the previous local runtime, storage backends, eval stack, observability stack, local server internals, or private deployment paths.

`2.1.0` was yanked because it exposed the wrong public package boundary for the cloud-only release. Use `2.1.1` or newer.

## Quick start

1. Start a 7-day Cloud trial:

   [https://bilinc.space/signup](https://bilinc.space/signup)

2. Create a hosted API key in the Bilinc dashboard.

3. Set the API key:

   ```bash
   export BILINC_API_KEY="bil_live_..."
   ```

4. Install and use the SDK:

   ```bash
   pip install bilinc
   ```

   ```python
   from bilinc import CloudClient

   client = CloudClient()

   commit = client.commit(
       key="agent.memory.release",
       value={"status": "verified", "version": "2.1.1"},
       memory_type="semantic",
       importance=0.9,
   )

   recall = client.recall("release status", limit=5)

   print(commit)
   print(recall)
   ```

## CLI

```bash
bilinc --version
bilinc signup
bilinc status
bilinc commit --key agent.memory.release --value '{"status":"verified"}'
bilinc recall --query "release status"
```

The CLI reads `BILINC_API_KEY` from the environment unless `--api-key` is passed.

## MCP adapter

Bilinc includes a hosted Cloud MCP adapter for MCP-compatible agents:

```json
{
  "mcpServers": {
    "bilinc": {
      "command": "python",
      "args": ["-m", "bilinc.cloud_mcp"],
      "env": {
        "BILINC_API_KEY": "bil_live_..."
      }
    }
  }
}
```

Use this adapter when you want an agent to commit and recall hosted Bilinc Cloud memory without running a local backend.

## Hosted Cloud endpoints

The SDK targets the hosted Bilinc Cloud API:

- `GET /api/cloud/health`
- `POST /api/cloud/memory/commit`
- `POST /api/cloud/memory/recall`

Unauthenticated memory operations return `401`. Runtime access is controlled by Bilinc Cloud entitlements.

## Plans

Public signup starts with a 7-day Cloud Free Trial. Pro and Team checkout are handled through the authenticated billing console on [bilinc.space](https://bilinc.space).

See current pricing: [https://bilinc.space/pricing](https://bilinc.space/pricing)

## What Bilinc is for

Bilinc Cloud gives autonomous agents a hosted memory layer for:

- durable memory commit and recall
- API-key scoped runtime access
- project/workspace isolation
- audit-friendly hosted operations
- MCP-compatible agent workflows

The public package is an acquisition and integration surface for the hosted product, not a bundle of the full private runtime.

## Verification

The release process checks that public artifacts do not contain private runtime packages and that the wheel/sdist expose only the intended cloud-facing modules.

Expected public import surface:

```python
import bilinc
from bilinc import CloudClient, Bilinc, BilincApiKeyRequired, BilincCloudError

print(bilinc.version)
```

Expected version:

```text
2.1.1
```

## License

[BUSL 1.1](LICENSE). Hosted Bilinc Cloud access is governed by active Cloud entitlements and plan limits.
