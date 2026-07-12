"""The repository must reject likely credentials without echoing their values."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_secret_safety_check_accepts_tracked_repository_content() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_secret_safety.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
