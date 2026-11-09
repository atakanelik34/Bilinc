"""The ``.bilinc-wiki.json`` manifest: which files a wiki folder's last run wrote.

A corrupt or hostile manifest must never make a run touch files the tool did
not write, so every path is validated on read and an invalid manifest is a
refusal, never a partial run.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterable
from pathlib import Path
from typing import Any

MANIFEST_NAME = ".bilinc-wiki.json"
TMP_NAME = ".bilinc-wiki.tmp"
FORMAT = 1
TOOL = "bilinc wiki"


class ManifestError(ValueError):
    """The manifest is missing pieces, unreadable, or names an unsafe path."""


def validate_rel_path(path: str) -> str:
    """Return ``path`` when it is a safe relative ``/``-separated file path.

    Refuses absolute paths, backslashes, drive prefixes (any ``:``), NUL,
    empty, ``.`` or ``..`` components, and any component starting with ``.``
    (generated paths never do, so ``.obsidian/``, the manifest and the temp
    folder can never be named).
    """

    if not isinstance(path, str) or not path:
        raise ManifestError(f"invalid path in manifest: {path!r}")
    if path.startswith("/") or "\\" in path or ":" in path or "\x00" in path:
        raise ManifestError(f"invalid path in manifest: {path!r}")
    for part in path.split("/"):
        if not part or part.startswith("."):
            raise ManifestError(f"invalid path in manifest: {path!r}")
    return path


def _validated_files(files: Iterable[Any]) -> list[str]:
    result = sorted(validate_rel_path(path) for path in files)
    if len(set(result)) != len(result):
        raise ManifestError("duplicate path in manifest")
    return result


def _validated_keys(keys: Any) -> dict[str, dict]:
    if not isinstance(keys, dict):
        raise ManifestError("manifest keys must be an object")
    result: dict[str, dict] = {}
    for key in sorted(keys):
        entry = keys[key]
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise ManifestError(f"invalid manifest entry for key {key!r}")
        validate_rel_path(entry.get("path"))
        result[key] = dict(entry)
    return result


def build_manifest(
    *,
    version: str,
    base_url: str,
    prefix: str | None,
    history: int,
    exported_at: str,
    complete: bool,
    files: Iterable[str],
    keys: dict[str, dict],
) -> dict:
    """Return the manifest dict for one run; ``files`` sorted and validated."""

    return {
        "format": FORMAT,
        "tool": TOOL,
        "tool_version": version,
        "base_url": base_url,
        "prefix": prefix,
        "history": history,
        "exported_at": exported_at,
        "complete": complete,
        "files": _validated_files(files),
        "keys": _validated_keys(keys),
    }


def dumps_manifest(manifest: dict) -> str:
    """Serialise deterministically (sorted keys, two-space indent, final newline)."""

    return json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _read_regular_file(path: Path) -> bytes | None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ManifestError(f"{path.name} is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ManifestError(f"cannot read {path.name}: {exc.strerror or exc}") from exc
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ManifestError(f"{path.name} is not a regular file")
        return handle.read()


def read_manifest(directory: Path) -> dict | None:
    """Read and validate ``<directory>/.bilinc-wiki.json``; None when absent."""

    raw = _read_regular_file(Path(directory) / MANIFEST_NAME)
    if raw is None:
        return None
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"{MANIFEST_NAME} is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise ManifestError(f"{MANIFEST_NAME} is not a JSON object")
    if manifest.get("tool") != TOOL:
        raise ManifestError(f"{MANIFEST_NAME} was not written by {TOOL}")
    format_ = manifest.get("format")
    if isinstance(format_, bool) or format_ != FORMAT:
        raise ManifestError(f"{MANIFEST_NAME} has unsupported format {format_!r}")
    if not isinstance(manifest.get("base_url"), str):
        raise ManifestError(f"{MANIFEST_NAME} has no base_url")
    if manifest.get("prefix") is not None and not isinstance(manifest["prefix"], str):
        raise ManifestError(f"{MANIFEST_NAME} has an invalid prefix")
    if not isinstance(manifest.get("complete"), bool):
        raise ManifestError(f"{MANIFEST_NAME} has an invalid complete flag")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ManifestError(f"{MANIFEST_NAME} files must be a list")
    manifest["files"] = _validated_files(files)
    manifest["keys"] = _validated_keys(manifest.get("keys"))
    return manifest
