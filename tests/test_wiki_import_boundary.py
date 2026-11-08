"""The wiki package ships in the public wheel, so it may import only public code."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
WIKI_FILES = sorted((SRC / "bilinc" / "wiki").glob("*.py"))
FORBIDDEN = (
    "bilinc.adaptive",
    "bilinc.cloud",
    "bilinc.core",
    "bilinc.embeddings",
    "bilinc.eval",
    "bilinc.integrations",
    "bilinc.jobs",
    "bilinc.mcp_server",
    "bilinc.observability",
    "bilinc.retrieval",
    "bilinc.scheduler",
    "bilinc.security",
    "bilinc.storage",
    "networkx",
    "numpy",
)


def _imports(path: Path) -> list[str]:
    names = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = "bilinc.wiki".rsplit(".", node.level - 1)[0]
                names.append(f"{base}.{node.module}" if node.module else base)
            else:
                names.append(node.module or "")
    return names


def _forbidden(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN)


def test_the_wiki_package_has_modules():
    assert {path.name for path in WIKI_FILES} >= {"__init__.py", "export.py", "writer.py"}


@pytest.mark.parametrize("path", WIKI_FILES, ids=lambda path: path.name)
def test_wiki_modules_import_only_public_code(path):
    assert [name for name in _imports(path) if _forbidden(name)] == []


def test_importing_the_cli_and_wiki_pulls_in_no_internal_or_heavy_module():
    code = (
        "import sys, bilinc.cli.main, bilinc.wiki\n"
        f"forbidden = {FORBIDDEN!r}\n"
        "print(sorted(m for m in sys.modules if any(m == p or m.startswith(p + '.') for p in forbidden)))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    completed = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "[]"
