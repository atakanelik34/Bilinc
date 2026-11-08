"""Mentions between wiki pages: which keys a value names, and the inverse."""

from __future__ import annotations

import json
import re
from typing import Any

#: Keys shorter than this are never matched (too many false hits).
MIN_LINK_KEY_LENGTH = 3

# A mention stands alone: not glued to a key-like character before it, and not
# continued by one after it. A "." or "-" after it ends the mention only when it
# is not followed by a letter or digit (sentence punctuation still links).
_BEFORE = r"(?<![A-Za-z0-9_:.\-/])"
_AFTER = r"(?![A-Za-z0-9_:/])(?![.\-][A-Za-z0-9])"


def value_text(value: Any) -> str:
    """The text a value is scanned as: a string as is, else its compact JSON."""

    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def find_links(values: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return ``(outgoing, incoming)`` mentions between the given keys.

    Every key is present in both maps; lists are sorted and never name the
    key itself. Only keys in ``values`` count.
    """

    outgoing: dict[str, list[str]] = {key: [] for key in values}
    incoming: dict[str, list[str]] = {key: [] for key in values}
    candidates = sorted(
        (key for key in values if len(key) >= MIN_LINK_KEY_LENGTH),
        key=lambda key: (-len(key), key),
    )
    if not candidates:
        return outgoing, incoming
    pattern = re.compile(_BEFORE + "(?:" + "|".join(map(re.escape, candidates)) + ")" + _AFTER)
    found: dict[str, set[str]] = {key: set() for key in values}
    for key, value in values.items():
        for match in pattern.finditer(value_text(value)):
            target = match.group(0)
            if target != key:
                found[key].add(target)
    for key in sorted(values):
        outgoing[key] = sorted(found[key])
        for target in outgoing[key]:
            incoming[target].append(key)
    return outgoing, incoming
