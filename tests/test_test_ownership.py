"""Test ownership lanes must remain visible to pytest and CI."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_public_source_lane_collects_only_public_boundary_tests() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "public_source"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "test_cloud_only_package.py" in result.stdout
    assert "test_cloud_service.py" not in result.stdout
