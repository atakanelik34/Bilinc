# Bilinc truth closeout packet

**Status:** Source, CI, deployment, and public contract verified  
**Date:** 2026-07-12

## Canonical repositories

| Repository | Main commit | Tree |
|---|---|---|
| `atakanelik34/Bilinc` | `bdf87b43d0557dc15a289b117d5d497ac2c92cb7` | `a071e358e562ff594b7dc9bb09c957593e50d44a` |
| `ReARCLabs/Bilinc` | `bdf87b43d0557dc15a289b117d5d497ac2c92cb7` | `a071e358e562ff594b7dc9bb09c957593e50d44a` |

## CI and artifacts

- Public CI run: `29205039092` — successful.
- Mirror CI run: `29205040238` — successful.
- Python 3.10, 3.11, and 3.12 public-source and internal-runtime gates passed.
- Package build and artifact validation passed; wheel and sdist were installed
  in clean CI environments and checked for the cloud-only boundary.
- Local final suite: `413 passed, 7 skipped`; Ruff clean.

## Public truth and evidence

- Canonical manifest: `docs/public/product-truth.json`.
- Public Cloud MCP surface: `commit_mem`, `recall`, `status`.
- Numeric benchmark and competitor-performance claims are not public-approved.
- `THIRD_PARTY_NOTICES`, asset provenance, branch disposition and tag mapping
  reports are present in this repository.

## Production deployment

- Site source commit: `ebc63cc4de7fb2e1a5a6889c1e51777f1a4036f2`.
- Existing target retained: `/home/busecimen/apps/bilinc-site`, PM2 app
  `bilinc-site`.
- Rollback archives retained on the approved VM under
  `/home/busecimen/backups/` with the `truth-closeout-20260712-182749` label.
- Nginx static AI endpoints and Next.js routes were refreshed.
- Cloudflare zone cache was purged after static content deployment.
- External checks returned `200` for landing, docs, pricing, trust, status,
  changelog, comparison, `llms.txt`, `llms-full.txt`, and `ai-index.json`.
- Rendered claim scan found no prohibited numeric benchmark, internal runtime,
  internal MCP-count, database, or deployment-detail claim.
