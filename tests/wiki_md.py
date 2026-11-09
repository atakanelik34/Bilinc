"""A small CommonMark-fence-aware scanner for wiki rendering tests.

It finds the structure a Markdown reader would see outside fenced code: ATX and
setext headings and inline / reference link targets. YAML frontmatter at the
top of a page is skipped.
"""

from __future__ import annotations

import re

_LINE_BREAK = re.compile(r"\r\n|\r|\n")
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_ATX = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
_SETEXT = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
_INLINE_LINK = re.compile(r"(?<!\\)\]\(\s*<?([^)\s>]*)")
_REFERENCE_DEF = re.compile(r"^ {0,3}\[[^\]]*\]:\s*<?(\S*?)>?(?:\s|$)")
_AUTOLINK = re.compile(r"(?<!\\)<([A-Za-z][A-Za-z0-9+.\-]{1,31}:[^<>\s]*)>")


def _lines_outside_fences(text: str) -> list[tuple[str, bool]]:
    """Return ``(line, outside)`` pairs; fence lines themselves are inside."""
    lines = _LINE_BREAK.split(text)
    start = 0
    if lines and lines[0] == "---":
        for index in range(1, len(lines)):
            if lines[index] == "---":
                start = index + 1
                break
    result: list[tuple[str, bool]] = []
    open_char = ""
    open_len = 0
    for line in lines[start:]:
        if open_char:
            result.append((line, False))
            close = re.match(rf"^ {{0,3}}({re.escape(open_char)}+)[ \t]*$", line)
            if close and len(close.group(1)) >= open_len:
                open_char, open_len = "", 0
            continue
        opened = _FENCE_OPEN.match(line)
        if opened and not (opened.group(1)[0] == "`" and "`" in opened.group(2)):
            open_char, open_len = opened.group(1)[0], len(opened.group(1))
            result.append((line, False))
            continue
        result.append((line, True))
    return result


def headings_outside_fences(text: str) -> list[str]:
    """Return every heading line outside fences.

    ATX headings are returned as written; a setext heading is returned as
    ``"setext: <paragraph line>"``.
    """
    headings: list[str] = []
    previous = ""
    previous_outside = False
    for line, outside in _lines_outside_fences(text):
        if outside:
            if _ATX.match(line):
                headings.append(line)
            elif (
                _SETEXT.match(line)
                and previous_outside
                and previous.strip()
                and not _ATX.match(previous)
                and not re.match(r"^ {0,3}[-*+] ", previous)
            ):
                headings.append(f"setext: {previous}")
        previous, previous_outside = line, outside
    return headings


def link_targets_outside_fences(text: str) -> list[str]:
    """Return every inline, reference and autolink target outside fences."""
    targets: list[str] = []
    for line, outside in _lines_outside_fences(text):
        if not outside:
            continue
        targets.extend(_INLINE_LINK.findall(line))
        targets.extend(_AUTOLINK.findall(line))
        ref = _REFERENCE_DEF.match(line)
        if ref:
            targets.append(ref.group(1))
    return targets
