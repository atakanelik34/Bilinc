#!/usr/bin/env python3
"""Ephemeral Modal runner for the frozen AMB v3 baseline.

Run directly with the installed Modal SDK, for example:

    python3 benchmarks/modal/amb_runner.py --layer 1

The script opens one temporary App, runs one single-use container, returns the
raw result JSON and hardware receipt, then exits.  It never deploys an App,
creates a Volume, mounts a home directory, or passes environment secrets into
the container.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

import modal


GOAL_ID = "bilinc-benchmark-dominance-20260804"
BENCHMARK_ID = "amb-legacy-v3"


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
        .run_commands(
            "python -m pip install --no-cache-dir -e '/root/bilinc[internal]'",
            "mkdir -p /opt/amb && cd /opt/amb && npm init -y",
            "cd /opt/amb && npm install --ignore-scripts --no-audit --no-fund agent-memory-benchmark@3.0.0 @modelcontextprotocol/sdk@1.0.4",
        )
    )


app = modal.App(
    f"bilinc-benchmark-{GOAL_ID}",
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
def run_amb(layer: int, store_delay_seconds: float = 3.0) -> dict[str, Any]:
    """Run one frozen AMB layer and return result plus non-secret receipt."""

    if layer not in (1, 2):
        raise ValueError("layer must be 1 or 2")
    run_root = Path("/tmp") / f"bilinc-{BENCHMARK_ID}-layer-{layer}"
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
    result: dict[str, Any] | None = None
    if result_path.is_file():
        result = json.loads(result_path.read_text())
    hardware = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "node": subprocess.run(["node", "--version"], capture_output=True, text=True, check=False).stdout.strip(),
        "cpu_count": os.cpu_count(),
    }
    return {
        "goal_id": GOAL_ID,
        "benchmark": BENCHMARK_ID,
        "layer": layer,
        "command": command,
        "started_epoch": started,
        "ended_epoch": ended,
        "wall_seconds": round(ended - started, 3),
        "exit_code": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
        "result": result,
        "hardware": hardware,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", type=int, choices=(1, 2), required=True)
    parser.add_argument("--store-delay", type=float, default=3.0)
    parser.add_argument("--receipt-path", type=Path)
    args = parser.parse_args()
    with app.run():
        receipt = run_amb.remote(args.layer, args.store_delay)
    if args.receipt_path:
        args.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        args.receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["exit_code"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
