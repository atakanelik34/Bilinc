"""Public cloud-only CLI error-path tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def public_cli_env(tmp_path: Path) -> dict[str, str]:
    """A subprocess environment with no reachable Bilinc credentials.

    This must stay airtight. `config_path()` resolves a saved key from, in order,
    ``BILINC_CONFIG_DIR``, ``XDG_CONFIG_HOME``, and finally ``Path.home()`` —
    so forwarding the real ``HOME`` is enough to hand the CLI a live
    ``bil_live_…`` key from ``~/.config/bilinc/config.json``. When that happens
    these tests stop testing the unauthenticated path: the CLI authenticates,
    reaches hosted Bilinc Cloud, and writes to the operator's production account.

    ``HOME`` is therefore redirected into a per-test tmp directory and
    ``BILINC_CONFIG_DIR`` is pinned there explicitly, so no lookup can escape
    to the real user. ``BILINC_API_KEY`` and ``BILINC_BASE_URL`` are simply
    never added, since this dict is built from scratch rather than copied
    from ``os.environ``.
    """
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "HOME": str(isolated_home),
        "BILINC_CONFIG_DIR": str(isolated_home / "bilinc-config"),
        "LANG": "C",
    }


def test_public_cli_env_exposes_no_ambient_credentials(public_cli_env: dict[str, str]):
    """Guard the guard: if this regresses, the tests below hit production."""
    assert "BILINC_API_KEY" not in public_cli_env
    assert public_cli_env["HOME"] != os.environ.get("HOME")
    assert not (Path(public_cli_env["BILINC_CONFIG_DIR"]) / "config.json").exists()


def test_cloud_cli_requires_api_key_for_memory_operations(public_cli_env: dict[str, str]):
    result = subprocess.run(
        [sys.executable, "-m", "bilinc.cli.main", "commit", "--key", "k1", "--value", "v1"],
        text=True,
        capture_output=True,
        env=public_cli_env,
    )

    assert result.returncode == 1
    assert "API key" in result.stderr


def test_cloud_cli_signup_is_available_without_api_key(public_cli_env: dict[str, str]):
    result = subprocess.run(
        [sys.executable, "-m", "bilinc.cli.main", "signup"],
        text=True,
        capture_output=True,
        env=public_cli_env,
    )

    assert result.returncode == 0
    assert "signup" in result.stdout
