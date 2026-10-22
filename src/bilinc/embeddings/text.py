"""The text the encoder sees for a memory: its key and decoded value, in chunks.

The encoder gets the real letters. The search fold (``bilinc.core.text_fold``)
strips diacritics for lexical matching and must not be applied here.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterator, List

QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
CHUNK_WORDS = 180
_KEY_SEPARATORS = re.compile(r"[:_\-./]+")


def _strings(value: Any) -> Iterator[str]:
    if value is None:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _strings(item)
    else:
        yield str(value)


def decode_stored_value(raw: Any) -> Any:
    """A ``memories.value`` column as stored (``json.dumps`` text), decoded."""
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def memory_text(key: str, value: Any) -> str:
    """Key words followed by every string in the value, in document order."""
    parts = [_KEY_SEPARATORS.sub(" ", str(key or "")).strip()]
    parts.extend(text.strip() for text in _strings(value) if str(text).strip())
    return "\n".join(part for part in parts if part)


def chunk_words(text: str, words: int = CHUNK_WORDS) -> List[str]:
    """Split into chunks of at most ``words`` words; short text stays whole."""
    tokens = text.split()
    if not tokens:
        return []
    return [" ".join(tokens[start:start + words]) for start in range(0, len(tokens), words)]


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
