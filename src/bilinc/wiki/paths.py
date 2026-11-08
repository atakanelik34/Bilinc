"""Map Bilinc keys to relative wiki page paths.

A key ``a:b:c`` becomes the page ``a/b/c.md``. Every segment is escaped so it is
a safe file name on POSIX, macOS and Windows; names are capped in bytes, made
unique per folder (case- and NFC-insensitively) and kept clear of the names the
export writes itself (``index.md``, ``_index.md``, ``AGENTS.md``).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

#: Maximum UTF-8 length of one file or folder name (``.md`` included).
MAX_NAME_BYTES = 120
#: Page stems (casefolded) that would clash with the export's own files.
RESERVED_STEMS = frozenset({"index", "_index", "agents"})
#: Folder names (casefolded) that would sit at the path of a generated file.
_RESERVED_FOLDER_NAMES = frozenset(f"{stem}.md" for stem in RESERVED_STEMS)
_PAGE_EXT = ".md"
_SUFFIX_BYTES = 7  # "~" + 6 hex characters
_TOKEN = re.compile(r"%[0-9A-F]{2}|.", re.DOTALL)

#: Characters that are never allowed verbatim in a file name segment.
_UNSAFE_CHARS = frozenset('/\\?*|"<>:')
#: Windows device names, any case, with or without an extension.
_WINDOWS_DEVICE = re.compile(
    r"(con|prn|aux|nul|com[1-9\u00b9\u00b2\u00b3]|lpt[1-9\u00b9\u00b2\u00b3]|conin\$|conout\$)"
    r"(\..*)?",
    re.IGNORECASE | re.DOTALL,
)
_TRAILING_SPACES_DOTS = re.compile(r"[ .]+\Z")


def key_hash(text: str) -> str:
    """Return the first 6 hex characters of the sha256 of ``text`` (UTF-8)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:6]


def _percent(char: str) -> str:
    """Return ``char`` as ``%XX`` escapes of its UTF-8 bytes (uppercase hex)."""
    return "".join(f"%{byte:02X}" for byte in char.encode("utf-8"))


def _needs_escape(char: str) -> bool:
    code = ord(char)
    return char in _UNSAFE_CHARS or code < 0x20 or code == 0x7F


def escape_segment(segment: str) -> str:
    """Escape one ``:``-separated key segment into a safe file name.

    Order: ``%`` first (so escaping stays unambiguous), then unsafe and
    control characters, a leading ``.``, a trailing run of spaces and dots and
    the first character of a Windows device name. An empty segment is ``_``.
    """
    if segment == "":
        return "_"
    text = segment.replace("%", "%25")
    text = "".join(_percent(ch) if _needs_escape(ch) else ch for ch in text)
    if text.startswith("."):
        text = "%2E" + text[1:]
    trailing = _TRAILING_SPACES_DOTS.search(text)
    if trailing:
        text = text[: trailing.start()] + "".join(_percent(ch) for ch in trailing.group())
    if _WINDOWS_DEVICE.fullmatch(text):
        text = _percent(text[0]) + text[1:]
    return text


def _fold(name: str) -> str:
    """Return the form two names are compared in (NFC, casefolded)."""
    return unicodedata.normalize("NFC", name).casefold()


def _cut(name: str, budget: int) -> str:
    """Cut ``name`` to at most ``budget`` UTF-8 bytes, never inside a character
    or a ``%XX`` escape."""
    out: list[str] = []
    used = 0
    for token in _TOKEN.findall(name):
        size = len(token.encode("utf-8"))
        if used + size > budget:
            break
        out.append(token)
        used += size
    return "".join(out)


def _suffixed(name: str, ext: str, digest: str) -> str:
    """Append ``~digest`` to ``name``, cutting it so the name stays capped."""
    budget = MAX_NAME_BYTES - len(ext) - _SUFFIX_BYTES
    return f"{_cut(name, budget)}~{digest}"


def _capped(name: str, ext: str, digest: str) -> str:
    """Return ``name`` unchanged when it fits, else cut and suffixed."""
    if len(name.encode("utf-8")) + len(ext) <= MAX_NAME_BYTES:
        return name
    return _suffixed(name, ext, digest)


@dataclass
class _Folder:
    """One folder of the key tree, keyed by escaped child names."""

    prefixes: set[str] = field(default_factory=set)
    folders: dict[str, _Folder] = field(default_factory=dict)
    pages: list[tuple[str, str]] = field(default_factory=list)  # (key, escaped name)


@dataclass
class _Name:
    """A child of a folder while its final name is being decided."""

    ext: str
    digest: str
    name: str
    target: str | _Folder  # the key (page) or the subfolder


def _initial_name(escaped: str, ext: str, digest: str) -> str:
    """Apply the reserved-name suffix, then the byte cap."""
    if ext:
        reserved = _fold(escaped) in RESERVED_STEMS
    else:
        reserved = _fold(escaped) in _RESERVED_FOLDER_NAMES
    if reserved:
        return _suffixed(escaped, ext, digest)
    return _capped(escaped, ext, digest)


def _final_names(folder: _Folder, where: str) -> list[_Name]:
    """Decide the final, unique names of ``folder``'s children."""
    children: list[_Name] = []
    for escaped, sub in sorted(folder.folders.items()):
        digest = key_hash(min(sub.prefixes))
        children.append(_Name("", digest, _initial_name(escaped, "", digest), sub))
    for key, escaped in sorted(folder.pages):
        digest = key_hash(key)
        children.append(
            _Name(_PAGE_EXT, digest, _initial_name(escaped, _PAGE_EXT, digest), key)
        )

    groups: dict[str, list[_Name]] = {}
    for child in children:
        groups.setdefault(_fold(child.name + child.ext), []).append(child)
    for group in groups.values():
        if len(group) > 1:
            for child in group:
                child.name = _suffixed(child.name, child.ext, child.digest)

    seen: dict[str, _Name] = {}
    for child in children:
        folded = _fold(child.name + child.ext)
        if folded in seen:
            raise ValueError(
                f"wiki path collision in {where or '.'!r}: "
                f"{seen[folded].name + seen[folded].ext!r} and {child.name + child.ext!r}"
            )
        seen[folded] = child
    return children


def _assign(root: _Folder) -> dict[str, str]:
    """Walk the tree (iteratively, so deep keys cannot exhaust the stack)."""
    out: dict[str, str] = {}
    stack: list[tuple[_Folder, str]] = [(root, "")]
    while stack:
        folder, where = stack.pop()
        for child in _final_names(folder, where):
            path = f"{where}/{child.name}" if where else child.name
            if isinstance(child.target, _Folder):
                stack.append((child.target, path))
            else:
                out[child.target] = path + child.ext
    return out


def build_paths(keys: Iterable[str]) -> dict[str, str]:
    """Map every key to a relative POSIX page path ending in ``.md``.

    The result depends only on the set of keys, never on their order. Raises
    ``ValueError`` when two names in one folder still collide after the
    collision suffix (an internal error; never silently overwritten).
    """
    root = _Folder()
    for key in sorted(set(keys)):
        segments = key.split(":")
        node = root
        for depth, segment in enumerate(segments[:-1], start=1):
            node = node.folders.setdefault(escape_segment(segment), _Folder())
            node.prefixes.add(":".join(segments[:depth]))
        node.pages.append((key, escape_segment(segments[-1])))
    out = _assign(root)
    return {key: out[key] for key in sorted(out)}
