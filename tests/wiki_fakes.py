"""Shared fakes for the wiki tests: a thread-safe routed transport and helpers.

No network: ``RoutedTransport`` answers the SDK's list and history routes from
scripted responses, and the error factories build the same typed errors the
real transport raises.
"""

from __future__ import annotations

import copy
import json
import os
import stat
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bilinc.client import BilincConnectionError, CloudClient, error_for_response

LIST_PATH = "/api/cloud/memory/list"
HISTORY_PATH = "/api/cloud/memory/history"
TEST_API_KEY = "bil_live_example"
TEST_BASE_URL = "https://bilinc.space"
MARKER_KEY = "__system"
#: The rollback marker's answer when no rollback ever happened.
NO_ROLLBACK = {"key": MARKER_KEY, "exists": False, "entries": [], "truncated": False, "values": "none"}


class RoutedTransport:
    """Answer list calls by ``cursor`` and history calls by ``key``.

    ``list_pages[i]`` answers the request whose cursor is ``None`` (i = 0) or
    ``"c<i>"``. ``history[key]`` is a script: each call takes the next item
    (an Exception is raised, a dict returned) and the last item repeats.
    Keys without a script get ``default_history`` or ``{"key": key,
    "entries": []}``. ``on_history(key)`` runs before a history answer,
    outside the lock, so tests can block or reorder workers.

    The rollback marker call (key ``__system`` with ``values="none"``) is
    answered from its own ``marker`` script (default: no rollback) and counted
    apart: ``history_calls`` and ``total_history_calls`` never include it.
    ``order`` lists every call as ``("list", cursor)`` or
    ``("history", key, values)`` in the order they arrived.

    Every piece of shared state is guarded by one lock.
    """

    def __init__(
        self,
        list_pages: list[dict] | None = None,
        history: dict[str, list[dict | Exception]] | None = None,
        default_history: dict | None = None,
        *,
        on_history: Callable[[str], None] | None = None,
        marker: list[dict | Exception] | None = None,
    ) -> None:
        self.list_pages = list(list_pages or [])
        self.history = {key: list(script) for key, script in (history or {}).items()}
        self.default_history = default_history
        self.on_history = on_history
        self.marker = list(marker or [NO_ROLLBACK])
        self._marker_calls = 0
        self._order: list[tuple] = []
        self._lock = threading.Lock()
        self._calls: list[dict[str, Any]] = []
        self._history_calls: dict[str, int] = {}
        self._completed: list[str] = []
        self._in_flight = 0
        self._max_in_flight = 0

    def __call__(self, method, url, *, headers, body, timeout):
        path = urlsplit(url).path
        payload = json.loads(body.decode("utf-8")) if body else None
        with self._lock:
            self._calls.append(
                {"method": method, "path": path, "headers": headers, "body": payload}
            )
            if path == LIST_PATH:
                self._order.append(("list", payload.get("cursor")))
            elif path == HISTORY_PATH:
                self._order.append(("history", payload.get("key"), payload.get("values")))
        if path == LIST_PATH:
            return self._answer_list(payload)
        if path == HISTORY_PATH:
            return self._answer_history(payload)
        raise AssertionError(f"unexpected route {method} {path}")

    def _answer_list(self, payload):
        cursor = payload.get("cursor")
        index = 0 if cursor is None else int(cursor.removeprefix("c"))
        with self._lock:
            response = self.list_pages[index]
        return _deliver(response)

    def _answer_history(self, payload):
        key = payload["key"]
        if key == MARKER_KEY and payload.get("values") == "none":
            with self._lock:
                response = self.marker[min(self._marker_calls, len(self.marker) - 1)]
                self._marker_calls += 1
            return _deliver(response)
        with self._lock:
            calls = self._history_calls.get(key, 0)
            self._history_calls[key] = calls + 1
            self._in_flight += 1
            self._max_in_flight = max(self._max_in_flight, self._in_flight)
            script = self.history.get(key)
            if script:
                response = script[min(calls, len(script) - 1)]
            elif self.default_history is not None:
                response = self.default_history
            else:
                response = {"key": key, "entries": []}
        try:
            if self.on_history is not None:
                self.on_history(key)
            return _deliver(response)
        finally:
            with self._lock:
                self._in_flight -= 1
                self._completed.append(key)

    # --- recorded state ------------------------------------------------------

    @property
    def calls(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._calls)

    def list_bodies(self) -> list[dict]:
        return [call["body"] for call in self.calls if call["path"] == LIST_PATH]

    def history_bodies(self) -> list[dict]:
        return [call["body"] for call in self.calls if call["path"] == HISTORY_PATH]

    @property
    def order(self) -> list[tuple]:
        with self._lock:
            return list(self._order)

    def marker_calls(self) -> int:
        with self._lock:
            return self._marker_calls

    def history_calls(self, key: str) -> int:
        with self._lock:
            return self._history_calls.get(key, 0)

    def total_history_calls(self) -> int:
        with self._lock:
            return sum(self._history_calls.values())

    @property
    def completed(self) -> list[str]:
        """Keys in the order their history answers finished (raised or returned)."""
        with self._lock:
            return list(self._completed)

    @property
    def max_concurrency(self) -> int:
        with self._lock:
            return self._max_in_flight


def _deliver(response):
    if isinstance(response, BaseException):
        # A fresh copy per raise: worker threads never share one traceback.
        raise copy.copy(response)
    return copy.deepcopy(response)


def make_client(transport, **overrides) -> CloudClient:
    """A ``CloudClient`` with a fake key that talks only to ``transport``."""

    arguments = {"api_key": TEST_API_KEY, "base_url": TEST_BASE_URL, "transport": transport}
    arguments.update(overrides)
    return CloudClient(**arguments)


def list_page(entries: list[dict], next_cursor: str | None = None) -> dict:
    return {"entries": entries, "nextCursor": next_cursor, "total": len(entries)}


# --- error factories (same path as the real transport) ------------------------


def rate_limited(retry_after: Any = None):
    return error_for_response(429, {"error": "rate_limited"}, retry_after=retry_after)


def unavailable(retry_after: Any = None):
    return error_for_response(503, {"error": "runtime_unavailable"}, retry_after=retry_after)


def not_found():
    return error_for_response(404, {"error": "not_found"})


def auth_error():
    return error_for_response(401, {"error": "invalid_api_key"})


def entitlement_error():
    return error_for_response(403, {"error": "not_entitled"})


def payment_required():
    return error_for_response(402, {"error": "payment_required"})


def connection_error():
    return BilincConnectionError(
        "Bilinc Cloud request failed: refused", code="connection_failed", retryable=True
    )


# --- disk snapshots -------------------------------------------------------------


def snapshot(tree: Path) -> dict[str, tuple[bytes, int]]:
    """Every entry under ``tree`` as ``{relative posix path: (bytes, mode bits)}``.

    Files map to their content; folders appear as ``"path/"`` with ``b""``;
    symlinks (never followed) as ``b"-> " + target``. Modes are
    ``stat.S_IMODE`` of ``lstat``. Sorted by path, so two snapshots compare
    byte for byte.
    """

    root = Path(tree)
    result: dict[str, tuple[bytes, int]] = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            full = Path(current) / name
            rel = full.relative_to(root).as_posix()
            info = os.lstat(full)
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                result[rel] = (b"-> " + os.fsencode(os.readlink(full)), mode)
            elif stat.S_ISDIR(info.st_mode):
                result[rel + "/"] = (b"", mode)
            else:
                result[rel] = (full.read_bytes(), mode)
    return dict(sorted(result.items()))
