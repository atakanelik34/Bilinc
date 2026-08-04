#!/usr/bin/env python3
"""Matched Modal A/B runner for generic current-state query intent handling."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import certifi
import modal


GOAL_ID = "bilinc-benchmark-dominance-20260804"
BENCHMARK_ID = "locomo-official-retrieval-component-stateplane-temporal-intent-v1"
DATASET_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
DATASET_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
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
        modal.Image.from_registry("python:3.11-slim")
        .add_local_dir(REPO_ROOT, REMOTE_REPO, copy=True, ignore=_ignore_local_path)
        .run_commands(
            "python -m pip install --no-cache-dir certifi",
            "python -m pip install --no-cache-dir -e '/root/bilinc[internal]'",
        )
    )


app = modal.App(
    f"bilinc-benchmark-{GOAL_ID}-locomo-temporal",
    tags={
        "project": "bilinc",
        "purpose": "benchmark",
        "goal": GOAL_ID,
        "benchmark": "locomo-temporal-intent",
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("bilinc", "certifi"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "missing"
    return versions


def _set_intents(enabled: bool) -> None:
    os.environ.pop("BILINC_GRAPH_RECALL", None)
    for key in (
        "BILINC_SEMANTIC_MODEL",
        "BILINC_SEMANTIC_MODEL_REVISION",
        "BILINC_SEMANTIC_DEVICE",
    ):
        os.environ.pop(key, None)
    os.environ["BILINC_CURRENT_STATE_INTENTS"] = "enabled" if enabled else "legacy"


@app.function(
    image=_image(),
    cpu=8.0,
    memory=16384,
    timeout=2400,
    single_use_containers=True,
    include_source=True,
)
def run_locomo_pair(top_k: int = 5) -> dict[str, Any]:
    """Run the frozen raw-turn component with legacy and expanded intent modes."""
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
    for label, enabled in (("baseline_legacy", False), ("candidate_temporal_intents", True)):
        _set_intents(enabled)
        result_path = Path(f"/tmp/locomo-stateplane-{label}.json")
        started = time.time()
        result = asyncio.run(run_benchmark(dataset_path, result_path, top_k=top_k))
        ended = time.time()
        results[label] = {
            "candidate_enabled": enabled,
            "started_epoch": started,
            "ended_epoch": ended,
            "wall_seconds": round(ended - started, 3),
            "result": result,
        }
    _set_intents(True)

    return {
        "goal_id": GOAL_ID,
        "benchmark": BENCHMARK_ID,
        "dataset_url": DATASET_URL,
        "dataset_sha256": dataset_sha256,
        "top_k": top_k,
        "product_files": {
            "src/bilinc/core/stateplane.py": _sha256(REMOTE_REPO / "src/bilinc/core/stateplane.py"),
            "benchmarks/runners/locomo_stateplane_component.py": _sha256(
                REMOTE_REPO / "benchmarks/runners/locomo_stateplane_component.py"
            ),
            "benchmarks/modal/locomo_temporal_intent_candidate_runner.py": _sha256(
                REMOTE_REPO / "benchmarks/modal/locomo_temporal_intent_candidate_runner.py"
            ),
        },
        "package_versions": _package_versions(),
        "hardware": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "python_command_version": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
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
