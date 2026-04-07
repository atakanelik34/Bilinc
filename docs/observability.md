# Observability Guide

Bilinc exposes lightweight in-process observability for both embedded use and HTTP deployments.

## Health Model

Bilinc reports three top-level health states:

- `healthy`: safe to serve traffic
- `degraded`: serving, but with a meaningful warning
- `failed`: not safe to serve requests

Two views are available:

- `liveness`: answers "is the process up?"
- `readiness`: answers "is the system ready to serve traffic safely?"

In-process:

```python
readiness = plane.health.readiness()
liveness = plane.health.liveness()
```

HTTP:

- `GET /health`

Example response shape:

```json
{
  "service": "bilinc-mcp-http",
  "status": "healthy",
  "ephemeral": true,
  "liveness": {"status": "healthy"},
  "readiness": {"status": "healthy", "issues": []}
}
```

### Component Reporting

Health includes component-level status for:

- backend
- audit
- working memory
- AGM engine
- knowledge graph
- verification
- HTTP transport configuration

Notes:

- in-memory mode is reported as `ephemeral`, not failed
- unauthenticated HTTP dev mode is reported as `degraded`
- missing or broken persistent backends fail readiness

## Metrics

Bilinc exports Prometheus-compatible metrics with the `bilinc_` prefix.

HTTP:

- `GET /metrics`

In-process:

```python
payload = plane.metrics.export_prometheus()
```

Current metric families include:

- operation totals and latency for commit, recall, forget, snapshot, diff, rollback
- HTTP request counters and latencies
- auth failure counters
- rate limit hit counters
- backend error counters
- health/readiness/liveness gauges
- working memory and AGM gauges

## Operator Guidance

- scrape `/metrics` from trusted infrastructure using the same bearer token as the HTTP MCP surface
- use `/health` for deployment probes and automated checks
- alert on:
  - `readiness.status != healthy`
  - `bilinc_auth_failures_total`
  - `bilinc_rate_limit_hits_total`
  - `bilinc_backend_errors_total`
