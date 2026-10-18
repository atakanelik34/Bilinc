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
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from bilinc.core.models import MemoryType

Extractor = Callable[[str], Union[List[str], Awaitable[List[str]]]]

_FACT_SUFFIX = re.compile(r"#f\d+$")


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
    search facts only and fetch sources through ``expand_sources``. The extractor
    runs before anything is written. Committing the same ``source_key`` again
    replaces its facts and forgets any earlier ones beyond the new count. The stored
    source always names at least as many facts as exist (it is updated before facts
    are added and after extra ones are forgotten), so a retry after a failed write
    cleans up. Returns the fact keys.
    A ``source_key`` may not itself end in ``#f<n>``: that is the fact key space.
    """
    if _FACT_SUFFIX.search(source_key):
        raise ValueError(f"source_key {source_key!r} ends like a distilled fact key (#f<n>)")
    base_meta = dict(metadata or {})
    if timestamp:
        base_meta["source_timestamp"] = timestamp
    facts = extract(text)  # before any write: a failing extractor leaves the stored source and facts intact
    if inspect.isawaitable(facts):
        facts = await facts
    if isinstance(facts, str):  # one fact, not a sequence of characters
        facts = [facts]
    facts = [str(f).strip() for f in facts or [] if f and str(f).strip()][:max_facts]

    previous = await plane._load_any(source_key)
    previous_count = int(((previous.metadata or {}) if previous is not None else {}).get("distilled_facts") or 0)
    if len(facts) > previous_count:
        # Record the larger count before writing more facts, so a failure partway
        # through cannot leave facts the source does not account for.
        await plane.commit(source_key, text, source_type, metadata={**base_meta, "distilled_facts": len(facts)})
    keys: List[str] = []
    for index, fact in enumerate(facts):
        key = f"{source_key}#f{index:02d}"
        await plane.commit(key, fact, fact_type, metadata={**base_meta, "source_key": source_key, "distilled": True})
        keys.append(key)
    for index in range(len(facts), previous_count):  # facts the earlier version had beyond the new count
        key = f"{source_key}#f{index:02d}"
        if await plane._load_any(key) is not None:
            await plane.forget(key)
    await plane.commit(source_key, text, source_type, metadata={**base_meta, "distilled_facts": len(facts)})
    return keys
