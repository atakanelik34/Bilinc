# Branch and tag disposition

**Reviewed:** 2026-07-12

| Ref class | Ref | Decision | Rationale |
|---|---|---|---|
| Canonical public main | `origin/main` | Retain | Public source of truth |
| Canonical private mirror | `rearclabs/main` | Retain | Exact mirror of public canonical main |
| Recovery | `codex/bilinc-runtime-benchmark-recovery-20260711` | Retain pending acceptance | Preserves pre-cleanup recovery evidence |
| Closeout work | `codex/bilinc-truth-site-closeout-plan` | Retain until closeout acceptance | Contains this truth-contract/governance closeout |
| Release tag | `v2.1.4` | Retain | Published package release reference |

No branch or tag is deleted by this sprint. Any later deletion requires an
updated inventory, explicit retention decision, and confirmation that recovery
bundles remain readable.
