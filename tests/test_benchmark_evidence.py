"""Evidence-manifest contract tests."""

import json
from pathlib import Path

from benchmarks.validate_evidence import validate_manifest


def test_all_committed_benchmark_manifests_validate_metadata() -> None:
    """A source checkout can validate manifests without ignored run artifacts."""
    evidence_root = Path(__file__).parents[1] / "benchmarks" / "evidence"
    manifests = sorted(evidence_root.glob("**/manifest.json"))

    assert manifests
    assert not [
        error
        for manifest in manifests
        for error in validate_manifest(manifest, require_raw_results=False)
    ]


def test_available_benchmark_artifacts_validate_checksums() -> None:
    """Any raw artifacts present locally must still match manifest hashes."""
    evidence_root = Path(__file__).parents[1] / "benchmarks" / "evidence"
    manifests = sorted(evidence_root.glob("**/manifest.json"))

    assert manifests
    errors: list[str] = []
    for manifest in manifests:
        payload = json.loads(manifest.read_text())
        raw_paths = [manifest.parents[3] / result["path"] for result in payload["raw_results"]]
        if all(path.is_file() for path in raw_paths):
            errors.extend(validate_manifest(manifest))
    assert not errors
