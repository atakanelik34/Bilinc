"""Evidence-manifest contract tests."""

from pathlib import Path

from benchmarks.validate_evidence import validate_manifest


def test_all_committed_benchmark_manifests_validate() -> None:
    evidence_root = Path(__file__).parents[1] / "benchmarks" / "evidence"
    manifests = sorted(evidence_root.glob("**/manifest.json"))

    assert manifests
    assert not [error for manifest in manifests for error in validate_manifest(manifest)]
