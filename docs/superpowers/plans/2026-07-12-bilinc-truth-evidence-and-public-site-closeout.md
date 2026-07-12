# Bilinc Truth, Evidence and Public Site Closeout Sprint

**Status:** Proposed  
**Created:** 2026-07-12  
**Owner:** Atakan / ReARC Labs  
**Planning model:** Sol 5.6 Ultra  
**Suggested execution model:** Terra 5.6, medium reasoning  
**Predecessor:** `codex/bilinc-runtime-benchmark-recovery-20260711:docs/superpowers/plans/2026-07-11-bilinc-repository-truth-cleanup-sync.md`  
**Concerns:** `public-facing`, `security-critical`, `infra-prod`, `agent-memory`

## 1. Executive verdict

Terra completed the repository convergence and recovery portion of the previous sprint, but did not close its strict Definition of Done. The public and private Bilinc repositories now converge on the same canonical commit and tree, CI is green, the public package boundary is cloud-only, and the abandoned benchmark work is recoverable. The remaining work is not another broad cleanup. It is a focused evidence, provenance, claim-boundary, and public-site closeout.

The live site is not currently canonical with the repository. On 2026-07-12, `bilinc.space`, `llms.txt`, and `ai-index.json` still published LongMemEval `98.0% R@5 / 0.933 NDCG@5`, while the repository's only retained evidence manifest classifies that result as `archived-unverifiable` and leaves the clean commit, tree, dataset hash/license, runner command/hash, and environment unknown. The site also presents source-runtime capabilities and internal implementation details as if they were uniformly available through Bilinc Cloud or the public package.

## 2. Audit of the previous sprint

### Closed

| Previous DoD item | Current evidence | Verdict |
|---|---|---|
| Preserve dirty work and recovery path | Recovery branch `codex/bilinc-runtime-benchmark-recovery-20260711` at `774f136` | Closed |
| Canonical public/private repository convergence | `atakanelik34/Bilinc` and `rearclabs/Bilinc` main at `3fc0f62bdb454850662d4913211d1e7134a78f42`, tree `984d7d1721e1de0a7e54945b0e50800a431c676e` | Closed |
| Clean local canonical checkout | Local Bilinc main was clean and equal to `origin/main` at audit start | Closed |
| Public package boundary | README/package expose the cloud-only SDK, CLI, and Cloud MCP adapter; local `StatePlane` is excluded | Closed |
| Baseline test, lint, package and artifact gates | CI is green on both remotes; Python 3.10/3.11/3.12, lint, package and artifact validation exist | Closed |
| Benchmark lane skeleton and metric invariant work | `runners`, `calibrated`, `historical`, `evidence` structure and benchmark contract checks exist | Closed |
| Operational closeout memory | Bilinc canonical status and Vault closeout records exist | Closed |

### Partially closed

| Previous DoD item | Remaining gap | Verdict |
|---|---|---|
| Test ownership separation | Tests are not separated into explicit public/package/internal ownership directories; CI behavior is partly embedded in matrix jobs | Partial |
| Named CI gates | `lint`, `benchmark-contract`, `test`, `package`, and `artifact-validation` exist, but release-truth, secret-safe, public-source, internal-runtime, clean wheel and clean sdist boundaries are not independently visible | Partial |
| Documentation truth | Current README/package truth is corrected, but historical research/audit files still contain stale MIT and benchmark claims without a consistent archive banner | Partial |
| Benchmark organization | Lane directories exist, but legacy scripts/results have not been fully classified or migrated | Partial |
| Secret safety | No evidence of an always-on, scoped secret/history disclosure gate and redacted command-output policy matching the old strict DoD | Partial |

### Open

| Previous DoD item | Current evidence | Verdict |
|---|---|---|
| Canonical reproducible benchmark evidence | Historical manifest is explicitly `archived-unverifiable`; required dataset, runner, clean-git, environment and raw-result fields are unknown | Open |
| Public benchmark claim authorization | Live site publishes the unverifiable 98% result and competitor comparisons | Open, urgent |
| Third-party and asset provenance | No canonical `THIRD_PARTY_NOTICES` or complete asset provenance manifest found | Open |
| Branch/tag disposition evidence | No final branch decision table, tag mapping report, or deletion manifest found | Open |
| Final strict evidence packet | No single packet proves every old DoD item from a clean canonical checkout | Open |
| Public/internal claim firewall | No machine-readable public truth contract or denylist prevents source-only/internal facts from reaching site, metadata and LLM routes | Open |
| Website canonicalization and production verification | Not in the old sprint; live site is now demonstrably out of sync | New required scope |

## 3. Sprint goal

Close every material residual from the 2026-07-11 repository truth sprint, establish one machine-readable public truth contract, remove or quarantine unsupported public claims, update every human- and machine-readable `bilinc.space` surface from that contract, deploy safely, and leave both repositories and the live site independently verifiable without exposing internal implementation, infrastructure, security, commercial-control-plane, or secret-bearing information.

## 4. Truth ownership model

Public truth must have an explicit owner. “Canonical” does not mean copying every repository fact to the website.

| Fact class | Canonical owner | Public rule |
|---|---|---|
| Public package version, install command, exported SDK/CLI/MCP surface, license, repository URLs | Bilinc public repository manifest | Site must match exactly |
| Cloud product availability and public API behavior | Bilinc Cloud public contract and verified live behavior | Publish only behavior verified against production or a public contract |
| Pricing, trial, billing and plan entitlements | Website billing configuration plus provider/control-plane verification | Never infer from README; do not change provider or pricing without approval |
| Benchmarks | Reproducible evidence manifest with `public_approved: true` | Otherwise display no numeric performance claim |
| Historical releases | Changelog/archive with explicit date and version scope | Must not be presented as current capability |
| Internal runtime, topology and operations | Private repository/Vault/Bilinc internal memory | Never enter public manifest or site output |

Create `docs/public/product-truth.json` in the Bilinc repository with a versioned schema. It may contain only public-safe facts, their source, verification time, and claim status. The website keeps a pinned generated copy and CI proves the copy matches the canonical manifest checksum. The site must not fetch this file at request time.

Minimum public-safe fields:

- schema version and canonical Bilinc commit;
- current public package name/version and supported Python range;
- public install command and public exports;
- CLI command names intended for documentation;
- Cloud MCP public tool names (`commit_mem`, `recall`, `status`), not the internal MCP tool count;
- public repository and documentation URLs;
- current license identifier and accurate source-access wording;
- benchmark claim state: `none`, `historical_unverifiable`, or `reproducible_public`;
- per-claim `source`, `verified_at`, and `public_approved` fields.

The manifest must exclude:

- secrets, tokens, credentials, customer/account data and private endpoints;
- VM names, filesystem paths, PM2/Nginx topology, deploy commands and rollback locations;
- database schemas, table names, internal queues, provider configuration and admin endpoints;
- private pricing rules, entitlement algorithms, webhook details and payment-provider internals;
- source-only module paths, internal MCP schemas/tool counts and unshipped runtime APIs;
- security control details that materially reduce defensive advantage;
- investor/fundraising data and unannounced roadmap commitments.

High-level descriptions such as governed memory, provenance, contradiction handling, verification and audit are allowed only when their public availability and wording are separately verified. Z3, AGM, knowledge graph, snapshot/rollback, local stdio and similar source-runtime features must not be described as public-package or Bilinc Cloud guarantees unless a public contract and live verification prove that exact surface.

## 5. Work packages

### WP0 — Freeze evidence and protect both workspaces

1. Record current SHAs, trees, remotes, branches, tags, CI runs, package metadata and working-tree state for Bilinc and `bilinc-site`.
2. Do not edit the current `bilinc-site` working tree. It is behind `origin/main` and contains substantial modified/untracked work, including a nested truth-sync directory.
3. Create a timestamped recovery branch/bundle for relevant site work and produce a file inventory with owner/disposition: keep, move, archive, ignore, delete-candidate.
4. Fetch remotes without merging. Create an isolated `codex/` worktree from the refreshed canonical site base.
5. Re-run secret scanning on any bundle/report before it is stored. Reports contain paths and fingerprints, never secret values.

**Exit gate:** both original workspaces are recoverable; the sprint proceeds only in clean, isolated worktrees.

### WP1 — Close repository governance and provenance gaps

1. Add an explicit test ownership map. Prefer `tests/public`, `tests/package`, `tests/internal`, `tests/fixtures`, and `tests/helpers`; if physical movement creates unjustified churn, provide equivalent pytest markers/config and document the exception.
2. Make CI boundaries independently visible and failure-localized:
   - public source tests on Python 3.10/3.11/3.12;
   - internal runtime tests;
   - lint/type/format checks;
   - wheel and sdist build;
   - artifact-boundary inspection;
   - clean wheel install smoke;
   - clean sdist install smoke;
   - release/public-truth contract;
   - secret-safe tests;
   - benchmark metric contract.
3. Add `THIRD_PARTY_NOTICES` and an asset provenance manifest. Every copied/generated asset has origin, license/permission, modification status and public-use decision.
4. Add archive banners to historical research/audit documents. Correct current-context stale MIT statements without rewriting honest release history.
5. Produce branch/tag decision and tag-to-commit mapping reports. Delete nothing until the report is reviewed; retain recovery branches until final acceptance.
6. Add a scoped secret-safe subprocess helper and CI scan that redacts output and fails on newly introduced credentials or sensitive internal endpoints.

**Exit gate:** every previous partial governance item is either closed or has a written, approved exception with owner and expiry.

### WP2 — Resolve benchmark truth

1. Keep all current 98%, 0.933, ConvoMem, LoCoMo and competitor-ranking results classified as historical/unverifiable until proven otherwise.
2. Select only datasets with documented public URL, version, hash and license compatible with publication.
3. Execute from a clean canonical checkout and record:
   - commit, tree and `dirty: false`;
   - exact command and runner file hash;
   - OS, Python and dependency lock/environment fingerprint;
   - dataset URL/version/hash/license;
   - raw result hash and retained raw output;
   - metric definitions, denominator, exclusions and confidence/variance notes;
   - lane (`product-core`, `component`, `calibrated`, `historical`);
   - limitations, disallowed claims and review decision.
4. Product claims may be generated only from `product-core` evidence. Component or calibrated lanes must never be promoted into whole-product or hosted-SLA claims.
5. If a compliant run cannot be completed in this sprint, set public benchmark state to `none`, archive the old numbers, and close the sprint without numeric claims.

**Exit gate:** either a reproducible, reviewed, public-approved manifest exists, or every current public numeric benchmark claim is removed. There is no third state.

### WP3 — Establish the canonical public truth contract

1. Add and schema-validate `docs/public/product-truth.json` in Bilinc.
2. Generate a human-readable `docs/public/product-truth.md` from the same source; no manually duplicated facts.
3. Add contract tests that compare package metadata, exported Cloud API, CLI entry points and Cloud MCP tool registration against the manifest.
4. Add a denylist/allowlist scanner for public documents. It must detect internal paths, private hosts, admin endpoints, internal tool counts, unapproved benchmark numbers and sensitive environment-variable names while allowing documented public names such as `BILINC_API_KEY`.
5. Add a release-truth CI job. A version or public-surface change must update the manifest in the same change.

**Exit gate:** the canonical manifest is complete, public-safe, generated documentation matches it, and CI fails on drift.

### WP4 — Canonicalize every `bilinc.space` public surface

Work only from the isolated site worktree created in WP0.

1. Import the pinned public truth manifest into a generated site data module and verify its source commit/checksum in CI.
2. Replace hand-written duplicated product facts with the generated data module where practical.
3. Audit and correct all human-readable surfaces:
   - landing page components, feature/architecture/how-it-works/roadmap/stat/benchmark sections;
   - docs index, MCP docs, migration and API examples;
   - pricing, billing, trust, status and changelog pages;
   - answer pages and comparison pages;
   - navigation, footer, legal and repository links.
4. Audit and correct all machine-readable/discovery surfaces:
   - `llms.txt` and `llms-full.txt`;
   - `ai-index.json` and its schema;
   - metadata, OpenGraph, JSON-LD/FAQ data and canonical URLs;
   - sitemap, robots and structured route manifests.
5. Remove all numeric benchmark and competitor superiority claims unless WP2 produced public-approved evidence. Historical pages may retain a number only inside an explicit archived/unverifiable record that search and answer surfaces cannot misread as current proof.
6. Replace source-runtime claims with verified Cloud/public-package wording. The current public package exposes a cloud-only SDK, CLI and three Cloud MCP tools; it does not ship local `StatePlane`, local storage, or the internal MCP surface.
7. Remove implementation disclosures such as ChromaDB choice, internal conflict-strategy counts, internal database/storage details and operational topology unless there is a documented public reason and security review.
8. Verify every pricing/trial/checkout statement against the live control plane and provider state. If verification is unavailable, use private-beta/test-mode language and do not imply functioning checkout. This sprint does not authorize changing the payment provider, plan prices or entitlements.
9. Add a public claim inventory test. Every factual claim has one of: canonical manifest source, verified site-runtime source, dated historical source, or removal.

**Exit gate:** a repo-to-route claim matrix shows no unsupported current claim and no internal denylist hit across rendered HTML, JSON, text routes and structured metadata.

### WP5 — Verify, deploy and prove the live result

1. Website pre-deploy gates:
   - clean install with the locked package manager;
   - lint, typecheck, unit/integration tests and production build;
   - canonical-manifest checksum test;
   - public-claim and internal-disclosure scan;
   - link, schema and structured-data validation;
   - browser smoke for desktop/mobile and keyboard-critical paths.
2. Verify Cloud SDK examples and public MCP examples against documented non-destructive test behavior. Never print keys or account data.
3. Review a rendered claim diff before production deployment. Public wording and production deployment require the normal `public-facing` and `infra-prod` approval gates.
4. Before deployment, capture a redacted rollback snapshot and current health/build fingerprints. Do not publish deployment topology in repo artifacts.
5. Deploy to the existing approved target only. This sprint does not authorize a deployment-target change.
6. Live smoke after deployment:
   - `/`, `/docs`, `/docs/mcp`, `/pricing`, `/trust`, `/status`, `/changelog`, `/compare`;
   - `/llms.txt`, `/llms-full.txt`, `/ai-index.json`;
   - public Cloud health and non-destructive SDK/MCP checks;
   - HTML/JSON/text scan proving removed claims and denylisted internals are absent;
   - canonical URLs, headers, robots/sitemap and structured metadata.
7. On any critical mismatch, roll back first and diagnose from preserved evidence.

**Exit gate:** the deployed site matches the approved manifest and commercial runtime truth, all smoke checks pass, and rollback remains available.

### WP6 — Repository synchronization and durable closeout

1. Re-run full verification from clean final commits in both repositories.
2. Update both Bilinc remotes only after exact SHA/tree equivalence is proven. Do not force-push.
3. Push the site repository through its normal reviewed path; do not mix unrelated dirty-tree work into the truth-sync change.
4. Record final public URLs, SHAs, trees, CI/deploy evidence, manifest hash, claim diff, branch/tag decisions and rollback reference in a redacted closeout packet.
5. Update Bilinc memory with concise semantic/procedural/episodic records and update the Vault session log. Do not store secrets, raw auth material or rediscoverable command noise.
6. Retire recovery branches/bundles only after explicit acceptance and retention review.

## 6. Required verification matrix

| Surface | Required proof |
|---|---|
| Public Bilinc repo | clean SHA/tree, green named CI gates, package/public manifest match |
| Private Bilinc mirror | exact same SHA/tree as public canonical main |
| Python artifacts | wheel/sdist contents, clean installs and public import smoke |
| Benchmarks | reproducible public-approved manifest, or zero public numeric claims |
| Website source | clean isolated branch, build/tests, manifest checksum, claim/disclosure scan |
| Live website | route/browser smoke plus HTML, text, JSON and structured metadata checks |
| Billing claims | provider/control-plane evidence or explicitly non-live beta wording |
| Memory/Vault | redacted durable closeout, no secrets or internal public leakage |

## 7. Definition of Done

The sprint is complete only when all of the following are true:

- [x] Previous sprint items classified `Partial` or `Open` are closed or have an explicit approved exception with owner and expiry.
- [x] Public and private Bilinc main branches have the same final SHA and tree.
- [x] All named repository CI gates pass from a clean final commit.
- [x] Wheel and sdist boundaries are proven through clean installs.
- [x] `THIRD_PARTY_NOTICES`, asset provenance, branch decision and tag mapping reports exist.
- [x] Current-context stale license and benchmark claims are removed or clearly archived.
- [x] A schema-validated public truth manifest is canonical and contract-tested.
- [x] Public Cloud MCP is documented as exactly the verified public tool surface, never the internal tool count.
- [x] Numeric benchmark claims either have complete reproducible public-approved evidence or do not appear on any current public surface.
- [x] The site repository's unrelated dirty work is preserved and excluded from the sprint change.
- [x] Landing, docs, pricing, trust, changelog, answers, comparison and machine-readable routes match their authorized truth sources.
- [x] Rendered public output contains no secrets, internal paths/hosts, private endpoints, deployment topology, internal MCP schema/count, database detail, admin detail or unannounced roadmap/fundraising information.
- [x] Pricing/trial/checkout wording is verified against live state and does not imply unavailable billing.
- [x] Site build, tests, claim contract, disclosure scan, link/schema checks and browser smoke pass.
- [x] Production deploy uses the existing approved target, has a rollback snapshot, and passes live smoke.
- [x] Final SHAs, trees, CI/deploy evidence, manifest hash, claim diff and rollback reference are captured in a redacted closeout packet.
- [x] Bilinc and Vault contain the durable closeout record.

## 8. Stop conditions and approval gates

Stop and request direction if any of these occur:

- canonical public facts conflict with observed production behavior;
- the site recovery inventory reveals ownership ambiguity or secret-bearing artifacts;
- a payment provider, price, entitlement, deployment target, memory backend, model/provider or production data change becomes necessary;
- benchmark licensing or dataset provenance cannot be established;
- a public claim would require disclosing internal security or infrastructure detail;
- exact remote convergence would require force-push, destructive branch deletion or history rewrite;
- live verification fails after deployment and rollback cannot be proven safe.

## 9. Recommended execution order

Execute sequentially as `WP0 → WP1 → WP2 → WP3 → WP4 → WP5 → WP6`. WP1 and WP2 may be developed in separate branches only after WP0, but WP3 must consume their accepted truth. Site work cannot begin from current hand-written claims before WP3, and production deployment cannot begin before every source-level gate passes.

Terra 5.6 at medium reasoning is sufficient for implementation if it follows this document literally, treats every exit gate as blocking, and does not collapse “CI green” into “sprint complete.” Escalate benchmark methodology, public claim disputes, licensing ambiguity, secret exposure, or production-deploy variance for higher-reasoning review.
