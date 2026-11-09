"""Reusing history blocks from the previous run of a wiki export.

A block is reused only when the previous manifest says the key's stored
entry is unchanged, the run marker (the newest ``__system`` history entry,
which every rollback changes) is unchanged, and the block read back from the
previous page hashes to what that run recorded. See the design addendum A1.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from bilinc.wiki.manifest import ManifestError, validate_rel_path

#: Largest previous page read back; a bigger file is never reused.
PAGE_READ_LIMIT = 8 * 1024 * 1024

_HEX64 = re.compile(r"[0-9a-f]{64}")
#: An opening fence as :func:`bilinc.wiki.render.fence` writes it: three or
#: more backticks and an info string without backticks. It closes on a line
#: holding exactly the same backticks.
_FENCE = re.compile(r"(`{3,})[^`]*")


def history_body(page: str) -> str | None:
    """The ``## History`` section body of one of our pages, trailing newlines stripped.

    The body is the text after ``## History`` and its blank line, up to the
    next top-level ``## `` heading or the end of the page. Lines inside
    fences are skipped, so a value or a history detail holding heading-like
    lines cannot move the boundary. ``None`` when there is no such section.
    """
    lines = page.split("\n")
    fence = None
    start = None
    for index, line in enumerate(lines):
        if fence is not None:
            if line == fence:
                fence = None
            continue
        opened = _FENCE.fullmatch(line)
        if opened:
            fence = opened.group(1)
            continue
        if line.startswith("## "):
            if start is not None:
                return "\n".join(lines[start:index]).rstrip("\n")
            if line == "## History" and index + 1 < len(lines) and lines[index + 1] == "":
                start = index + 2
    if start is None:
        return None
    return "\n".join(lines[start:]).rstrip("\n")


def history_digest(body: str) -> str:
    """sha256 hex of ``body`` as the page file stores it (a lone surrogate is ``?``)."""
    return hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()


def read_previous_body(target: Path, rel: str) -> str | None:
    """Read the history body of ``target/rel`` without following any symlink.

    ``None`` when the path is unsafe, a folder on the way or the file itself
    is not real (a symlink, a folder), the file is over
    :data:`PAGE_READ_LIMIT`, is not UTF-8, or has no history section.
    """
    try:
        validate_rel_path(rel)
    except ManifestError:
        return None
    current = Path(target)
    for part in rel.split("/")[:-1]:
        current = current / part
        try:
            if not stat.S_ISDIR(os.lstat(current).st_mode):
                return None
        except OSError:
            return None
    try:
        # Checked before opening too: opening a FIFO for reading would block.
        if not stat.S_ISREG(os.lstat(Path(target) / rel).st_mode):
            return None
    except OSError:
        return None
    # O_NONBLOCK: a FIFO swapped in after the check still cannot hang the run.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(Path(target) / rel, flags)
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > PAGE_READ_LIMIT:
                return None
            raw = handle.read(PAGE_READ_LIMIT + 1)
    except OSError:
        return None
    if len(raw) > PAGE_READ_LIMIT:
        return None
    try:
        return history_body(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return None


def reusable_keys(
    entries: Iterable[dict[str, Any]],
    previous: dict[str, Any] | None,
    *,
    history: int,
    marker: str | None,
    refresh: bool,
    version: str,
    history_format: int,
) -> set[str]:
    """Keys whose block may be read back from the previous page (manifest rules only).

    Covers rules 1 to 6 of addendum A1; the caller still checks the page
    itself (rule 7: path in ``files``, :func:`read_previous_body`, digest).
    ``history`` is validated by the caller (never a bool).
    """
    if refresh or history <= 0 or previous is None or marker is None:
        return set()
    if (
        previous.get("complete") is not True
        or previous.get("tool_version") != version
        or previous.get("history_format") != history_format
        or previous.get("history") != history
        or previous.get("history_marker") != marker
    ):
        return set()
    keys = previous.get("keys")
    if not isinstance(keys, dict):
        return set()
    result: set[str] = set()
    for entry in entries:
        key = entry.get("key")
        old = keys.get(key) if isinstance(key, str) else None
        if not isinstance(old, dict):
            continue
        version_now, updated_now = entry.get("entryVersion"), entry.get("updatedAt")
        if not (isinstance(version_now, str) and version_now and isinstance(updated_now, str) and updated_now):
            continue
        if old.get("entry_version") != version_now or old.get("updated_at") != updated_now:
            continue
        digest = old.get("history_sha256")
        if not (isinstance(digest, str) and _HEX64.fullmatch(digest)):
            continue
        result.add(key)
    return result
