"""Public cloud-only CLI error-path tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _public_cli_env() -> dict[str, str]:
    """Run subprocesses without forwarding ambient credentials."""
    src = Path(__file__).resolve().parents[1] / "src"
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(src),
        "HOME": os.environ.get("HOME", ""),
        "LANG": "C",
    }


def test_cloud_cli_requires_api_key_for_memory_operations():
    result = subprocess.run(
        [sys.executable, "-m", "bilinc.cli.main", "commit", "--key", "k1", "--value", "v1"],
        text=True,
        capture_output=True,
        env=_public_cli_env(),
    )

    assert result.returncode == 1
    assert "API key" in result.stderr


def test_cloud_cli_signup_is_available_without_api_key():
    result = subprocess.run(
        [sys.executable, "-m", "bilinc.cli.main", "signup"],
        text=True,
        capture_output=True,
        env=_public_cli_env(),
    )

    assert result.returncode == 0
    assert "signup" in result.stdout
