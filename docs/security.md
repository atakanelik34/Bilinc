# Security Guide

Bilinc implements defense-in-depth security for memory operations.

## Input Validation

All inputs pass through `InputValidator` before reaching the storage layer:

```python
from bilinc.security.validator import InputValidator

# Key validation
key = InputValidator.validate_key("my_memory_key")
# Allowed: alphanumeric, hyphens, underscores, dots, colons
# Max length: 256 characters

# Value validation
value = InputValidator.validate_value({"data": "sensitive_content"})
# Check: JSON serializable, max 1MB

# Sanitization for KGraph node names
clean = InputValidator.sanitize_for_kg("<script>alert('xss')</script>RealNode")
# Result: "alert('xss')RealNode" (tags removed)
```

### Blocked Patterns
- **Path Traversal**: `../`, `/tmp/evil`, `\etc\passwd`
- **XSS Injection**: `<script>`, `javascript:`, `<style>`
- **Null Bytes**: `\x00` injection
- **Empty Keys**: `""`, `"  "`, `None`

## Resource Limits

| Resource | Limit | Action on Exceed |
|----------|-------|-----------------|
| Working Memory | 16 entries | Reject new commits |
| Episodic | 50,000 entries | Reject new commits |
| Semantic | 25,000 entries | Reject new commits |
| KG Nodes | 100,000 | Reject new nodes |
| KG Edges | 500,000 | Reject new edges |
| Value Size | 1MB | Reject commit |
| Audit Log | 1,000,000 entries | Rotation recommended |

## MCP Auth Policy (Prod-Strict)

Bilinc enforces transport-specific auth behavior:

- `stdio`: trusted-local mode, token optional.
- `http`: token required; missing/invalid token returns structured `unauthorized` error. (feat: complete Hermes public integration pack and prod-strict MCP policy)

- **stdio transport**: trusted local process boundary, no request-level auth
- **HTTP transport**: Bearer API key auth is enforced

For HTTP deployments:
- set `STATEMEL_API_KEY` or pass `auth_token=...`
- send `Authorization: Bearer <token>`
- token validation uses **constant-time comparison** (`hmac.compare_digest`)

HTTP app factory:

```python
from bilinc.mcp_server.server_v2 import create_mcp_http_app

app = create_mcp_http_app(auth_token="super-secret")
```

```python
from bilinc.mcp_server.server_v2 import create_mcp_server_v2
server = create_mcp_server_v2(plane, auth_token="your-secure-key-here", transport_mode="http")
``` (feat: complete Hermes public integration pack and prod-strict MCP policy)

For local development only:

```python
app = create_mcp_http_app(allow_unauthenticated=True)
```

## Rate Limiting

Default: **10 requests burst, 1 request/second refill** per client.

- **stdio**: single local bucket (`stdio`)
- **HTTP authenticated**: per-token bucket using a stable token hash
- **HTTP unauthenticated dev mode**: per-client-IP bucket

```python
server = create_mcp_server_v2(plane, max_tokens=20, refill_rate=2.0)
```

For HTTP:

```python
app = create_mcp_http_app(auth_token="super-secret", max_tokens=20, refill_rate=2.0)
```

HTTP error codes:
- `401`: missing or invalid bearer token
- `429`: rate limit exceeded
- `400`: malformed request / validation failure
- `500`: internal tool failure

## Audit Trail

When `enable_audit=True`, every operation is logged to a Merkle chain:

```python
plane = StatePlane(enable_audit=True)
# All creates, updates, deletions, consolidations → audit trail
```

The audit trail includes:
- Timestamp
- Operation type (CREATE, UPDATE, DELETE, CONSOLIDATE)
- Key and value diff
- Source identifier

## Recommendations

1. **Always validate keys**: Use `InputValidator.validate_key()` for user-provided keys.
2. **Enable audit in production**: `enable_audit=True` for compliance.
3. **Set appropriate API keys**: Rotate `STATEMEL_API_KEY` periodically for HTTP deployments.
4. **Monitor health and metrics**: Use HTTP `/health` and `/metrics`, or `plane.health.readiness()` / `plane.metrics.export_prometheus()` in-process.
5. **Backup database**: Regular SQLite/PostgreSQL backups for persistent storage.
