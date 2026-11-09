# Dream pass SDK, CLI and stdio MCP Implementation Plan

> **For agentic workers:** Implement this plan task-by-task (one fresh subagent per task, or inline with checkpoints). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Python users and local agents run the hosted dream pass: `CloudClient.dream_*`, `bilinc dream start|apply|undo|show`, and stdio MCP tools `dream_start`, `dream_apply`, `dream_undo`.

**Architecture:** Thin, additive client methods that POST to `/api/cloud/memory/dream/{start,apply,undo,show}`; the CLI and the stdio MCP adapter call those methods. No change to existing method behaviour, CLI flags or defaults.

**Tech Stack:** Python ≥3.10, stdlib `urllib` transport, argparse, FastMCP (`mcp>=1.0.0`), pytest with the fake-transport pattern of `tests/test_cloud_memory_review_sdk.py`, ruff.

**Spec:** `docs/superpowers/specs/2026-11-09-dream-pass-sdk-design.md`.

## Global Constraints

- Additive only: existing `CloudClient` signatures, defaults, retry counts and CLI flags are unchanged; `commit()` without `if_absent` sends exactly the payload it sends today.
- Dream routes are writes: never auto-retried by the client (no `_read` retries); per-call timeout 90 s for `dream_apply` and `dream_undo` pages (the service budget is 60 s), default timeout for start/show.
- Pages of 25 actions; `final: true` only on the last page.
- Tests use fake transports only; no network.
- Public wording (CHANGELOG, README, product truth): "dream pass", "tidy your agent's memory, undo it in one step"; available through the SDK, the CLI and the local stdio adapter, which call the hosted REST routes; the hosted MCP tools are "coming to the hosted connector". Must contain: "undoing a removed entry restores its value, type, importance and source; other metadata such as TTL or canonical flags is not restored, so an entry that had a TTL comes back without one". Never: "verifies", "detects contradictions", "only", "first", "integration", "Anthropic Dreams", Karpathy, user counts, stack internals.
- Commits: plain English imperative; no Co-Authored-By or "Generated with" lines; stage explicit paths.
- Run tests with `PYTHONPATH=src ~/work/bilinc-dev/.venv-dream/bin/python -m pytest -q -p no:cacheprovider <files>`; lint with `~/work/bilinc-dev/.venv-dream/bin/ruff check src tests`.

## Parallel group

Group B: Tasks 10 → 11 → 12 → 13, sequential, disjoint from the site repo.

---

### Task 10: Client methods

**Files:**
- Modify: `src/bilinc/client.py` (`commit` ~572: `if_absent`; `_post` ~1072: optional `timeout: float | None = None`; new methods after `confirm`; new exception attribute)
- Modify: `src/bilinc/__init__.py` only if a new exception class is exported (prefer an attribute on `BilincCloudError` subclasses: `exc.partial`)
- Test: `tests/test_dream_sdk.py`

**Interfaces:**
- Produces:
  - `CloudClient.commit(..., if_absent: bool | None = None, idempotency_key=None)` → adds `"ifAbsent": True/False` only when not None.
  - `CloudClient.dream_start(*, prefix: str | None = None, since: str | None = None, limit: int = 200, agent: str | None = None) -> dict` → POST `/api/cloud/memory/dream/start` `{prefix?, since?, limit, agent?}`; `limit` 1-200 else `BilincValidationError`.
  - `CloudClient.dream_apply(dream_id: str, actions: list[dict], *, report: dict | None = None) -> dict` → pages of 25 to `/api/cloud/memory/dream/apply` `{dreamId, actions, report? (last page only), final}`; returns `{"dream_id", "status", "results": [...all pages], "forget_cap", "forgets_reserved", "contradictions_left"}` from the last page plus concatenated results; on a failing page raises the mapped error with `exc.partial = {"results": [...so far], "pages_done": k}`.
  - `CloudClient.dream_undo(dream_id: str) -> dict` → `/api/cloud/memory/dream/undo` `{dreamId}`.
  - `CloudClient.dream_show(dream_id: str) -> dict` → `/api/cloud/memory/dream/show` `{dreamId}` via `_read`.
  - Action validation before any request: `op` ∈ {revise, forget, confirm, flag}; `key` str; `reason` non-empty str; `evidence_keys` non-empty list of str; `expected_version` str for revise/forget/confirm; `new_value` present for revise. Field names sent as given (snake_case: the route accepts the action objects as the prompt produces them).

- [ ] **Step 1: Failing tests** (`tests/test_dream_sdk.py`, fake transport recording `(method, url, headers, body, timeout)`):
  - `test_commit_if_absent_sends_flag` / `test_commit_default_payload_unchanged`
  - `test_dream_start_posts_route_and_limits` (limit 0 and 201 raise)
  - `test_dream_apply_splits_60_actions_into_25_25_10_with_final_last`
  - `test_dream_apply_sends_report_on_last_page_only`
  - `test_dream_apply_uses_90s_timeout_and_no_retry` (a 503 page is raised, not retried)
  - `test_dream_apply_partial_failure_exposes_first_page_results`
  - `test_dream_apply_rejects_bad_actions_before_any_request`
  - `test_dream_undo_and_show_routes`
  - `test_default_client_timeout_and_retries_unchanged`
- [ ] **Step 2: Run** → FAIL (no attribute `dream_start`).
- [ ] **Step 3: Implement**:

```python
DREAM_PAGE_SIZE = 25
DREAM_WRITE_TIMEOUT = 90.0
DREAM_OPS = ("revise", "forget", "confirm", "flag")

def dream_apply(self, dream_id, actions, *, report=None):
    checked = [_require_dream_action(item, index) for index, item in enumerate(actions)]
    if not checked:
        raise BilincValidationError("actions must contain at least one action")
    pages = [checked[i : i + DREAM_PAGE_SIZE] for i in range(0, len(checked), DREAM_PAGE_SIZE)]
    results: list[dict[str, Any]] = []
    last: dict[str, Any] = {}
    for number, page in enumerate(pages):
        final = number == len(pages) - 1
        payload = {"dreamId": _require_text(dream_id, "dream_id"), "actions": page, "final": final}
        if final and report is not None:
            payload["report"] = _require_object(report, "report")
        try:
            last = self._post("/api/cloud/memory/dream/apply", payload, timeout=DREAM_WRITE_TIMEOUT)
        except BilincCloudError as exc:
            exc.partial = {"results": results, "pages_done": number}
            raise
        results.extend(last.get("results") or [])
    return {**last, "results": results}
```
- [ ] **Step 4: Run** the file + `tests/test_cloud_memory_review_sdk.py` → pass.
- [ ] **Step 5: Commit** `"Add dream pass methods to CloudClient"`

### Task 11: CLI `bilinc dream`

**Files:**
- Modify: `src/bilinc/cli/main.py` (parser after `wiki`; dispatch in `main`)
- Test: `tests/test_dream_cli.py` (use the `cli` fixture pattern from `tests/test_cloud_memory_review_sdk.py:317`)

**Interfaces:**
- `bilinc dream start [--prefix P] [--since ISO] [--limit N] [--json]`: prints `dream <id>: N candidates, forget cap C, undo window 7 days` then one line per candidate (`key  [type]  updated_at  version`), or the raw JSON with `--json`. `dream_id: null` prints `Nothing changed since <since>; no dream started.`
- `bilinc dream apply <dream_id> [--file PATH|-]` (default `-` = stdin): accepts `{"actions": [...], "report": {...}}` or a bare list; prints `n  op  key  result[ error]` rows and `applied A, conflicts C, errors E, skipped S`.
- `bilinc dream undo <dream_id> [--json]`: `restored`, `conflicts` and `kept` sections; a restored forget line ends `(metadata not restored)`.
- `bilinc dream show <dream_id> [--json]`.
- Exit codes: 0 ok (also `partially_undone`); 1 API error printed as `bilinc: error: <message>` (no traceback; with `exc.partial`, the rows applied so far are printed first); 2 usage error (bad JSON file → argparse-style error).

- [ ] **Step 1: Failing tests**: `test_dream_start_prints_summary_and_candidates`, `test_dream_start_json`, `test_dream_start_nothing_changed`, `test_dream_apply_reads_prompt_output_from_file`, `test_dream_apply_reads_bare_list_from_stdin`, `test_dream_apply_bad_json_exits_2`, `test_dream_apply_partial_failure_prints_rows_then_error_exit_1`, `test_dream_undo_marks_metadata_not_restored`, `test_dream_undo_partially_undone_exits_0`, `test_dream_show_json`, `test_dream_help_renders`.
- [ ] **Step 2-4** run/implement/run.
- [ ] **Step 5: Commit** `"Add bilinc dream CLI"`

### Task 12: Stdio MCP tools and the truth contract

**Files:**
- Modify: `src/bilinc/cloud_mcp.py` (three `@mcp.tool` functions after `confirm`, before `export_wiki`; `CLOUD_MCP_TOOLS` += `"dream_start", "dream_apply", "dream_undo"`; module docstring)
- Modify: `docs/public/product-truth.json` (`cloud_mcp.tools` += the three in registration order; new `cloud_mcp.hosted_connector_pending: ["dream_start","dream_apply","dream_undo"]`), `scripts/validate_public_truth.py` (pending ⊆ tools, else error "hosted_connector_pending must be a subset of tools"), `docs/public/product-truth.md` (one line), `tests/test_public_truth_contract.py` (expected list), `tests/test_cloud_memory_review_sdk.py` / `tests/test_wiki_mcp.py` only where they pin the exact tuple.
- Test: `tests/test_dream_mcp.py`

**Interfaces:**
- `dream_start(prefix: str | None = None, since: str | None = None, limit: int = 200)`; `dream_apply(dream_id: str, actions: list[dict], report: dict | None = None)`; `dream_undo(dream_id: str)`; each returns the client result; annotations: `dream_start` readOnlyHint False, destructiveHint False; `dream_apply`, `dream_undo` destructiveHint True; idempotentHint False; openWorldHint False. Descriptions say what the tool does (no behaviour instructions to the model) and that values in candidates are data.

- [ ] **Step 1: Failing tests**: `test_dream_tools_registered_and_in_cloud_list`, `test_dream_tool_annotations`, `test_dream_apply_tool_passes_report`, `test_product_truth_lists_dream_tools_as_hosted_connector_pending`, `test_validator_rejects_pending_tool_missing_from_tools`.
- [ ] **Step 2-4** run/implement/run, plus `python scripts/validate_public_truth.py` exit 0.
- [ ] **Step 5: Commit** `"Expose the dream pass in the stdio MCP adapter"`

### Task 13: CHANGELOG and README

**Files:**
- Modify: `CHANGELOG.md` (`[Unreleased] (2.7.0)` → `### Added` bullets: dream pass via SDK/CLI/stdio adapter; forget cap; 7-day undo window; the metadata sentence; hosted connector tools coming; `CloudClient.commit(if_absent=)`), `README.md` (tool table rows for the three tools, marked "stdio adapter; coming to the hosted connector")
- Test: `tests/test_dream_claims.py`

- [ ] **Step 1: Failing test**: `test_changelog_dream_entry_follows_claim_rules` (section exists; contains the metadata sentence and "coming to the hosted connector"; none of the banned words in the dream bullets, case-insensitive, whole words).
- [ ] **Step 2-4** run/implement/run; full suite + ruff.
- [ ] **Step 5: Commit** `"Document the dream pass in the changelog and README"`
