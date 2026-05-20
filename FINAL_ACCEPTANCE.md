# BILINC 2.0 - Final Acceptance Gate

Use this only at the end of the Bilinc 2.0 cloud-only release process. If any item below is not true, do not publish the package.

## Public Package Surface

- [ ] `import bilinc` succeeds from a clean environment.
- [ ] `bilinc.version == "2.0.0"`.
- [ ] `from bilinc import CloudClient, Bilinc, BilincApiKeyRequired, BilincCloudError` succeeds.
- [ ] `Bilinc is CloudClient`.
- [ ] `StatePlane` is not exported by the public package.
- [ ] No local runtime package is shipped: `core`, `storage`, `eval`, `observability`, `integrations`, `mcp_server`, `adaptive`, `retrieval`, `security`, or `jobs`.

## Hosted API Contract

- [ ] `CloudClient.commit(...)` uses `POST /api/cloud/memory/commit`.
- [ ] `CloudClient.recall(...)` uses `POST /api/cloud/memory/recall`.
- [ ] `CloudClient.status()` uses `GET /api/cloud/health`.
- [ ] Missing API key errors point users to `https://bilinc.space/signup`.
- [ ] No API key is printed in normal errors or docs examples.
- [ ] No authenticated live commit/recall smoke is run during release validation without explicit approval.

## CLI And MCP

- [ ] `bilinc --version` prints `bilinc 2.0.0`.
- [ ] `bilinc signup` prints the 7-day trial URL.
- [ ] `bilinc commit ...` without `BILINC_API_KEY` fails cleanly and points to signup.
- [ ] `bilinc recall ...` without `BILINC_API_KEY` fails cleanly and points to signup.
- [ ] `python -m bilinc.cloud_mcp` remains the public MCP adapter entrypoint.
- [ ] Importing `bilinc.cloud_mcp` does not require `BILINC_API_KEY` at import time.

## Artifact Validation

- [ ] `python3 -m build` succeeds.
- [ ] Wheel install succeeds in a clean virtualenv.
- [ ] Sdist install succeeds in a clean virtualenv.
- [ ] Wheel and sdist leak checks confirm forbidden local runtime paths are absent.
- [ ] Wheel metadata has no dependency on `z3-solver`, `networkx`, or `pydantic` unless a future cloud-only change explicitly requires it.

## Documentation Validation

- [ ] README describes Bilinc 2.0 as cloud-only.
- [ ] Release checklist uses hosted SDK/CLI smoke, not old `--db` or `StatePlane` smoke.
- [ ] Legacy/private runtime docs are labeled as legacy/private.
- [ ] Public quickstarts do not present SQLite/PostgreSQL/local StatePlane as the Bilinc 2.0 PyPI path.
- [ ] Changelog does not call v2.0 the latest published package until PyPI publish completes.

## Final Commands

Run before requesting publish approval:

```bash
python3 -m pip install -e '.[dev]'
PYTHONPATH=src python3 -m pytest -q -o 'addopts='
python3 -m build
BILINC_TEST_WHEEL=dist/bilinc-2.0.0-py3-none-any.whl \
BILINC_TEST_SDIST=dist/bilinc-2.0.0.tar.gz \
PYTHONPATH=src python3 -m pytest -q -o 'addopts='
```

Clean install smoke:

```bash
python3 -m venv /tmp/bilinc-2-release-smoke
/tmp/bilinc-2-release-smoke/bin/pip install dist/bilinc-2.0.0-py3-none-any.whl
env -u PYTHONPATH -u BILINC_API_KEY /tmp/bilinc-2-release-smoke/bin/python -c "import bilinc; print(bilinc.version)"
env -u BILINC_API_KEY /tmp/bilinc-2-release-smoke/bin/bilinc --version
env -u BILINC_API_KEY /tmp/bilinc-2-release-smoke/bin/bilinc signup
env -u BILINC_API_KEY /tmp/bilinc-2-release-smoke/bin/bilinc commit --key smoke_key --value hello
```

The final command should fail cleanly with signup guidance. Do not publish if it tracebacks.
