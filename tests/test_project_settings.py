import json
import os
import subprocess
import sys

import pytest

from bilinc.cloud.project_settings import ProjectSettings, load_project_settings, save_project_settings

PROJECT = "22222222-2222-4222-8222-222222222222"


def _run(tmp_path, *extra, project=PROJECT):
    return subprocess.run(
        [sys.executable, "-m", "bilinc.cloud.project_settings", "--runtime-dir", str(tmp_path), "--project", project, *extra],
        capture_output=True,
        text=True,
        env={**os.environ},
    )


def test_defaults_when_missing(tmp_path):
    assert load_project_settings(tmp_path) == ProjectSettings()


def test_roundtrip_and_permissions(tmp_path):
    save_project_settings(tmp_path, ProjectSettings(timezone="Europe/Istanbul", low_signal_sources=("sample-chat-transcript",)))
    assert load_project_settings(tmp_path) == ProjectSettings("Europe/Istanbul", ("sample-chat-transcript",))
    assert oct((tmp_path / "settings.json").stat().st_mode & 0o777) == "0o600"
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]


@pytest.mark.parametrize(
    "bad",
    [
        ProjectSettings(timezone="Mars/Olympus"),
        ProjectSettings(timezone="../etc/passwd"),
        ProjectSettings(timezone="/etc/passwd"),
        ProjectSettings(low_signal_sources=("x" * 121,)),
        ProjectSettings(low_signal_sources=("",)),
        ProjectSettings(low_signal_sources=("   ",)),
        ProjectSettings(low_signal_sources=tuple(f"s{i}" for i in range(21))),
    ],
)
def test_invalid_settings_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        save_project_settings(tmp_path, bad)
    assert not (tmp_path / "settings.json").exists()


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    (tmp_path / "settings.json").write_text("{not json")
    assert load_project_settings(tmp_path) == ProjectSettings()


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        '"text"',
        "null",
        "42",
        '{"timezone": 5, "low_signal_sources": "sample-chat-transcript"}',
        '{"timezone": "UTC", "low_signal_sources": "sample-chat-transcript"}',
        '{"timezone": "UTC", "low_signal_sources": [1, null]}',
        '{"timezone": "UTC", "low_signal_sources": {"a": 1}}',
        '{"timezone": "../etc/passwd"}',
        '{"timezone": "Europe/Istanbul", "low_signal_sources": ["ok", ""]}',
    ],
)
def test_wrong_shapes_fall_back_to_defaults(tmp_path, content):
    (tmp_path / "settings.json").write_text(content)
    assert load_project_settings(tmp_path) == ProjectSettings()


def test_symlinked_settings_is_read(tmp_path):
    target = tmp_path / "elsewhere.json"
    target.write_text('{"timezone": "Europe/Istanbul", "low_signal_sources": ["sample-chat-transcript"]}')
    project = tmp_path / "p"
    project.mkdir()
    (project / "settings.json").symlink_to(target)
    assert load_project_settings(project) == ProjectSettings("Europe/Istanbul", ("sample-chat-transcript",))


def test_cli_sets_and_shows(tmp_path):
    first = _run(tmp_path, "--timezone", "Europe/Istanbul", "--low-signal-source", "sample-chat-transcript")
    assert first.returncode == 0, first.stderr
    shown = _run(tmp_path, "--show")
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout) == {"timezone": "Europe/Istanbul", "low_signal_sources": ["sample-chat-transcript"]}
    assert json.loads(_run(tmp_path).stdout) == json.loads(shown.stdout)


def test_cli_dedups_and_clears(tmp_path):
    assert _run(tmp_path, "--low-signal-source", "sample-chat-transcript").returncode == 0
    assert _run(tmp_path, "--low-signal-source", "sample-chat-transcript", "--low-signal-source", "other-feed").returncode == 0
    shown = json.loads(_run(tmp_path, "--show").stdout)
    assert shown["low_signal_sources"] == ["sample-chat-transcript", "other-feed"]
    assert _run(tmp_path, "--clear-low-signal").returncode == 0
    assert json.loads(_run(tmp_path, "--show").stdout)["low_signal_sources"] == []


@pytest.mark.parametrize("bad_project", ["../x", "not-a-uuid"])
def test_cli_invalid_project_writes_nothing(tmp_path, bad_project):
    runtime = tmp_path / "runtime"
    result = _run(runtime, "--timezone", "Europe/Istanbul", project=bad_project)
    assert result.returncode != 0
    assert result.stderr.strip()
    assert "Traceback" not in result.stderr
    assert not runtime.exists()
    assert list(tmp_path.iterdir()) == []


def test_cli_invalid_timezone_writes_nothing(tmp_path):
    runtime = tmp_path / "runtime"
    for tz in ("Mars/Olympus", "../etc/passwd"):
        result = _run(runtime, "--timezone", tz)
        assert result.returncode != 0
        assert result.stderr.strip()
        assert "Traceback" not in result.stderr
    assert not runtime.exists()
