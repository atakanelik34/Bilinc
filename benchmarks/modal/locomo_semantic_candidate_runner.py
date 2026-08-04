#!/usr/bin/env python3
"""Matched Modal A/B runner for Bilinc's opt-in local semantic retrieval."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import certifi
import modal


GOAL_ID = "bilinc-benchmark-dominance-20260804"
BENCHMARK_ID = "locomo-official-retrieval-component-stateplane-semantic-v1"
DATASET_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
DATASET_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MODEL_MANIFEST_SHA256 = "2db4942727d159bcf555eead73a5e1384c197f72bfae286b7994267f8620b92a"
MODEL_REQUIRED_FILES = (
    "1_Pooling/config.json",
    "README.md",
    "config.json",
    "config_sentence_transformers.json",
    "model.safetensors",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
)
REMOTE_REPO = Path("/root/bilinc")


def _repo_root() -> Path:
    candidate = Path(__file__).resolve().parent
    for _ in range(2):
        candidate = candidate.parent
    if (candidate / "pyproject.toml").is_file():
        return candidate
    if (REMOTE_REPO / "pyproject.toml").is_file():
        return REMOTE_REPO
    return Path.cwd()


REPO_ROOT = _repo_root()


def _ignore_local_path(path: Path) -> bool:
    try:
        relative = path.relative_to(REPO_ROOT)
    except ValueError:
        return False
    parts = set(relative.parts)
    if parts & {".git", ".venv", "__pycache__", "node_modules"}:
        return True
    name = relative.name
    if name.startswith(".env") or name.endswith((".sqlite", ".sqlite3", ".db", ".pem", ".key")):
        return True
    return str(relative).startswith("benchmarks/runs/")


def _image() -> modal.Image:
    return (
        modal.Image.from_registry("node:22-bookworm-slim", add_python="3.11")
        .add_local_dir(REPO_ROOT, REMOTE_REPO, copy=True, ignore=_ignore_local_path)
        .run_commands(
            "python -m pip install --no-cache-dir -e '/root/bilinc[internal,semantic]'",
            "python -m pip install --no-cache-dir "
            "numpy==2.4.2 sentence-transformers==3.4.1 torch==2.12.1 "
            "transformers==4.57.6 huggingface-hub==0.36.2 "
            "safetensors==0.8.0 tokenizers==0.22.2",
        )
    )


app = modal.App(
    f"bilinc-benchmark-{GOAL_ID}-locomo-semantic",
    tags={
        "project": "bilinc",
        "purpose": "benchmark",
        "goal": GOAL_ID,
        "benchmark": BENCHMARK_ID,
    },
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _model_manifest() -> dict[str, Any]:
    snapshot = Path.home() / ".cache" / "huggingface" / "hub" / (
        "models--sentence-transformers--all-MiniLM-L6-v2"
    ) / "snapshots" / MODEL_REVISION
    files: dict[str, str] = {}
    for name in MODEL_REQUIRED_FILES:
        path = snapshot / name
        if not path.is_file():
            raise RuntimeError(f"required model file missing: {name}")
        files[name] = _sha256(path)
    digest = hashlib.sha256()
    for name, file_hash in files.items():
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(file_hash.encode())
        digest.update(b"\0")
    manifest_sha256 = digest.hexdigest()
    if manifest_sha256 != MODEL_MANIFEST_SHA256:
        raise RuntimeError(f"model manifest mismatch: {manifest_sha256}")
    return {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "manifest_sha256": manifest_sha256,
        "files": files,
    }


def _package_versions() -> dict[str, str]:
    names = (
        "bilinc",
        "numpy",
        "sentence-transformers",
        "torch",
        "transformers",
        "huggingface-hub",
        "safetensors",
        "tokenizers",
    )
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "missing"
    return versions


def _set_semantic(enabled: bool) -> None:
    # The Rust xet transport can fail to discover the container CA bundle even
    # though Python HTTPS is configured with certifi. Use the pinned model's
    # regular HTTPS download path so a transport warning cannot corrupt the
    # artifact-integrity check below.
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    for key in (
        "BILINC_SEMANTIC_MODEL",
        "BILINC_SEMANTIC_MODEL_REVISION",
        "BILINC_SEMANTIC_DEVICE",
    ):
        os.environ.pop(key, None)
    if enabled:
        os.environ["BILINC_SEMANTIC_MODEL"] = MODEL_ID
        os.environ["BILINC_SEMANTIC_MODEL_REVISION"] = MODEL_REVISION
        os.environ["BILINC_SEMANTIC_DEVICE"] = "cpu"


@app.function(
    image=_image(),
    cpu=8.0,
    memory=16384,
    timeout=2400,
    single_use_containers=True,
    include_source=True,
)
def run_locomo_pair(top_k: int = 5) -> dict[str, Any]:
    """Run disabled baseline and enabled candidate in one matched container."""

    dataset_path = Path("/tmp/locomo10.json")
    tls_context = __import__("ssl").create_default_context(cafile=certifi.where())
    with urlopen(DATASET_URL, context=tls_context, timeout=60) as response:
        dataset_path.write_bytes(response.read())
    dataset_sha256 = _sha256(dataset_path)
    if dataset_sha256 != DATASET_SHA256:
        raise RuntimeError(f"dataset sha256 mismatch: {dataset_sha256}")

    import sys

    sys.path.insert(0, str(REMOTE_REPO))
    from benchmarks.runners.locomo_stateplane_component import run_benchmark

    results: dict[str, dict[str, Any]] = {}
    for label, enabled in (("baseline_disabled", False), ("candidate_semantic", True)):
        _set_semantic(enabled)
        result_path = Path(f"/tmp/locomo-stateplane-{label}.json")
        started = time.time()
        result = asyncio.run(run_benchmark(dataset_path, result_path, top_k=top_k))
        ended = time.time()
        results[label] = {
            "semantic_enabled": enabled,
            "started_epoch": started,
            "ended_epoch": ended,
            "wall_seconds": round(ended - started, 3),
            "result": result,
        }
    _set_semantic(False)

    product_files = {
        "src/bilinc/core/stateplane.py": _sha256(REMOTE_REPO / "src/bilinc/core/stateplane.py"),
        "src/bilinc/core/vector_search.py": _sha256(REMOTE_REPO / "src/bilinc/core/vector_search.py"),
        "benchmarks/runners/locomo_stateplane_component.py": _sha256(
            REMOTE_REPO / "benchmarks/runners/locomo_stateplane_component.py"
        ),
        "benchmarks/modal/locomo_semantic_candidate_runner.py": _sha256(
            REMOTE_REPO / "benchmarks/modal/locomo_semantic_candidate_runner.py"
        ),
    }
    hardware = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "node": subprocess.run(
            ["node", "--version"], capture_output=True, text=True, check=False
        ).stdout.strip(),
        "cpu_count": os.cpu_count(),
    }
    return {
        "goal_id": GOAL_ID,
        "benchmark": BENCHMARK_ID,
        "dataset_url": DATASET_URL,
        "dataset_sha256": dataset_sha256,
        "top_k": top_k,
        "model": _model_manifest(),
        "package_versions": _package_versions(),
        "product_files": product_files,
        "hardware": hardware,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--receipt-path", type=Path)
    args = parser.parse_args()
    with app.run():
        receipt = run_locomo_pair.remote(args.top_k)
    if args.receipt_path:
        args.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        args.receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
