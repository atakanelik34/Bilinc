#!/usr/bin/env python3
"""Matched Modal A/B runner for Bilinc's general current-state query intents."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

import modal


GOAL_ID = "bilinc-benchmark-dominance-20260804"
BENCHMARK_ID = "amb-legacy-v3-temporal-intent-candidate"
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
            "python -m pip install --no-cache-dir -e '/root/bilinc[internal]'",
            "mkdir -p /opt/amb && cd /opt/amb && npm init -y",
            "cd /opt/amb && npm install --ignore-scripts --no-audit --no-fund agent-memory-benchmark@3.0.0 @modelcontextprotocol/sdk@1.0.4",
        )
    )


app = modal.App(
    f"bilinc-benchmark-{GOAL_ID}-amb-temporal",
    tags={
        "project": "bilinc",
        "purpose": "benchmark",
        "goal": GOAL_ID,
        "benchmark": BENCHMARK_ID,
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("bilinc", "mcp"):
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


def _run_layer(layer: int, candidate_enabled: bool, store_delay_seconds: float) -> dict[str, Any]:
    _set_intents(candidate_enabled)
    label = "candidate_temporal_intents" if candidate_enabled else "baseline_legacy"
    run_root = Path("/tmp") / f"bilinc-{BENCHMARK_ID}-layer-{layer}-{label}"
    run_root.mkdir(parents=True, exist_ok=True)
    db_path = run_root / "state.sqlite"
    output_dir = run_root / "results"
    command = [
        "node",
        "/opt/amb/node_modules/agent-memory-benchmark/dist/cli.js",
        "--provider",
        "mcp",
        "--mcp-command",
        f"python3 {REMOTE_REPO}/benchmarks/adapters/amb_generic_mcp.py --db-path {db_path}",
        "--mcp-store-tool",
        "remember",
        "--mcp-search-tool",
        "search",
        "--mcp-delete-tool",
        "forget",
        "--layer",
        str(layer),
        "--store-delay",
        str(store_delay_seconds),
        "--fixtures-dir",
        "/opt/amb/node_modules/agent-memory-benchmark/fixtures",
        "--output",
        str(output_dir),
    ]
    started = time.time()
    process = subprocess.run(command, cwd="/opt/amb", capture_output=True, text=True, check=False)
    ended = time.time()
    result_path = output_dir / "results.json"
    result = json.loads(result_path.read_text()) if result_path.is_file() else None
    return {
        "candidate_enabled": candidate_enabled,
        "started_epoch": started,
        "ended_epoch": ended,
        "wall_seconds": round(ended - started, 3),
        "exit_code": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
        "result": result,
    }


@app.function(
    image=_image(),
    cpu=8.0,
    memory=16384,
    timeout=1800,
    single_use_containers=True,
    include_source=True,
)
def run_amb_pair(store_delay_seconds: float = 3.0) -> dict[str, Any]:
    """Run both AMB layers with legacy and expanded temporal intent modes."""
    results: dict[str, dict[str, Any]] = {}
    for layer in (1, 2):
        for label, enabled in (("baseline_legacy", False), ("candidate_temporal_intents", True)):
            results[f"layer{layer}_{label}"] = _run_layer(layer, enabled, store_delay_seconds)
    _set_intents(True)

    return {
        "goal_id": GOAL_ID,
        "benchmark": BENCHMARK_ID,
        "store_delay_seconds": store_delay_seconds,
        "product_files": {
            "src/bilinc/core/stateplane.py": _sha256(REMOTE_REPO / "src/bilinc/core/stateplane.py"),
            "benchmarks/adapters/amb_generic_mcp.py": _sha256(REMOTE_REPO / "benchmarks/adapters/amb_generic_mcp.py"),
            "benchmarks/modal/amb_temporal_intent_candidate_runner.py": _sha256(
                REMOTE_REPO / "benchmarks/modal/amb_temporal_intent_candidate_runner.py"
            ),
        },
        "package_versions": _package_versions(),
        "hardware": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "node": subprocess.run(["node", "--version"], capture_output=True, text=True, check=False).stdout.strip(),
            "cpu_count": os.cpu_count(),
        },
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-delay", type=float, default=3.0)
    parser.add_argument("--receipt-path", type=Path)
    args = parser.parse_args()
    with app.run():
        receipt = run_amb_pair.remote(args.store_delay)
    if args.receipt_path:
        args.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        args.receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
