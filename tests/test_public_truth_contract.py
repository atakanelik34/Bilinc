"""Public truth must be derived from the shipped Cloud package surface."""

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]


def test_registry_and_pypi_package_share_one_release_version() -> None:
    import bilinc

    server = json.loads((ROOT / "server.json").read_text())
    package = next(item for item in server["packages"] if item["identifier"] == "bilinc")
    assert server["version"] == package["version"] == bilinc.__version__
    assert {"type": "streamable-http", "url": "https://mcp.bilinc.space/mcp"} in server["remotes"]


def test_public_product_truth_matches_the_shipped_cloud_surface() -> None:
    manifest = ROOT / "docs" / "public" / "product-truth.json"

    assert manifest.is_file(), "public product truth manifest is required"

    payload = json.loads(manifest.read_text())
    assert payload["package"]["name"] == "bilinc"
    assert payload["package"]["version"] == "2.3.7"
    assert payload["cloud_mcp"]["tools"] == [
        "commit_mem",
        "recall",
        "revise",
        "forget",
        "status",
        "snapshot",
        "diff",
        "rollback",
        "list_memories",
        "history",
        "confirm",
    ]
    benchmark = payload["benchmark_claims"]
    assert benchmark["state"] == "historical_scoped"
    assert benchmark["public_approved"] is True
    assert benchmark["label"] == "Frozen regression receipt"
    assert benchmark["scope"] == "LongMemEval-s cleaned retrieval fixture, 500 questions"
    assert benchmark["metrics"] == {"hit_at_5": "98.0%", "ndcg_at_5": "0.913"}
    assert "not a current hosted SLA" in benchmark["qualification"]


def test_public_product_truth_validator_accepts_the_committed_manifest() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/validate_public_truth.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_generated_public_truth_document_matches_the_manifest() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/generate_public_truth_doc.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
