#!/usr/bin/env python3
"""Ephemeral Modal runner for the clean LoCoMo StatePlane component lane."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import ssl
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import modal


GOAL_ID = "bilinc-benchmark-dominance-20260804"
BENCHMARK_ID = "locomo-official-retrieval-component-stateplane"
DATASET_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
DATASET_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"


def _repo_root() -> Path:
    candidate = Path(__file__).resolve().parent
    for _ in range(2):
        candidate = candidate.parent
    if (candidate / "pyproject.toml").is_file():
        return candidate
    mounted = Path("/root/bilinc")
    if (mounted / "pyproject.toml").is_file():
        return mounted
    return Path.cwd()


REPO_ROOT = _repo_root()
REMOTE_REPO = Path("/root/bilinc")


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
        .run_commands("python -m pip install --no-cache-dir -e '/root/bilinc[internal]'")
    )


app = modal.App(
    f"bilinc-benchmark-{GOAL_ID}-locomo",
    tags={
        "project": "bilinc",
        "purpose": "benchmark",
        "goal": GOAL_ID,
        "benchmark": BENCHMARK_ID,
    },
)


@app.function(
    image=_image(),
    cpu=8.0,
    memory=16384,
    timeout=1800,
    single_use_containers=True,
    include_source=True,
)
def run_locomo(top_k: int = 5) -> dict[str, Any]:
    """Download and hash the official dataset, then run the frozen component."""

    dataset_path = Path("/tmp/locomo10.json")
    import certifi

    tls_context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(DATASET_URL, context=tls_context, timeout=60) as response:
        dataset_path.write_bytes(response.read())
    dataset_sha256 = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    if dataset_sha256 != DATASET_SHA256:
        raise RuntimeError(f"dataset sha256 mismatch: {dataset_sha256}")

    import sys

    sys.path.insert(0, str(REMOTE_REPO))
    from benchmarks.runners.locomo_stateplane_component import run_benchmark

    result_path = Path("/tmp/locomo-stateplane-result.json")
    started = time.time()
    result = asyncio.run(run_benchmark(dataset_path, result_path, top_k=top_k))
    ended = time.time()
    hardware = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "node": subprocess.run(["node", "--version"], capture_output=True, text=True, check=False).stdout.strip(),
        "cpu_count": os.cpu_count(),
    }
    return {
        "goal_id": GOAL_ID,
        "benchmark": BENCHMARK_ID,
        "dataset_url": DATASET_URL,
        "dataset_sha256": dataset_sha256,
        "top_k": top_k,
        "started_epoch": started,
        "ended_epoch": ended,
        "wall_seconds": round(ended - started, 3),
        "hardware": hardware,
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--receipt-path", type=Path)
    args = parser.parse_args()
    with app.run():
        receipt = run_locomo.remote(args.top_k)
    if args.receipt_path:
        args.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        args.receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
