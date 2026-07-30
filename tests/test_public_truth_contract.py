"""Public truth must be derived from the shipped Cloud package surface."""

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]


def test_public_product_truth_matches_the_shipped_cloud_surface() -> None:
    manifest = ROOT / "docs" / "public" / "product-truth.json"

    assert manifest.is_file(), "public product truth manifest is required"

    payload = json.loads(manifest.read_text())
    assert payload["package"]["name"] == "bilinc"
    assert payload["package"]["version"] == "2.1.6"
    assert payload["cloud_mcp"]["tools"] == [
        "commit_mem",
        "recall",
        "revise",
        "forget",
        "status",
        "snapshot",
        "diff",
        "rollback",
    ]
    benchmark = payload["benchmark_claims"]
    assert benchmark["state"] == "historical_scoped"
    assert benchmark["public_approved"] is True
    assert benchmark["label"] == "Archived research receipt"
    assert benchmark["scope"] == "LongMemEval-s cleaned retrieval fixture, 500 questions"
    assert benchmark["metrics"] == {"legacy_r_at_5": "98.0%", "legacy_ndcg_at_5": "0.933"}
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
