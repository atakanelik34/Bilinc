"""The wiki manifest ``.bilinc-wiki.json`` (``bilinc.wiki.manifest``)."""

from __future__ import annotations

import json
import os

import pytest

from bilinc.wiki.manifest import (
    FORMAT,
    MANIFEST_NAME,
    TMP_NAME,
    TOOL,
    ManifestError,
    build_manifest,
    dumps_manifest,
    read_manifest,
    validate_rel_path,
)

KEYS = {
    "project:bilinc:release": {
        "path": "project/bilinc/release.md",
        "entry_version": "v3",
        "updated_at": "2026-11-08T10:00:00Z",
    },
    "note": {"path": "note.md", "entry_version": "v1", "updated_at": "2026-11-01T00:00:00Z"},
}
FILES = ["index.md", "AGENTS.md", "project/bilinc/release.md", "note.md", "project/_index.md"]


def _build(files=FILES, keys=KEYS, **overrides):
    arguments = {
        "version": "2.7.0",
        "base_url": "https://bilinc.space",
        "prefix": None,
        "history": 5,
        "exported_at": "2026-11-09T01:00:00Z",
        "complete": True,
        "files": files,
        "keys": keys,
    }
    arguments.update(overrides)
    return build_manifest(**arguments)


def _write(directory, text):
    (directory / MANIFEST_NAME).write_text(text, encoding="utf-8")


def test_constants():
    assert MANIFEST_NAME == ".bilinc-wiki.json"
    assert TMP_NAME == ".bilinc-wiki.tmp"
    assert FORMAT == 1
    assert TOOL == "bilinc wiki"


def test_build_matches_the_design_shape():
    manifest = _build()
    assert manifest == {
        "format": 1,
        "tool": "bilinc wiki",
        "tool_version": "2.7.0",
        "base_url": "https://bilinc.space",
        "prefix": None,
        "history": 5,
        "exported_at": "2026-11-09T01:00:00Z",
        "complete": True,
        "files": sorted(FILES),
        "keys": KEYS,
    }


def test_build_rejects_invalid_file_paths():
    with pytest.raises(ManifestError):
        _build(files=["ok.md", "../escape.md"])


def test_round_trip(tmp_path):
    manifest = _build(prefix="project:", complete=False)
    _write(tmp_path, dumps_manifest(manifest))
    loaded = read_manifest(tmp_path)
    assert loaded == manifest
    assert loaded["files"] == sorted(FILES)


@pytest.mark.parametrize(
    "bad",
    [
        "../x",
        "/etc/x",
        "a//b",
        "a\\..\\b",
        "a\\b",
        "C:x",
        "C:/x",
        ".",
        "",
        "a/../b",
        "..",
        "a/./b",
        ".obsidian/app.json",
        ".bilinc-wiki.json",
        ".bilinc-wiki.tmp/x.md",
        "a/.hidden",
        "a/",
        "x\x00y",
    ],
)
def test_invalid_paths_rejected(bad):
    with pytest.raises(ManifestError):
        validate_rel_path(bad)


@pytest.mark.parametrize("bad", [None, 3, b"a.md"])
def test_non_string_paths_rejected(bad):
    with pytest.raises(ManifestError):
        validate_rel_path(bad)


@pytest.mark.parametrize(
    "good", ["index.md", "project/bilinc/release.md", "a%2Fb.md", "ü/x~abc123.md"]
)
def test_valid_paths_accepted(good):
    assert validate_rel_path(good) == good


def test_read_manifest_absent_is_none(tmp_path):
    assert read_manifest(tmp_path) is None


def test_read_manifest_symlink_rejected(tmp_path):
    real = tmp_path / "real.json"
    real.write_text(dumps_manifest(_build()), encoding="utf-8")
    os.symlink(real, tmp_path / MANIFEST_NAME)
    with pytest.raises(ManifestError):
        read_manifest(tmp_path)


def test_read_manifest_dangling_symlink_rejected(tmp_path):
    os.symlink(tmp_path / "missing.json", tmp_path / MANIFEST_NAME)
    with pytest.raises(ManifestError):
        read_manifest(tmp_path)


def test_read_manifest_directory_rejected(tmp_path):
    (tmp_path / MANIFEST_NAME).mkdir()
    with pytest.raises(ManifestError):
        read_manifest(tmp_path)


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "[]",
        "",
        json.dumps({"tool": "other"}),
        json.dumps({"format": 2}),
        "\udcff",
    ],
)
def test_read_manifest_garbage_rejected(tmp_path, text):
    if text == "\udcff":
        (tmp_path / MANIFEST_NAME).write_bytes(b"\xff\xfe{")
    else:
        _write(tmp_path, text)
    with pytest.raises(ManifestError):
        read_manifest(tmp_path)


@pytest.mark.parametrize(
    "change",
    [
        {"tool": "other"},
        {"format": 2},
        {"format": True},
        {"files": "index.md"},
        {"files": ["index.md", 3]},
        {"files": ["index.md", "index.md"]},
        {"keys": []},
        {"keys": {"note": "note.md"}},
        {"keys": {"note": {"path": "../note.md"}}},
        {"base_url": 3},
        {"prefix": 3},
        {"complete": "yes"},
    ],
)
def test_read_manifest_bad_fields_rejected(tmp_path, change):
    manifest = _build()
    manifest.update(change)
    _write(tmp_path, json.dumps(manifest))
    with pytest.raises(ManifestError):
        read_manifest(tmp_path)


@pytest.mark.parametrize("bad", [".obsidian/app.json", "../x", "a\\b", "/etc/passwd"])
def test_read_manifest_bad_file_entry_rejected(tmp_path, bad):
    manifest = _build()
    manifest["files"] = ["index.md", bad]
    _write(tmp_path, json.dumps(manifest))
    with pytest.raises(ManifestError):
        read_manifest(tmp_path)


def test_dumps_is_deterministic():
    reordered_keys = dict(reversed(list(KEYS.items())))
    first = dumps_manifest(_build())
    second = dumps_manifest(_build(files=list(reversed(FILES)), keys=reordered_keys))
    assert first == second
    assert first.endswith("}\n")
    assert (
        first == json.dumps(json.loads(first), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def test_dumps_keeps_non_ascii():
    text = dumps_manifest(_build(prefix="proje:ş"))
    assert '"proje:ş"' in text
