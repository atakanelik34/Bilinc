#!/usr/bin/env python3
"""Matched Modal A/B runner for Bilinc's opt-in local semantic retrieval."""

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
BENCHMARK_ID = "amb-legacy-v3-semantic-candidate"
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
            "mkdir -p /opt/amb && cd /opt/amb && npm init -y",
            "cd /opt/amb && npm install --ignore-scripts --no-audit --no-fund agent-memory-benchmark@3.0.0 @modelcontextprotocol/sdk@1.0.4",
        )
    )


app = modal.App(
    f"bilinc-benchmark-{GOAL_ID}-amb-semantic",
    tags={
        "project": "bilinc",
        "purpose": "benchmark",
        "goal": GOAL_ID,
        "benchmark": BENCHMARK_ID,
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _model_manifest() -> dict[str, Any]:
    snapshot = Path.home() / ".cache" / "huggingface" / (
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
    return {"model_id": MODEL_ID, "revision": MODEL_REVISION, "manifest_sha256": manifest_sha256, "files": files}


def _package_versions() -> dict[str, str]:
    names = (
        "bilinc",
        "mcp",
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
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    for key in (
        "BILINC_GRAPH_RECALL",
        "BILINC_SEMANTIC_MODEL",
        "BILINC_SEMANTIC_MODEL_REVISION",
        "BILINC_SEMANTIC_DEVICE",
    ):
        os.environ.pop(key, None)
    if enabled:
        os.environ["BILINC_SEMANTIC_MODEL"] = MODEL_ID
        os.environ["BILINC_SEMANTIC_MODEL_REVISION"] = MODEL_REVISION
        os.environ["BILINC_SEMANTIC_DEVICE"] = "cpu"


def _run_layer(layer: int, semantic_enabled: bool, store_delay_seconds: float) -> dict[str, Any]:
    _set_semantic(semantic_enabled)
    label = "candidate_semantic" if semantic_enabled else "baseline_disabled"
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
        "semantic_enabled": semantic_enabled,
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
    """Run both AMB layers with semantic baseline and candidate in one container."""
    results: dict[str, dict[str, Any]] = {}
    for layer in (1, 2):
        for label, enabled in (("baseline_disabled", False), ("candidate_semantic", True)):
            results[f"layer{layer}_{label}"] = _run_layer(layer, enabled, store_delay_seconds)
    _set_semantic(False)

    return {
        "goal_id": GOAL_ID,
        "benchmark": BENCHMARK_ID,
        "store_delay_seconds": store_delay_seconds,
        "model": _model_manifest(),
        "product_files": {
            "src/bilinc/core/stateplane.py": _sha256(REMOTE_REPO / "src/bilinc/core/stateplane.py"),
            "src/bilinc/core/vector_search.py": _sha256(REMOTE_REPO / "src/bilinc/core/vector_search.py"),
            "benchmarks/adapters/amb_generic_mcp.py": _sha256(REMOTE_REPO / "benchmarks/adapters/amb_generic_mcp.py"),
            "benchmarks/modal/amb_semantic_candidate_runner.py": _sha256(
                REMOTE_REPO / "benchmarks/modal/amb_semantic_candidate_runner.py"
            ),
        },
        "package_versions": _package_versions(),
        "hardware": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "node": subprocess.run(
                ["node", "--version"], capture_output=True, text=True, check=False
            ).stdout.strip(),
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
