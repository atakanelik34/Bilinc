# Release Checklist

Use this checklist for any Bilinc release candidate or PyPI publish.

## Pre-release

1. Confirm working tree is intentional and free of accidental artifacts.
2. Update version and changelog together.
3. Re-run the production gate locally:
   - `python -m pip install -e '.[dev]'`
   - `PYTHONPATH=src pytest -q tests/`
   - `python -m build`
4. Confirm docs match runtime truth:
   - README
   - MCP docs
   - security docs
   - observability docs
   - operator runbook

## Artifact Validation

1. Build artifacts:

```bash
python -m build
```

2. Validate wheel install in a clean virtualenv:

```bash
python -m venv .venv-wheel
. .venv-wheel/bin/activate
pip install --upgrade pip
pip install dist/*.whl
python -c "import bilinc; print(bilinc.__version__)"
```

3. Validate sdist install in a second clean virtualenv:

```bash
python -m venv .venv-sdist
. .venv-sdist/bin/activate
pip install --upgrade pip
pip install dist/*.tar.gz
python -c "import bilinc; print(bilinc.__version__)"
```

## Pre-publish Smoke

```bash
bilinc --db ./tmp.db commit --key smoke_key --value hello
bilinc --db ./tmp.db recall --key smoke_key
```

HTTP deployment smoke:

- authenticated `/health`
- authenticated `/metrics`

## Publish

1. Create tag for the release commit.
2. Publish to PyPI using the approved maintainer flow.
3. Verify the published package page and artifact availability.

## Post-publish Verification

1. Fresh clone in a clean environment.
2. `pip install bilinc` or `pip install bilinc==<version>`.
3. Import smoke:

```bash
python -c "import bilinc; print(bilinc.__version__)"
python -c "from bilinc import StatePlane; print(type(StatePlane()).__name__)"
```

4. If HTTP surface is part of the release notes, verify:
   - authenticated requests succeed and unauthenticated ones fail
   - `/health` returns readiness/liveness
   - `/metrics` exposes `bilinc_` metrics
