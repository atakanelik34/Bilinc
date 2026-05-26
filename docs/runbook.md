# Operator Runbook

This runbook covers the supported Bilinc deployment surfaces in the current production gate.

## Deployment Modes

- **stdio MCP**: trusted local process boundary, no request-level auth
- **HTTP MCP**: production-facing transport with bearer auth and rate limiting
- **SQLite**: small deployment / local durability path
- **PostgreSQL**: validated in CI when installed with the `postgres` extra

## Required Runtime Inputs

### HTTP auth

Set either:

- `STATEMEL_API_KEY`
- or pass `auth_token=...` when creating the HTTP app

### Persistence

- SQLite:
  - `bilinc --db ./bilinc.db ...`
- PostgreSQL:
  - `bilinc --db postgresql://user:pass@host/db ...`

## HTTP Deployment

Minimal example:

```python
from bilinc import StatePlane
from bilinc.mcp_server.server_v2 import create_mcp_http_app

plane = StatePlane(enable_verification=False, enable_audit=False)
plane.init_agm()
plane.init_knowledge_graph()

app = create_mcp_http_app(plane=plane, auth_token="super-secret")
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
bilinc --db ./tmp.db commit --key smoke_key --value hello
bilinc --db ./tmp.db recall --key smoke_key
```

5. If PostgreSQL is failing, validate the service independently and then re-run the targeted integration tests with:

```bash
BILINC_TEST_POSTGRES_DSN=postgresql://... PYTHONPATH=src pytest -q tests/test_postgres_integration.py
```
