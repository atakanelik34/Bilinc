# Bilinc Audit Hardening Design

## Goal
Restore Bilinc live audit integrity and harden `AuditTrail` so concurrent or stale MCP stdio processes cannot fork the audit chain again.

## Current failure
`mcp_bilinc_health` reports `readiness=failed`, `liveness=degraded`, and `audit_integrity_invalid`. Diagnostic replay of `/Users/busecimen/bilinc.db` shows the first bad `audit_log` row at id 582 with five bad rows through 586. Two `bilinc_stdio_v2.py` processes are currently running, which makes process-local `_root_hash` unsafe.

## Design
`AuditTrail.log()` must treat SQLite as the source of truth for the latest root. It will acquire a SQLite write lock using `BEGIN IMMEDIATE`, read `SELECT root_hash FROM audit_log ORDER BY id DESC LIMIT 1` inside that transaction, compute the next hash from that root, insert the entry, commit, and update the process-local cache only after commit. The existing thread lock remains useful inside a process, but it is no longer the correctness boundary.

The live database repair remains explicit and manual: backup the DB, replay the audit log from genesis, verify every `data_hash`, and only update `prev_root`/`root_hash` for rows whose data hash is intact. If any data hash mismatches, stop instead of silently rewriting history.

The MCP status tool should report the installed package version via `importlib.metadata.version("bilinc")` instead of the stale hardcoded `1.0.4`.

## Verification
- Add a regression test with two `AuditTrail` instances connected to the same SQLite DB. Instance B initializes before instance A writes, so B has a stale local root. B then writes and the final chain must remain valid.
- Run targeted pytest for audit/security/sqlite/AGM/belief sync.
- Run live DB diagnostic before and after repair.
- Restart/reload MCP so only fresh code writes to the database.
- Verify `mcp_bilinc_health` returns healthy readiness and no `audit_integrity_invalid` issue.
