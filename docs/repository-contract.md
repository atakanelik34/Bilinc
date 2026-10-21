# Bilinc Repository Contract

## What ships

`pip install bilinc` installs the Cloud SDK, hosted CLI and Cloud MCP adapter.
Use `CloudClient`, `bilinc login`, `bilinc quicktest` and `bilinc.cloud_mcp` for
the public supported path.

## What is source-only

The StatePlane runtime, SQLite/PostgreSQL backends, local MCP server, scheduler,
evaluation, observability, integrations and Cloud sidecar live in this repository
but are not part of the public wheel or sdist. Import them only from a source/runtime
checkout and label related docs/tests as internal.

## Remote policy

- Core development upstream: `atakanelik34/Bilinc` (public for now; it becomes private later).
- Exact private mirror: `ReARCLabs/bilinc-core` (renamed from `ReARCLabs/Bilinc` on 2026-10-21).
- Public package source: `ReARCLabs/bilinc` (renamed from `ReARCLabs/bilinc-python`). It holds exactly what PyPI publishes and is synced from each release's sdist; it is the `canonical_repository` in `docs/public/product-truth.json`.
- `github.com/ReARCLabs/Bilinc` now resolves to the public package repository. Never push core history there; the `rearclabs` remote must point at `bilinc-core`.
- No force-push, independent cherry-pick or tag rewrite.
- Merge canonical work first; mirror the exact resulting commit after its checks pass.

## Test commands

- Public package boundary: `python3 -m pytest -q tests/test_cloud_only_package.py`
- Internal runtime: `python3 -m pytest -q tests/`
- Lint: `python3 -m ruff check src tests benchmarks`
- Package: `python3 -m build && python3 -m twine check dist/*`

## Benchmark evidence

Scratch runs belong under ignored `benchmarks/runs/`. Committed evidence requires a
clean commit SHA, dataset source/license/hash, exact command, metric definitions and
one of: `product-core`, `component`, `calibrated`, `historical`, or `invalid`.

## Approval gates

Never force-push, rewrite tags/history, delete data, publish to PyPI, deploy Bilinc
Cloud, mutate the live Bilinc DB or make public performance claims without Atakan's
explicit approval and verification evidence.
