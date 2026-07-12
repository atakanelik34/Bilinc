"""Explicit ownership lanes for public-package and internal-runtime tests."""

from __future__ import annotations

from pathlib import Path

import pytest


PUBLIC_SOURCE_FILES = {
    "test_cloud_only_package.py",
    "test_public_truth_contract.py",
    "test_secret_safety.py",
    "test_test_ownership.py",
}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "public_source: public package and truth-contract boundary")
    config.addinivalue_line("markers", "internal_runtime: source-only runtime behavior")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        filename = Path(str(item.fspath)).name
        item.add_marker("public_source" if filename in PUBLIC_SOURCE_FILES else "internal_runtime")
