# Hermes Integration Contract

This document defines the stable Bilinc↔Hermes behavior contract.

## Tool Call Order

1. `commit_mem`
2. `recall`
3. `revise`
4. `snapshot`
5. `diff`
6. `rollback`

`diff` and `rollback` require persistent backend + audit.

## Metadata Standard

Hermes writes should use:

- `source` (`hermes`, `hermes_session_summary`, etc.)
- `session_id` (session correlation id)
- `canonical` (`true` for durable truth, `false` for session summary)
- `priority` (`low|normal|high`)
- `ttl` (seconds, recommended for session summaries)

## Priority Rules

Recall ordering is stable and deterministic:

1. canonical first
2. higher priority first
3. verified first
4. stronger/important first
5. newer first

Session summaries should be low-priority and non-canonical.

## TTL / Retention

- Session summary keys should be prefixed with `hermes_session::`
- Recommended default TTL: `1209600` (14 days)
- Expired entries should be filtered from recall.

## Example `commit_mem` Payload

```json
{
  "key": "user_profile",
  "value": {"name": "Atakan", "focus": "Bilinc"},
  "memory_type": "semantic",
  "importance": 0.92,
  "source": "hermes",
  "session_id": "20260410_123456_abcd",
  "canonical": true,
  "priority": "high",
  "metadata": {"scope": "founder_profile"}
}
```

## Session Summary Example

```json
{
  "key": "hermes_session::20260410_123456_abcd",
  "value": {"summary": "Discussed launch checklist."},
  "memory_type": "episodic",
  "source": "hermes_session_summary",
  "session_id": "20260410_123456_abcd",
  "canonical": false,
  "priority": "low",
  "ttl": 1209600
}
```

## Compatibility Promise

No breaking rename of MCP tools:

- `commit_mem`, `recall`, `revise`, `snapshot`, `diff`, `rollback`
