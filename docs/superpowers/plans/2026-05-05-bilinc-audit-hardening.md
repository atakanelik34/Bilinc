# Bilinc Audit Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair Bilinc's live audit chain and make audit appends safe across duplicate/stale MCP stdio processes.

**Architecture:** Use SQLite's write lock as the cross-process serialization boundary. Every append reads the latest persisted root inside `BEGIN IMMEDIATE`, then inserts and commits atomically. Live DB repair is explicit, backed up, and only rewrites chain hashes when row data hashes are intact.

**Tech Stack:** Python 3.11, SQLite, pytest, Bilinc MCP stdio.

---

### Task 1: Regression test for stale multi-instance audit writers

**Files:**
- Modify: `tests/test_security.py`
- Modify: `src/bilinc/core/audit.py`

- [ ] **Step 1: Write the failing test**

Add a pytest that initializes two `AuditTrail` instances against the same temporary DB. Initialize B before A writes so B's local `_root_hash` is stale, then interleave writes and assert both instances verify the chain as valid.

- [ ] **Step 2: Run the test to verify RED**

Run:
`python3 -m pytest tests/test_security.py::test_audit_trail_handles_stale_multi_instance_root -q`

Expected before implementation: FAIL with `integrity['valid'] is False` or equivalent root mismatch.

- [ ] **Step 3: Implement minimal code**

In `AuditTrail.log()`, keep the thread lock but start `BEGIN IMMEDIATE`, read the latest `root_hash` from `audit_log` inside the transaction, compute the new root from that persisted root, insert, commit, then update `self._root_hash`.

- [ ] **Step 4: Verify GREEN**

Run:
`python3 -m pytest tests/test_security.py::test_audit_trail_handles_stale_multi_instance_root -q`

Expected after implementation: PASS.

### Task 2: MCP status version correctness

**Files:**
- Modify: `src/bilinc/mcp_server/server_v2.py`
- Test: existing MCP/status tests if available, otherwise direct Python import check.

- [ ] **Step 1: Replace hardcoded version**

Change `_handle_status()` from `{"tool": "status", "version": "1.0.4"}` to a helper that calls `importlib.metadata.version("bilinc")` with fallback `"unknown"`.

- [ ] **Step 2: Verify version**

Run direct call or grep/import check to confirm status code path no longer contains hardcoded `1.0.4`.

### Task 3: Live DB repair

**Files:**
- Live DB: `/Users/busecimen/bilinc.db`
- Backup: `/Users/busecimen/bilinc.db.bak-YYYYMMDD-HHMMSS-audit-repair`

- [ ] **Step 1: Backup DB**

Copy the DB before changing it.

- [ ] **Step 2: Repair only chain hashes**

Replay `audit_log` from genesis. For each row, recompute `data_hash`. If the stored `data_hash` differs, abort. Otherwise recompute and update `prev_root`/`root_hash` where needed.

- [ ] **Step 3: Verify DB**

Run the diagnostic replay. Expected: `first_bad=null`, `bad_count=0`.

### Task 4: Restart stale MCP writers and verify live health

**Files/processes:**
- `bilinc_stdio_v2.py` processes
- Hermes gateway/MCP client

- [ ] **Step 1: Kill duplicate stale Bilinc MCP processes**

Stop stale `bilinc_stdio_v2.py` processes so no old process can keep writing with stale root logic.

- [ ] **Step 2: Restart/reload Hermes gateway/MCP**

Use Hermes gateway restart or MCP reload equivalent.

- [ ] **Step 3: Verify live Bilinc health**

Run `mcp_bilinc_bilinc_health` and audit diagnostic. Expected: readiness healthy, liveness healthy, no `audit_integrity_invalid`.

### Task 5: Persist session record

**Files/systems:**
- Bilinc semantic memory
- Obsidian Vault note under ReARC/Bilinc infrastructure notes

- [ ] **Step 1: Save concise Bilinc summary**

Use a semantic key for this hardening session with changed files, backup path, tests run, and live health result.

- [ ] **Step 2: Save Vault note**

Create or update a dated Vault note with the same facts and future follow-ups.
