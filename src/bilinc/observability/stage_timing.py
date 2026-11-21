"""Per-request stage timings, reported as a ``Server-Timing`` header.

A request opens a scope with ``collect()``; code on the request path calls ``Stopwatch().lap(name)``
after each stage. Outside a scope every call is a no-op, so the library pays nothing when nobody asks.
Laps with the same name add up (a reflective recall runs several passes). Only the task that opened
the scope records: background tasks started during the request inherit the context variable, and
must not write into a response that has already been sent.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Dict, Iterator, Optional, Tuple

_current: ContextVar[Optional[Tuple[Dict[str, float], object]]] = ContextVar("bilinc_stage_timings", default=None)
_NAME = re.compile(r"[^A-Za-z0-9_-]")


@contextmanager
def collect() -> Iterator[Dict[str, float]]:
    """Collect stage durations (milliseconds) for the code run inside the block."""
    timings: Dict[str, float] = {}
    token = _current.set((timings, _owner()))
    try:
        yield timings
    finally:
        _current.reset(token)


def _owner() -> object:
    try:
        return asyncio.current_task()
    except RuntimeError:  # no running loop: the scope belongs to this thread's synchronous code
        return threading.get_ident()


class Stopwatch:
    """Times consecutive stages; ``lap(name)`` charges the time since the previous lap to ``name``."""

    __slots__ = ("_timings", "_last")

    def __init__(self) -> None:
        scope = _current.get()
        # == not `is`: a thread id is an int, and two equal ints need not be the same object.
        self._timings = scope[0] if scope is not None and scope[1] == _owner() else None
        self._last = time.perf_counter() if self._timings is not None else 0.0

    def lap(self, name: str) -> None:
        if self._timings is None:
            return
        now = time.perf_counter()
        self._timings[name] = self._timings.get(name, 0.0) + (now - self._last) * 1000.0
        self._last = now


def server_timing_header(timings: Dict[str, float]) -> str:
    """Format as ``name;dur=12.3`` entries (names reduced to header-safe characters)."""
    return ", ".join(f"{_NAME.sub('_', name)};dur={duration:.1f}" for name, duration in timings.items())
