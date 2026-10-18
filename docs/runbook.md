# Internal Runtime Operator Runbook

> Source-only/internal runtime. Public PyPI users should follow the Cloud quickstart
> instead of this document.

This runbook covers the supported Bilinc deployment surfaces in the current production gate.

## Deployment Modes

- **stdio MCP**: trusted local process boundary, no request-level auth
- **HTTP MCP**: production-facing transport with bearer auth and rate limiting
- **SQLite**: small deployment / local durability path
- **PostgreSQL**: validated in CI when installed with the `postgres` extra

## Required Runtime Inputs

### HTTP auth

Set either:

- `BILINC_MCP_AUTH_TOKEN`
- or pass `auth_token=...` when creating the HTTP app

### Persistence

- SQLite/PostgreSQL configuration is supplied by the internal runtime launcher;
  the public `bilinc` CLI has no local `--db` mode.

### Recall options (optional)

These are internal runtime features; they are not in the PyPI package and are
off unless configured.

- **Distilled facts.** `bilinc.integrations.distill.commit_distilled(plane, key, text, extract)`
  stores the exchange as an episodic source and each fact `extract` returns as a
  semantic memory pointing back to it, with the same timestamp.
  `recall_reflective(..., memory_types=[MemoryType.SEMANTIC], expand_sources=True)`
  searches the facts and returns each fact's source with it.
- **Recency tie-breaking.** With `BILINC_RECALL_RECENCY_FUSION=1`, a recall that
  carries a `query_timestamp` orders near-equal matches newest first, so it
  returns the value that was current then; clearly better matches keep their place.
- **Cross-encoder rerank.** `BILINC_RERANK_MODEL` names a local Sentence
  Transformers cross-encoder (needs the `semantic` extra); the top
  `BILINC_RERANK_DEPTH` results are rescored against the query. Recall keeps the
  fused order if the model does not load.

| Variable | Default | Purpose |
|---|---|---|
| `BILINC_RECALL_RECENCY_FUSION` | off | As-of recall orders near-equal matches newest first |
| `BILINC_RERANK_MODEL` | unset | Cross-encoder model name; setting it enables rerank |
| `BILINC_RERANK_DEPTH` | `100` | How many results are rescored |
| `BILINC_RERANK_DEVICE` | `cpu` | Torch device for the cross-encoder |
| `BILINC_RERANK_MODEL_REVISION` | unset | Pinned model revision |

## HTTP Deployment

Minimal example:

```python
from bilinc.core.stateplane import StatePlane
from bilinc.mcp_server.server_v2 import create_mcp_http_app

plane = StatePlane(enable_verification=False, enable_audit=False)
plane.init_agm()
plane.init_knowledge_graph()

app = create_mcp_http_app(plane=plane, auth_token="your-auth-token")
```

Run with:

```bash
uvicorn yourmodule:app --host 0.0.0.0 --port 8000
```

## Probes and Metrics

- `GET /health`
  - exposes `liveness`
  - exposes `readiness`
  - returns `200` for healthy/degraded
  - returns `503` for failed readiness
- `GET /metrics`
  - Prometheus-compatible text
  - `bilinc_` prefix

## Expected States

### Healthy

- backend reachable
- audit integrity valid when audit is enabled
- authenticated HTTP is active for production deployments
- no blocking issues in readiness

### Degraded

- in-memory / ephemeral operation where expected
- HTTP dev mode with `allow_unauthenticated=True`
- non-blocking component limitations

### Failed

- persistent backend unavailable or uninitialized
- schema/version mismatch
- audit required but unavailable
- integrity failure

## First Troubleshooting Steps

1. Check `/health` and inspect `issues`.
2. Check `/metrics` for:
   - `bilinc_auth_failures_total`
   - `bilinc_rate_limit_hits_total`
   - `bilinc_backend_errors_total`
3. Verify backend configuration:
   - SQLite path exists and is writable
   - PostgreSQL DSN is reachable
4. Re-run local smoke:

```bash
python -m bilinc.mcp_server.hermes_stdio
```

5. If PostgreSQL is failing, validate the service independently and then re-run the targeted integration tests with:

```bash
BILINC_TEST_POSTGRES_DSN=postgresql://... PYTHONPATH=src pytest -q tests/test_postgres_integration.py
```
