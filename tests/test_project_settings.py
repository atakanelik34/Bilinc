import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

import bilinc
from bilinc.cloud.project_settings import ProjectSettings, load_project_settings, save_project_settings

PROJECT = "22222222-2222-4222-8222-222222222222"


def _run(tmp_path, *extra, project=PROJECT):
    return subprocess.run(
        [sys.executable, "-m", "bilinc.cloud.project_settings", "--runtime-dir", str(tmp_path), "--project", project, *extra],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(bilinc.__file__).resolve().parents[1])},
    )


def _project(runtime):
    project_dir = runtime / PROJECT
    project_dir.mkdir(parents=True)
    return project_dir


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


def test_symlinked_settings_is_not_followed(tmp_path):
    target = tmp_path / "elsewhere.json"
    target.write_text('{"timezone": "Europe/Istanbul", "low_signal_sources": ["sample-chat-transcript"]}')
    project = tmp_path / "p"
    project.mkdir()
    (project / "settings.json").symlink_to(target)
    assert load_project_settings(project) == ProjectSettings()


def test_fifo_oversize_and_odd_files_fall_back_without_blocking(tmp_path):
    fifo_dir = tmp_path / "fifo"
    fifo_dir.mkdir()
    os.mkfifo(fifo_dir / "settings.json")
    assert load_project_settings(fifo_dir) == ProjectSettings()
    for name, content in [("big", '{"timezone": "UTC", "pad": "' + "x" * 70_000 + '"}'), ("deep", "[" * 100_000),
                          ("empty", ""), ("binary", b"\xff\xfe")]:
        directory = tmp_path / name
        directory.mkdir()
        target = directory / "settings.json"
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
        assert load_project_settings(directory) == ProjectSettings(), name
    as_dir = tmp_path / "as-dir"
    (as_dir / "settings.json").mkdir(parents=True)
    assert load_project_settings(as_dir) == ProjectSettings()


def test_unusable_file_is_logged_missing_file_is_not(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="bilinc.cloud.project_settings"):
        load_project_settings(tmp_path)
        assert not caplog.records
        (tmp_path / "settings.json").write_text("{not json")
        load_project_settings(tmp_path)
    assert len(caplog.records) == 1
    assert "not json" not in caplog.text and str(tmp_path) not in caplog.text


def test_boundaries_are_accepted(tmp_path):
    settings = ProjectSettings(low_signal_sources=tuple(f"{i:02d}" + "x" * 118 for i in range(20)))
    save_project_settings(tmp_path, settings)
    assert load_project_settings(tmp_path) == settings


def test_sources_are_a_tuple_never_a_string():
    assert ProjectSettings(low_signal_sources=["a"]).low_signal_sources == ("a",)
    with pytest.raises(ValueError):
        ProjectSettings(low_signal_sources="abc")


@pytest.mark.parametrize("bad", [" padded ", "line\nbreak"])
def test_unnormalised_sources_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        save_project_settings(tmp_path, ProjectSettings(low_signal_sources=(bad,)))


def test_failed_save_keeps_previous_file(tmp_path):
    good = ProjectSettings("Europe/Istanbul", ("sample-chat-transcript",))
    save_project_settings(tmp_path, good)
    with pytest.raises(ValueError):
        save_project_settings(tmp_path, ProjectSettings(timezone="Mars/Olympus"))
    assert load_project_settings(tmp_path) == good


def test_new_project_dir_is_private(tmp_path):
    old = os.umask(0o022)
    try:
        save_project_settings(tmp_path / "new", ProjectSettings())
    finally:
        os.umask(old)
    assert oct((tmp_path / "new").stat().st_mode & 0o777) == "0o700"


def test_cli_sets_and_shows(tmp_path):
    _project(tmp_path)
    first = _run(tmp_path, "--timezone", "Europe/Istanbul", "--low-signal-source", "sample-chat-transcript")
    assert first.returncode == 0, first.stderr
    shown = _run(tmp_path, "--show")
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout) == {"timezone": "Europe/Istanbul", "low_signal_sources": ["sample-chat-transcript"]}
    assert json.loads(_run(tmp_path).stdout) == json.loads(shown.stdout)


def test_cli_dedups_and_clears(tmp_path):
    _project(tmp_path)
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
    assert result.returncode == 2
    assert "error: invalid project id" in result.stderr
    assert "Traceback" not in result.stderr
    assert not runtime.exists()
    assert list(tmp_path.iterdir()) == []


def test_cli_invalid_timezone_writes_nothing(tmp_path):
    project_dir = _project(tmp_path)
    for tz in ("Mars/Olympus", "../etc/passwd", ""):
        result = _run(tmp_path, "--timezone", tz)
        assert result.returncode == 2
        assert "error: unknown time zone" in result.stderr
        assert "Traceback" not in result.stderr
    assert list(project_dir.iterdir()) == []


def test_cli_missing_project_dir_creates_nothing(tmp_path):
    runtime = tmp_path / "runtime"
    result = _run(runtime, "--timezone", "Europe/Istanbul")
    assert result.returncode == 2
    assert "error: project directory not found" in result.stderr
    assert not runtime.exists()


def test_cli_combined_flags_strip_and_keep(tmp_path):
    _project(tmp_path)
    assert _run(tmp_path, "--timezone", "Europe/Istanbul", "--low-signal-source", "old-feed").returncode == 0
    assert _run(tmp_path, "--clear-low-signal", "--low-signal-source", "  new-feed  ").returncode == 0
    assert json.loads(_run(tmp_path).stdout) == {"timezone": "Europe/Istanbul", "low_signal_sources": ["new-feed"]}
    assert _run(tmp_path, "--timezone", "UTC").returncode == 0
    assert json.loads(_run(tmp_path).stdout)["low_signal_sources"] == ["new-feed"]


def test_cli_invalid_source_leaves_file_unchanged(tmp_path):
    _project(tmp_path)
    assert _run(tmp_path, "--low-signal-source", "sample-chat-transcript").returncode == 0
    before = json.loads(_run(tmp_path).stdout)
    for bad in ("", "x" * 121):
        result = _run(tmp_path, "--low-signal-source", bad)
        assert result.returncode == 2
        assert "error: invalid low-signal source" in result.stderr
    assert json.loads(_run(tmp_path).stdout) == before
