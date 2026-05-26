# Bilinc Cognitive Runtime Implementation Plan

> **For Hermes/Codex:** This is a product-grade implementation plan, not permission to implement. Use `software-development/test-driven-development` before code changes, `verification-before-completion` before done claims, and ReARC approval gates for memory backend, provider/model, live DB, deploy, public-site/pricing, payment, destructive, or production changes.

**Goal:** Make Bilinc function as an automatic agent consciousness runtime: an agent can hold normal conversations while Bilinc observes, recalls, injects context, captures salient outcomes, consolidates memory, and preserves provenance without the end user manually naming memory tools.

**Architecture:** Keep StatePlane as the verifiable memory/state substrate. Add a framework-agnostic cognitive runtime layer above it: turn lifecycle hooks, context assembly, salience/writeback policy, background consolidation, and SDK/framework adapters. MCP remains compatibility/admin/debug tooling, not the primary automatic brain path.

**Tech Stack:** Python 3.10+, existing Bilinc StatePlane, SQLite/PostgreSQL backends, MCP server v2, existing eval/claims/entities/audit/consolidation modules, pytest. Later: TypeScript SDK parity and Cloud HTTP cognitive endpoints.

---

## Concern Classification

Primary concern: `agent-memory`.

Secondary concerns:
- `security-critical`: automatic memory capture can leak sensitive values or over-persist private context if policy is wrong.
- `public-facing`: product/docs/SDK positioning will eventually expose this feature.
- `infra-prod`: hosted Bilinc Cloud runtime may later expose cognitive endpoints.
- `payments`: Cloud packaging/entitlements may later gate hosted retention, audit, eval receipts, or team features.

Approval gates:
- No memory backend switch.
- No provider/model switch.
- No live `/Users/busecimen/bilinc.db` mutation except explicit receipt capture.
- No production deployment.
- No Stripe/payment/pricing mutation.
- No destructive data changes.
- No public marketing claim without fresh verification.
- No schema migration against production/live DB without explicit approval and rollback plan.

Current repo caveat:
- Existing dirty/untracked Cloud work is present and must be preserved:
  - `cloud/README.md`
  - `pyproject.toml`
  - `src/bilinc/cloud/__init__.py`
  - `src/bilinc/cloud/runtime.py`
  - `src/bilinc/cloud/service.py`
  - `tests/test_cloud_runtime.py`
  - `tests/test_cloud_service.py`
  - `AGENTS.md`
- This plan must not overwrite or absorb that work.

---

## Grounded Current State

Existing Bilinc primitives already available:

- `src/bilinc/core/stateplane.py`
  - `StatePlane.commit()`
  - `StatePlane.recall()`
  - `StatePlane.recall_intelligent()`
  - `StatePlane.recall_profiled()`
  - `StatePlane.recall_reflective()`
  - `StatePlane.consolidate()`
  - `StatePlane.summarize_episodic_sessions()`
  - `StatePlane.apply_decay_pass()`
  - `StatePlane.snapshot()` / `diff()` / `rollback()`
  - AGM/KG/belief-sync initialization and AGM commit paths

- `src/bilinc/core/working_memory.py`
  - working-memory slots, heat, priority, promotion to episodic

- `src/bilinc/core/models.py`
  - `MemoryEntry`, `MemoryType`, `Claim`, `ClaimKind`, `CCSDimension`

- `src/bilinc/core/claims.py`
  - deterministic structured claim projection

- `src/bilinc/core/entities.py`
  - entity/backlink projection

- `src/bilinc/eval/*`
  - recall capture/replay and contradiction probes

- `src/bilinc/adaptive/*`
  - budget/forgetting/policy components, currently not fully connected to context assembly

- `src/bilinc/mcp_server/server_v2.py`
  - 20-tool MCP surface, useful but manual-tool oriented

- `src/bilinc/integrations/langgraph.py`
  - current checkpointer integration, but likely API drift exists: it references `state_plane._storage` and a recall signature that does not match current `StatePlane`.

Product reality from Vault/Bilinc:
- Bilinc is source-available verifiable memory/state infrastructure for autonomous agents.
- `bilinc.space` is live with Cloud signup, org/project/credential-gated hosted runtime, usage/billing posture, and Pro/Team checkout.
- Internal Bilinc entitlements/DB are runtime authority; Stripe is payment/subscription sync only.
- Research direction says retrieval is table stakes; Bilinc should win as verifiable state/brain infrastructure.
- Prior research recommended Event Ledger + Eval Receipts, Temporal Claim Graph, Context Assembler, Memory Doctor. This plan reorders the product-facing UX layer: Cognitive Runtime should become the top-level developer experience while ledger/eval remain the proof layer underneath.

---

## Product Decision

Do not make this another MCP tool that the user or agent has to call by name.

Correct product shape:

1. SDK-first automatic cognitive runtime.
2. Framework-native adapters.
3. MCP as compatibility/admin/debug surface.
4. Cloud as hosted memory/state plane with org/project isolation, audit, retention, and eval receipts.

North-star developer experience:

```python
from bilinc import Bilinc

brain = Bilinc.auto(mode="local", path="agent.db")
agent = brain.wrap_agent(agent)

# User now chats normally. Bilinc runs in the turn lifecycle.
```

Cloud shape:

```python
from bilinc import Bilinc

brain = Bilinc.auto(mode="cloud", credential="...")
agent = brain.wrap_agent(agent)
```

The end user should never say “call recall” or “commit_mem”. The agent developer should not need to put 20 tool names into the prompt. Bilinc should sit in the runtime path.

---

## Core Concepts

### 1. Turn lifecycle

A Bilinc-wrapped agent should execute:

1. `on_user_message`
2. `prepare_context`
3. `before_model_call`
4. model/tool loop
5. `observe_tool_event`
6. `after_model_call`
7. `assimilate_response`
8. background consolidation when idle / threshold reached

### 2. Cognitive Workspace

A workspace is the active mental frame for a session/thread/task.

It contains:
- active goal
- current user/session context
- relevant stable facts
- recent episodic timeline
- relevant procedures/preferences
- open commitments
- unresolved contradictions
- uncertainty/gaps
- scope/freshness warnings
- context budget decisions
- provenance references
- writeback plan

### 3. Context packet

Agents should receive a compact packet, not raw memory dumps.

Suggested packet sections:
- `stable_facts`
- `recent_relevant_events`
- `preferences_and_procedures`
- `active_goals_and_open_loops`
- `cautions_and_contradictions`
- `evidence_refs`
- `omitted_counts`
- `writeback_policy_hint`

### 4. Salience / writeback policy

Every turn asks:

> Is this information useful now, later, always, or never?

Policy outputs:
- store or ignore
- memory type
- key
- importance
- TTL
- revision strategy
- provenance metadata
- whether human approval/review is required

### 5. Sync vs async cognition

Synchronous path must be low latency:
- observe turn
- fast/balanced recall
- context assembly
- minimal episodic capture

Async path handles heavier cognition:
- summarization
- semantic promotion
- procedural extraction
- claim projection
- contradiction sweeps
- KG enrichment
- eval receipts
- memory doctor checks

---

## Proposed New Modules

### `src/bilinc/core/cognitive_workspace.py`

Defines:
- `CognitiveWorkspace`
- `WorkspaceFrame`
- `TurnObservation`
- `WorkspaceConfig`
- `WorkspaceMode`

Responsibilities:
- session/thread state
- observe user/assistant/tool turns
- coordinate context assembly
- coordinate salience decisions
- produce workspace frames
- call StatePlane primitives without exposing low-level tools to the agent/user

### `src/bilinc/core/context_assembler.py`

Defines:
- `ContextBundle`
- `ContextSection`
- `ContextAssembler`
- `ContextBudget`

Responsibilities:
- call `StatePlane.recall_profiled()` / `recall_reflective()`
- combine working + episodic + semantic + procedural memory
- include claims/contradictions when profile requires
- rank by relevance, importance, recency, verification, scope, freshness
- enforce token budget deterministically
- return prompt-safe context block with evidence refs

### `src/bilinc/core/salience.py`

Defines:
- `SalienceDecision`
- `MemoryWriteProposal`
- `SalienceEngine`
- `WritebackRouter`

Responsibilities:
- decide whether a turn should be stored
- choose memory type
- generate stable keys
- infer importance/TTL
- identify preference/fact/commitment/procedure candidates
- select `commit` vs `revise` vs no-op
- prevent over-persistence of casual chatter

Default implementation should be deterministic/rule-based. LLM-assisted extraction can be a later optional adapter behind explicit config.

### `src/bilinc/integrations/agent_runtime.py`

Defines:
- `BilincAgentRuntime`
- `AgentTurnResult`
- `ToolEvent`
- `RuntimeAdapterProtocol`

Responsibilities:
- framework-agnostic lifecycle hooks
- `before_model_call(messages, session_id, metadata)`
- `after_model_call(input, output, tool_events)`
- context injection into messages/state
- automatic observation capture
- no dependency on Hermes-specific behavior

### `src/bilinc/integrations/langgraph_workspace.py`

Defines:
- `BilincLangGraphMiddleware`
- optional compatibility with existing `LangGraphCheckpointer`

Responsibilities:
- pre-node context injection
- post-node observation capture
- checkpoint compatibility
- async StatePlane API correctness

### Later modules

- `src/bilinc/core/event_ledger.py`
- `src/bilinc/core/eval_receipts.py`
- `src/bilinc/core/memory_doctor.py`
- `src/bilinc/core/temporal_claims.py`

These are important, but should not block the first automatic UX layer.

---

## API Shape

### Low-level APIs remain

Keep existing primitives:
- commit
- recall
- recall_smart/profiled
- revise
- forget
- consolidate
- claims
- contradictions
- query_graph
- snapshot/diff/rollback

### High-level product APIs

#### Local SDK

```python
from bilinc import CognitiveWorkspace, StatePlane
from bilinc.storage.sqlite import SQLiteBackend

workspace = CognitiveWorkspace(
    state_plane=StatePlane(SQLiteBackend("agent.db"), enable_audit=True),
    agent_id="agent_123",
    default_profile="balanced",
)

context = await workspace.prepare_context(
    session_id="thread_1",
    user_input="What did we decide about pricing?",
    budget_tokens=3000,
)

# caller injects context.prompt_block into the model call

await workspace.assimilate_response(
    session_id="thread_1",
    user_input="What did we decide about pricing?",
    assistant_output="...",
    tool_events=[],
)
```

#### Agent runtime wrapper

```python
from bilinc.integrations.agent_runtime import BilincAgentRuntime

runtime = BilincAgentRuntime.local("agent.db")
agent = runtime.wrap_agent(agent)
```

#### Cloud HTTP endpoint

Future hosted endpoint:

`POST /v1/cognitive/turn`

Input:
- `project_id`
- `agent_id`
- `session_id`
- `messages`
- `tool_events`
- `latency_budget_ms`
- `context_budget_tokens`
- `profile`

Output:
- `augmented_context`
- `memory_actions`
- `workspace_frame_id`
- `audit_refs`
- `warnings`
- `debug` optional

---

## Sprint Plan

### Sprint 0: Feasibility + safety baseline

Objective: confirm current source/test state and avoid trampling existing Cloud work.

Files:
- Read only:
  - `src/bilinc/core/stateplane.py`
  - `src/bilinc/core/working_memory.py`
  - `src/bilinc/core/models.py`
  - `src/bilinc/mcp_server/server_v2.py`
  - `src/bilinc/integrations/langgraph.py`
  - `tests/*`
- Create/modify only this plan/doc if needed.

Verification:
```bash
git status -sb
python3 -m pytest tests/test_core.py tests/test_recall_profiles.py tests/test_claims.py tests/test_entities.py -q
```

No implementation yet.

### Sprint 1: Context Assembler MVP

Objective: produce agent-ready context bundles from existing recall/profile primitives.

Files:
- Create: `src/bilinc/core/context_assembler.py`
- Create: `tests/test_context_assembler.py`
- Modify: `src/bilinc/core/__init__.py` only if export is needed

TDD cases:
- assembles relevant memories from `StatePlane.recall_profiled()`
- includes working + semantic + episodic + procedural sections
- respects `budget_tokens`
- deterministic ordering
- includes evidence refs for selected memory keys
- includes contradiction warnings only for returned memory scope
- does not mutate backend

Definition of done:
- No backend schema change.
- No MCP exposure.
- No live DB mutation.
- Focused tests pass.

### Sprint 2: Salience Engine MVP

Objective: decide what to store and where after a normal conversation turn.

Files:
- Create: `src/bilinc/core/salience.py`
- Create: `tests/test_salience.py`

TDD cases:
- casual chatter -> no write or low-importance episodic
- explicit preference -> semantic/procedural candidate
- task decision -> episodic + semantic candidate
- repeated workflow -> procedural candidate
- temporary state -> working with TTL
- stable key generation is deterministic
- sensitive-value content is not persisted by default or gets redaction warning
- confidence/importance bounded to 0..1

Definition of done:
- Deterministic policy only.
- No LLM dependency.
- No automatic destructive revise/forget.

### Sprint 3: Cognitive Workspace MVP

Objective: combine context assembly and salience into a turn lifecycle.

Files:
- Create: `src/bilinc/core/cognitive_workspace.py`
- Create: `tests/test_cognitive_workspace.py`

TDD cases:
- `prepare_context()` recalls and returns prompt block without explicit tool names
- `observe_user_turn()` records current turn frame in working/episodic policy
- `assimilate_response()` writes only salience-approved memories
- `finalize_turn()` returns retrieved/written keys and warnings
- `end_session()` can call consolidation on temp DB
- no live DB paths are hardcoded

Definition of done:
- Works with in-memory and temp SQLite backends.
- Uses existing StatePlane APIs.
- Does not modify MCP server yet.

### Sprint 4: Agent Runtime Adapter MVP

Objective: make Bilinc usable as an automatic wrapper for generic agents.

Files:
- Create: `src/bilinc/integrations/agent_runtime.py`
- Create: `tests/test_agent_runtime.py`

TDD cases:
- `before_model_call()` injects a memory context block into messages/state
- `after_model_call()` observes output and writes salience-approved memory
- tool events can be observed as episodic evidence
- no low-level Bilinc tool names are required by the end user
- wrapper is framework-agnostic via protocol/stubs

Definition of done:
- Pure SDK/local path.
- No Cloud/HTTP/MCP changes.

### Sprint 5: LangGraph Workspace Adapter

Objective: turn LangGraph into the flagship automatic integration.

Files:
- Create: `src/bilinc/integrations/langgraph_workspace.py`
- Modify: `src/bilinc/integrations/langgraph.py` only if compatibility/fixes are required
- Create: `tests/test_langgraph_workspace.py`

TDD cases:
- no `state_plane._storage` reliance
- async StatePlane APIs respected
- pre-node context injection works
- post-node turn capture works
- checkpointer compatibility remains intact or deprecation path is documented

Definition of done:
- Existing LangGraph checkpointer tests pass or are updated with explicit compatibility rationale.

### Sprint 6: MCP/Admin Preview, not primary UX

Objective: expose workspace preview/status for debugging, not as required runtime path.

Files:
- Modify: `src/bilinc/mcp_server/server_v2.py`
- Create/modify: `tests/test_mcp_server_v2.py`

Possible tools:
- `bilinc_workspace_preview`
- `bilinc_workspace_status`
- `bilinc_workspace_replay_session`

Rules:
- These are optional admin/debug tools.
- They should not become the main product story.
- MCP exposure requires explicit approval before implementation.

### Sprint 7: Event Ledger + Eval Receipts Foundation

Objective: create replayable proof for automatic cognition.

Files:
- Create: `src/bilinc/core/event_ledger.py`
- Create: `src/bilinc/core/eval_receipts.py`
- Modify: `src/bilinc/storage/sqlite.py` only via additive temp-DB-tested schema
- Modify: `src/bilinc/storage/postgres.py` for parity after SQLite passes
- Create: `tests/test_event_ledger.py`
- Create: `tests/test_eval_receipts.py`

Deliverables:
- CloudEvents-compatible memory operation envelope
- append-only event ledger for commit/revise/forget/consolidate/snapshot/claim projection/workspace frames
- read-only replay/export
- eval receipt references event IDs/checkpoint roots

Approval gate:
- Any production/live DB migration requires Atakan approval.

### Sprint 8: Cloud Cognitive Endpoint

Objective: hosted product path for any agent framework.

Files likely in site/cloud repo, not this package alone.

Endpoint:
- `POST /v1/cognitive/turn`

Scope:
- org/project/agent/session isolation
- Credential-gated auth
- entitlement/credit checks
- hosted retention/audit/event ledger

Approval gates:
- Production deployment
- public docs/site/pricing copy
- payment/credit policy changes

---

## Product Packaging

### Self-host/local

Free/source-available path:
- local SQLite state plane
- cognitive workspace
- context assembler
- salience/writeback policy
- local event ledger/export
- local eval receipts

### Cloud Free / Pro / Team / Scale

Paid value should be operational, not philosophical:
- hosted retention
- team/org/project isolation
- signed receipts
- dashboard explorer
- eval history
- memory doctor reports
- audit export
- webhooks/RBAC
- production replay
- longer event retention

Potential entitlement fields later:
- `event_retention_days`
- `workspace_sessions_per_month`
- `eval_receipts_per_month`
- `signed_receipts_enabled`
- `memory_doctor_enabled`
- `audit_export_enabled`
- `max_context_budget_tokens`

Do not create new pricing/SKU until implementation and usage data prove value.

---

## What Not To Do

- Do not make MCP the primary automatic brain path.
- Do not require users to say tool names.
- Do not require agent prompts to list 20 Bilinc tools.
- Do not store every message as permanent semantic memory.
- Do not run expensive claim extraction/contradiction sweeps synchronously on every turn.
- Do not make LLM extraction mandatory or default.
- Do not replace source memories with derived claims.
- Do not dump raw memories into prompts.
- Do not leak sensitive values into context bundles, eval exports, traces, or receipts.
- Do not make Cloud a dependency for local self-host.
- Do not switch backend/provider/model.
- Do not publish unscoped “SOTA” or “proves truth” claims.

---

## Pre-Mortem

### Tigers

1. **Over-persistence pollutes the brain**
   - Mitigation: deterministic salience policy, low default write rate, semantic promotion only after strong signals.

2. **User/private data leaks into prompt context or exports**
   - Mitigation: context assembler redaction hooks, scope filters, no raw memory dumps, privacy tests.

3. **Latency kills normal chat flow**
   - Mitigation: sync path is only recall/context/minimal observe; heavy work is async.

4. **MCP-first design fails the invisible-brain UX**
   - Mitigation: SDK/runtime is primary, MCP is debug/admin.

5. **Framework lock-in weakens product adoption**
   - Mitigation: framework-agnostic runtime protocol first, LangGraph as adapter not core.

6. **Existing Cloud/runtime work gets broken**
   - Mitigation: keep first sprints core-local, no Cloud file edits, preserve dirty files.

### Elephants

1. Bilinc’s current product narrative is strong but the developer UX still looks like tools, not consciousness.
2. Automatic memory is dangerous if salience is bad; the hardest part is deciding what not to remember.
3. “Human brain” positioning is only credible if Bilinc has attention + consolidation + writeback, not just recall.

### Paper Tigers

1. CodeGraph-style impact/projection is useful but not required for the first automatic brain UX.
2. Event ledger is valuable, but it should prove/observe the cognitive runtime rather than block the first context assembler.

---

## Recommended Immediate Next Step

If Atakan approves implementation direction, start with:

`Sprint 1: Context Assembler MVP`

Reason:
- lowest-risk path toward automatic agent brain
- no schema migration
- no MCP exposure
- no Cloud/deploy/payment changes
- directly converts existing `recall_profiled`, claims, contradictions, and memory types into an agent-ready mental frame

Then:
1. Salience Engine
2. Cognitive Workspace
3. Agent Runtime Adapter
4. LangGraph adapter
5. Event Ledger + Eval Receipts
6. Cloud cognitive endpoint

This sequence makes Bilinc feel like a brain before adding heavier proof/governance layers.
