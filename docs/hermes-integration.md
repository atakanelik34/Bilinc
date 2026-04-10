# Hermes Integration Guide

Bilinc can run as Hermes' durable MCP memory layer with a one-command bootstrap.

## Install (10 minutes)

```bash
pip install bilinc
bilinc hermes bootstrap --hermes-home ~/.hermes --db-path ~/bilinc.db
```

The bootstrap command creates:

- `~/.hermes/bilinc_stdio_v2.py` (standard launcher, server_v2 only)
- `~/.hermes/bilinc.env` (runtime env defaults)
- an integration smoke report for `commit/recall/revise/diff/rollback`

## Runtime Matrix

| Mode | Transport | Auth | Rate Limit | Recommended Use |
|------|-----------|------|------------|-----------------|
| Local | `stdio` | Optional (trusted-local) | Enabled | Hermes local agent runtime |
| Production | HTTP wrapper around MCP | Required token (`STATEMEL_API_KEY`) | Required | Shared service / remote agents |

## Auth Modes

- `stdio` mode: trusted-local by policy, token is optional.
- `http` mode: token is required and compared in constant time.
- invalid/missing token must return structured error payload.

## Integration Contract

See [Hermes Integration Contract](./hermes-integration-contract.md).

## Troubleshooting

1. **Rate limit response**
- Symptom: `rate_limited` error payload.
- Fix: raise `max_tokens` / `refill_rate` or reduce request burst.

2. **Auth failures in HTTP mode**
- Symptom: `unauthorized` error payload.
- Fix: set `STATEMEL_API_KEY` and pass `_auth_token` in request args.

3. **Wrong DB path / no persistence**
- Symptom: data disappears after restart.
- Fix: verify `BILINC_DB_PATH` points to persistent location.

4. **Stale session summaries polluting recall**
- Symptom: session noise dominates recall.
- Fix: use metadata contract (`canonical=false`, `priority=low`, `ttl`) and `exclude_session_summaries=true` when needed.

5. **Diff/Rollback not working**
- Symptom: `persistent backend or audit trail required`.
- Fix: run with SQLite/PostgreSQL backend and `BILINC_ENABLE_AUDIT=1`.
