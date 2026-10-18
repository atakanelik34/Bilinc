"""
Commit an exchange together with facts distilled from it.

An agent that distils what it hears into short standalone facts (with its own
LLM, or any function) stores far more of a long conversation within a fixed
recall budget. ``commit_distilled`` keeps the raw exchange as the source and
writes each fact as its own memory that points back to it, with the source's
exact timestamp, so time-scoped recall and ``expand_sources`` keep working::

    keys = await commit_distilled(plane, "t042", exchange_text, my_llm_extract,
                                  timestamp="2024-03-15T12:00:00+00:00")
    hits = await plane.recall_reflective(question, memory_types=[MemoryType.SEMANTIC],
                                         expand_sources=True)
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from bilinc.core.models import MemoryType

Extractor = Callable[[str], Union[List[str], Awaitable[List[str]]]]


async def commit_distilled(
    plane: Any,
    source_key: str,
    text: str,
    extract: Extractor,
    *,
    timestamp: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    fact_type: MemoryType = MemoryType.SEMANTIC,
    source_type: MemoryType = MemoryType.EPISODIC,
    max_facts: int = 50,
) -> List[str]:
    """Commit ``text`` under ``source_key`` and each extracted fact as ``<source_key>#f<n>``.

    Facts go in as ``fact_type`` and the source as ``source_type`` so recall can
    search facts only and fetch sources through ``expand_sources``. Returns the
    fact keys.
    """
    base_meta = dict(metadata or {})
    if timestamp:
        base_meta["source_timestamp"] = timestamp
    await plane.commit(source_key, text, source_type, metadata=dict(base_meta))
    facts = extract(text)
    if inspect.isawaitable(facts):
        facts = await facts
    keys: List[str] = []
    for index, fact in enumerate([f.strip() for f in facts or [] if f and f.strip()][:max_facts]):
        key = f"{source_key}#f{index:02d}"
        await plane.commit(key, fact, fact_type, metadata={**base_meta, "source_key": source_key, "distilled": True})
        keys.append(key)
    return keys
