# Bilinc Agent Operating Contract

Project: Bilinc, the verifiable state plane for autonomous agents.
Primary concerns: agent-memory, security-critical, public-facing, infra-prod when cloud/runtime code is touched.

## Stack lock

- Language: Python 3.10+.
- Packaging: setuptools via `pyproject.toml`.
- Storage: SQLite default, PostgreSQL optional; do not switch memory backend or storage architecture without Atakan approval.
- Verification/memory primitives: AGM belief revision, FTS5 recall, knowledge graph/entity signals, Z3 verification, Merkle audit, snapshots/diff/rollback.
- Optional cloud/server code must remain separate from the local/self-hosted package path unless the task explicitly asks to change the boundary.

## Repo commands

Use focused commands first, then broaden only when risk requires it:

- Focused tests: `python3 -m pytest tests/<target>.py -q`
- Full tests: `python3 -m pytest tests/ -q`
- Build package: `python3 -m build`
- Lint if available in the environment: `python3 -m ruff check src tests`
- MCP smoke when MCP/server code changes: `python3 -m bilinc.mcp_server.server_v2` only in a controlled smoke context, or use the established Hermes MCP test path from the ReARC operating layer.

## Scope discipline

- Only modify files directly required by the current task.
- Do not refactor, rename, reformat, or reorganize unrelated code.
- If unrelated debt is noticed, report it as a follow-up instead of touching it.
- Preserve existing public APIs, CLI behavior, MCP schemas, storage schemas, and package metadata unless the task explicitly targets them.
- Prefer the simplest compatible implementation. Do not add abstractions or dependencies speculatively.

## Approval gates

Explicit in-session Atakan approval is required before:

- Changing model/provider, memory backend, or storage backend defaults.
- Mutating the live `/Users/busecimen/bilinc.db` except for an explicitly requested receipt/capture key.
- Running destructive data operations, rollback, forget/delete, migrations against live data, or irreversible schema changes.
- Publishing to PyPI, yanking releases, changing public package metadata, or deploying `bilinc.space`.
- Making public claims about cloud billing, paid activation, or production readiness without live verification.
- Exposing or printing secrets, API keys, database dumps, user memory contents beyond the task scope, or private Stripe/runtime values.

Read-only inspection, local tests, local builds, and non-mutating recall are allowed.

## Memory and source-of-truth routing

- Bilinc is the canonical machine-readable memory/state layer for ReARC agent state, product status, receipts, and verification records.
- Vault is the human-readable source of truth for operating docs, product decisions, and session captures.
- Built-in Hermes memory is only for compact bootloader hints and stable preferences.
- `session_search` is transcript recall, not source-of-truth state.
- Do not create a repo-local MEMORY.md as canonical project memory. Use Bilinc/Vault unless the user explicitly asks for a local scratch file.

## Public and package claim safety

- Public README/site/PyPI claims must be backed by current repo, package, or live service evidence.
- Do not claim hosted Cloud billing is self-serve end-to-end unless checkout, entitlement sync, client adapters, and live smoke are verified.
- Keep local package/self-host free positioning separate from hosted API billing.

## Verification before done

- For code changes: inspect diff and run focused tests covering the touched path.
- For MCP/recall/memory changes: include adversarial or regression tests for evidence scope, explicit argument precedence, destructive-path safety, and backend parity where relevant.
- For package/public surface changes: verify build artifacts or rendered docs as applicable.
- Final response must include changed files, verification run, and caveats.

## Git discipline

- Do not push unless Atakan explicitly asks.
- Commit only when requested or when the task explicitly includes commit workflow.
- If committing in ReARC/Bilinc repos, use author and committer: `Atakan Elik <atakan@rearclabs.com>`.
- Preserve existing dirty work. Never reset, stash, or overwrite unrelated changes without approval.
