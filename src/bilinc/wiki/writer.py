"""Every disk operation of the wiki export.

The writer only ever creates, replaces or deletes paths listed in the
previous manifest or produced by this run, and it never follows a symbolic
link inside the target folder. A run builds every file in a temporary folder
first; the previous wiki stays as it was until that build has succeeded and
every path it will write through has been checked.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from bilinc.wiki.manifest import (
    MANIFEST_NAME,
    TMP_NAME,
    ManifestError,
    dumps_manifest,
    read_manifest,
    validate_rel_path,
)

#: Entries an editor creates in a fresh folder. A folder holding only these
#: counts as empty, and the export never touches them.
IGNORED_ENTRIES = frozenset({".obsidian", ".trash", ".DS_Store"})

DIR_MODE = 0o700
FILE_MODE = 0o600


class WikiExportError(Exception):
    """The export stopped; the previous wiki (if any) is left as it was."""


class WikiRefused(WikiExportError):
    """The export refused to write into this folder; nothing was changed."""


@dataclass
class WriteResult:
    written: int = 0
    removed: list[str] = field(default_factory=list)
    #: Previously exported paths left alone because a folder on the way is
    #: no longer a real folder, or the path itself became a folder.
    skipped: list[str] = field(default_factory=list)


def inspect_target(target: Path, *, base_url: str, prefix: str | None) -> dict[str, Any] | None:
    """Return the previous manifest, None for a new or empty folder, or refuse.

    Changes nothing on disk.
    """

    target = Path(target)
    if not os.path.lexists(target):
        if not target.parent.is_dir():
            raise WikiRefused(f"{target.parent} does not exist; create it first")
        return None
    if target.is_symlink():
        raise WikiRefused(f"{target} is a symbolic link; give the real folder instead")
    if not target.is_dir():
        raise WikiRefused(f"{target} is not a folder")

    entries = set(os.listdir(target))
    if MANIFEST_NAME in entries:
        try:
            manifest = read_manifest(target)
        except ManifestError as exc:
            raise WikiRefused(f"{target / MANIFEST_NAME} cannot be used: {exc}") from exc
        assert manifest is not None
        if manifest.get("base_url") != base_url or manifest.get("prefix") != prefix:
            raise WikiRefused(
                f"{target} holds an export of {manifest.get('base_url')} with prefix "
                f"{manifest.get('prefix')!r}; this run is {base_url} with prefix {prefix!r}. "
                "Use another folder to export a different workspace or prefix."
            )
        return manifest

    remaining = entries - IGNORED_ENTRIES
    if not remaining:
        return None
    if TMP_NAME in remaining:
        raise WikiRefused(
            f"{target} is not a Bilinc wiki folder: it has no {MANIFEST_NAME}, only "
            f"{TMP_NAME} left by an interrupted first export. Remove {target / TMP_NAME} and run again."
        )
    raise WikiRefused(
        f"{target} is not a Bilinc wiki folder (it is not empty and has no {MANIFEST_NAME}); "
        "choose an empty or new folder"
    )


def write_tree(
    target: Path,
    files: dict[str, str],
    *,
    previous: dict[str, Any] | None,
    manifest_for: Callable[[bool, list[str]], dict[str, Any]],
) -> WriteResult:
    """Replace the previous export in ``target`` with ``files`` (relative path → text)."""

    target = Path(target)
    wanted = sorted(validate_rel_path(rel) for rel in files)
    owned = set(previous["files"]) if previous else set()
    created_target = False
    if not os.path.lexists(target):
        os.mkdir(target, DIR_MODE)
        created_target = True

    temp = target / TMP_NAME
    try:
        _build_in_temp(temp, files, wanted, previous_exists=previous is not None)
        _check_paths(target, wanted, owned)
    except BaseException as exc:
        _discard_temp(temp)
        if created_target:
            with contextlib.suppress(OSError):
                target.rmdir()
        if isinstance(exc, OSError):
            raise WikiExportError(f"could not write the wiki: {exc}") from exc
        raise

    result = WriteResult()
    try:
        # Own every path this run may leave behind before the first move, so a
        # crash halfway never strands files the next run would treat as the user's.
        _write_manifest(target, manifest_for(False, sorted(owned | set(wanted))))
        for rel in wanted:
            _ensure_folders(target, rel)
            source = temp / rel
            os.chmod(source, FILE_MODE)
            os.replace(source, target / rel)
            result.written += 1
        _remove_stale(target, sorted(owned - set(wanted)), result)
        _write_manifest(target, manifest_for(True, wanted))
    except OSError as exc:
        raise WikiExportError(f"could not finish writing the wiki: {exc}") from exc
    _discard_temp(temp)
    os.chmod(target, DIR_MODE)
    return result


def _build_in_temp(temp: Path, files: dict[str, str], wanted: list[str], *, previous_exists: bool) -> None:
    if os.path.lexists(temp):
        if temp.is_symlink() or not temp.is_dir():
            raise WikiRefused(f"{temp} is not a folder this tool made; remove it and run again")
        if not previous_exists:
            raise WikiRefused(f"{temp} was left by an interrupted export; remove it and run again")
        shutil.rmtree(temp)
    os.mkdir(temp, DIR_MODE)
    for rel in wanted:
        path = temp / rel
        for parent in reversed(path.relative_to(temp).parents[:-1]):
            folder = temp / parent
            if not folder.is_dir():
                os.mkdir(folder, DIR_MODE)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, FILE_MODE)
        # errors="replace": a lone surrogate (valid in JSON, not in UTF-8) becomes "?".
        with os.fdopen(fd, "w", encoding="utf-8", errors="replace", newline="\n") as handle:
            handle.write(files[rel])


def _check_paths(target: Path, wanted: list[str], owned: set[str]) -> None:
    """Refuse before anything moves if a path this run needs is not ours to write."""

    folders = sorted({parent.as_posix() for rel in wanted for parent in Path(rel).parents if parent != Path(".")})
    for folder in folders:
        info = _lstat(target / folder)
        if info is not None and not stat.S_ISDIR(info.st_mode):
            raise WikiRefused(f"{target / folder} is in the way: the export needs a real folder there")
    for rel in wanted:
        info = _lstat(target / rel)
        if info is None:
            continue
        if rel not in owned:
            raise WikiRefused(f"{target / rel} exists and was not written by this tool; move it away and run again")
        if stat.S_ISDIR(info.st_mode):
            raise WikiRefused(f"{target / rel} is now a folder; move it away and run again")


def _ensure_folders(target: Path, rel: str) -> None:
    current = target
    for part in Path(rel).parts[:-1]:
        current = current / part
        if _lstat(current) is None:
            os.mkdir(current, DIR_MODE)
        os.chmod(current, DIR_MODE)


def _remove_stale(target: Path, stale: list[str], result: WriteResult) -> None:
    emptied: set[Path] = set()
    for rel in stale:
        validate_rel_path(rel)
        parts = Path(rel).parts
        current = target
        blocked = False
        for part in parts[:-1]:
            current = current / part
            info = _lstat(current)
            if info is None:
                blocked = None  # nothing left to delete
                break
            if not stat.S_ISDIR(info.st_mode):
                blocked = True
                break
        if blocked is None:
            continue
        path = target / rel
        info = None if blocked else _lstat(path)
        if blocked or (info is not None and stat.S_ISDIR(info.st_mode)):
            result.skipped.append(rel)
            continue
        if info is None:
            continue
        os.unlink(path)
        result.removed.append(rel)
        emptied.update(target / parent for parent in Path(rel).parents if parent != Path("."))
    for folder in sorted(emptied, key=lambda p: len(p.parts), reverse=True):
        with contextlib.suppress(OSError):
            folder.rmdir()


def _write_manifest(target: Path, manifest: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".bilinc-wiki-manifest-", suffix=".json", dir=target)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="replace", newline="\n") as handle:
            handle.write(dumps_manifest(manifest))
        os.chmod(temporary, FILE_MODE)
        os.replace(temporary, target / MANIFEST_NAME)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def _discard_temp(temp: Path) -> None:
    if os.path.lexists(temp) and not temp.is_symlink() and temp.is_dir():
        shutil.rmtree(temp, ignore_errors=True)


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
