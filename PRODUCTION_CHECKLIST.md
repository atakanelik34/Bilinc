# BILINC 2.0 - Cloud-Only Release Checklist

Use this checklist for the public PyPI package. Bilinc 2.0 ships a thin SDK, CLI, and MCP adapter for hosted Bilinc Cloud. It does not ship local StatePlane/storage/server internals.

## 1. Package Surface

- [ ] `pyproject.toml` version is `2.0.0`.
- [ ] Package discovery includes only `bilinc` and `bilinc.cli`.
- [ ] Public exports are limited to cloud-facing SDK objects and errors.
- [ ] `Bilinc` remains an alias for `CloudClient`.
- [ ] No public import path points at `bilinc.core`, `bilinc.storage`, `bilinc.mcp_server`, or other removed local runtime modules.

Verification:

```bash
python3 -c "import bilinc; print(bilinc.version)"
python3 -c "from bilinc import CloudClient, Bilinc; print(CloudClient is Bilinc)"
```

## 2. Hosted API Contract

- [ ] `CloudClient.commit` posts to `/api/cloud/memory/commit`.
- [ ] `CloudClient.recall` posts to `/api/cloud/memory/recall`.
- [ ] `CloudClient.status` gets `/api/cloud/health`.
- [ ] Default base URL is `https://bilinc.space`.
- [ ] `base_url` is normalized without trailing slash duplication.
- [ ] Missing key errors include `https://bilinc.space/signup`.

Verification:

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_cloud_only_package.py
curl -sS -i https://bilinc.space/api/cloud/health
```

Do not call authenticated commit/recall endpoints during release validation without explicit approval.

## 3. CLI And MCP Adapter

- [ ] `bilinc --version` works.
- [ ] `bilinc signup` works without an API key.
- [ ] `bilinc commit` and `bilinc recall` use `BILINC_API_KEY` unless `--api-key` is passed.
- [ ] Missing-key CLI failures are clean nonzero exits without traceback.
- [ ] `bilinc.cloud_mcp` imports without requiring `BILINC_API_KEY`.
- [ ] `bilinc.cloud_mcp` does not import the legacy local MCP server.

Verification:

```bash
env -u BILINC_API_KEY bilinc signup
env -u BILINC_API_KEY bilinc commit --key smoke_key --value hello
env -u BILINC_API_KEY python3 -c "import bilinc.cloud_mcp; print('ok')"
```

The commit command should fail cleanly with signup guidance.

## 4. Artifact Safety

- [ ] `python3 -m build` succeeds from a clean tree.
- [ ] Wheel includes only the cloud package files plus dist-info/license metadata.
- [ ] Sdist excludes local runtime source directories.
- [ ] No `.env`, database, cache, local credential, or private note is included in artifacts.
- [ ] Metadata dependencies do not include local-runtime dependencies such as `z3-solver`, `networkx`, or `pydantic`.

Verification:

```bash
rm -rf dist build src/*.egg-info
python3 -m build
BILINC_TEST_WHEEL=dist/bilinc-2.0.0-py3-none-any.whl \
BILINC_TEST_SDIST=dist/bilinc-2.0.0.tar.gz \
PYTHONPATH=src python3 -m pytest -q -o 'addopts='
```

## 5. Documentation Truth

- [ ] README states the 2.0 package is cloud-only.
- [ ] Quickstart points to trial signup, API key creation, and CloudClient.
- [ ] Release docs do not use old `StatePlane` or `--db` smoke.
- [ ] Legacy/private runtime docs are clearly labeled.
- [ ] Changelog keeps v1.2.5 as latest published until v2.0 is actually published.

Verification:

```bash
rg -n "from bilinc import StatePlane|--db|mcp_server\\.server_v2|SQLite|PostgreSQL" README.md docs FINAL_ACCEPTANCE.md PRODUCTION_CHECKLIST.md
```

Any match must either be in a clearly marked legacy/private document or historical changelog context.

## 6. Approval Gates

Do not perform these without explicit approval:

- Push branch.
- Open PR.
- Publish to PyPI.
- Yank a PyPI release.
- Deploy `bilinc.space`.
- Run authenticated live commit/recall smoke against production.
