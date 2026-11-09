"""Fetch the memories and their histories for a wiki export.

History requests run on a small thread pool through a copy of the client with
``read_retry_attempts=1``, so this module is the only retry layer: no SDK
retries are stacked under it and no real ``time.sleep`` runs outside the
injected wait. Results are keyed by memory key, so the order in which
requests finish never reaches the output.
"""

from __future__ import annotations

import dataclasses
import hashlib
import http.client
import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from bilinc.client import (
    BilincApiKeyRequired,
    BilincAuthError,
    BilincCloudError,
    BilincEntitlementError,
    BilincPaymentRequiredError,
    CloudClient,
)
from bilinc.wiki.render import HISTORY_UNAVAILABLE

#: Errors that stop the whole run: retrying or skipping cannot help.
FATAL_ERRORS = (
    BilincAuthError,
    BilincEntitlementError,
    BilincPaymentRequiredError,
    BilincApiKeyRequired,
)
#: Retries per key after the first request, so at most 4 requests per key.
MAX_RETRIES = 3
#: Longest wait honoured from a ``Retry-After`` the service sent.
RETRY_AFTER_CAP = 60.0
#: Waits before retries 1, 2 and 3 when the error carried no ``Retry-After``.
BACKOFF = (1.0, 2.0, 4.0)
#: Failures the SDK's default transport lets through unwrapped (a timeout or a
#: dropped connection while reading the response). Retried like a connection error.
RAW_NETWORK_ERRORS = (OSError, http.client.HTTPException)
#: Most history requests in flight at once.
MAX_WORKERS = 4
#: The key every rollback writes a history entry under; its newest entry is the
#: run marker that tells history reuse a rollback happened (see ``reuse.py``).
MARKER_KEY = "__system"


class HistoryAbort(Exception):
    """A fatal error (auth, entitlement, payment, no key) stopped the history phase."""

    def __init__(self, error: BaseException) -> None:
        super().__init__(str(error))
        self.error = error


class HistoryCancelled(Exception):
    """The ``stop`` event was set while history was being fetched."""


def fetch_entries(client: CloudClient, *, prefix: str | None) -> list[dict]:
    """Every memory (full values) under ``prefix``, sorted by key.

    A duplicate or missing key means the list walk is inconsistent, so it is
    refused rather than written as a half-right wiki.
    """

    by_key: dict[str, dict] = {}
    for entry in client.iter_memories(prefix=prefix, values="full"):
        key = entry.get("key") if isinstance(entry, dict) else None
        if not isinstance(key, str):
            raise BilincCloudError(
                "Bilinc Cloud returned a memory without a key",
                code="invalid_response",
            )
        if key in by_key:
            raise BilincCloudError(
                f"Bilinc Cloud returned the memory {key!r} twice",
                code="invalid_response",
            )
        by_key[key] = entry
    return [by_key[key] for key in sorted(by_key)]


def fetch_histories(
    client: CloudClient,
    keys: list[str],
    *,
    limit: int,
    sleep: Callable[[float], None],
    max_workers: int = MAX_WORKERS,
    progress: Callable[[int, int], None] | None = None,
    stop: threading.Event | None = None,
) -> dict[str, Any]:
    """Return ``{key: history payload or HISTORY_UNAVAILABLE}`` in ``keys`` order.

    Per key, a retryable error is retried up to ``MAX_RETRIES`` times, waiting
    the error's ``retry_after`` (capped at ``RETRY_AFTER_CAP``) or else
    ``BACKOFF``; any other error, or retries running out, marks the key
    unavailable. A fatal error raises :class:`HistoryAbort` and cancels the
    pending work. Waits use ``stop.wait(delay)`` when ``stop`` is given (so
    setting it wakes them), else ``sleep(delay)``; a set ``stop`` raises
    :class:`HistoryCancelled`. When the run aborts, ``stop`` is set so
    workers still waiting wake up at once.
    """

    keys = list(keys)
    total = len(keys)
    if not total:
        return {}
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")
    history_client = dataclasses.replace(client, read_retry_attempts=1)
    halt = threading.Event()
    fatal: list[HistoryAbort] = []

    def stopped() -> bool:
        return halt.is_set() or (stop is not None and stop.is_set())

    def wait(delay: float) -> None:
        if stop is not None:
            if stop.wait(delay):
                raise HistoryCancelled()
        else:
            sleep(delay)
        if stopped():
            raise HistoryCancelled()

    def fetch_one(key: str) -> Any:
        try:
            return _with_retries(lambda: history_client.history(key, limit=limit, values="full"), wait, stopped)
        except HistoryAbort as abort:
            fatal.append(abort)
            halt.set()
            raise

    results: dict[str, Any] = {}
    executor = ThreadPoolExecutor(
        max_workers=min(max_workers, MAX_WORKERS),
        thread_name_prefix="bilinc-wiki-history",
    )
    try:
        futures = {executor.submit(fetch_one, key): key for key in keys}
        for done, future in enumerate(as_completed(futures), start=1):
            try:
                results[futures[future]] = future.result()
            except HistoryCancelled:
                # A cancellation caused by another key's fatal error reports that error.
                if fatal:
                    raise fatal[0] from fatal[0].error
                raise
            if progress is not None:
                progress(done, total)
        if stop is not None and stop.is_set():
            raise HistoryCancelled()
    except BaseException:
        halt.set()
        if stop is not None:
            stop.set()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    executor.shutdown(wait=True)
    return {key: results[key] for key in keys}


def _with_retries(call: Callable[[], Any], wait: Callable[[float], None], stopped: Callable[[], bool]) -> Any:
    """Run one read with the wiki's retry rules.

    Returns the payload when it is a dict, else :data:`HISTORY_UNAVAILABLE`
    (a non-retryable error, or retries running out). A fatal error raises
    :class:`HistoryAbort`; a set stop raises :class:`HistoryCancelled`.
    """

    for attempt in range(MAX_RETRIES + 1):
        if stopped():
            raise HistoryCancelled()
        try:
            result = call()
        except FATAL_ERRORS as exc:
            raise HistoryAbort(exc) from exc
        except BilincCloudError as exc:
            if not exc.retryable or attempt == MAX_RETRIES:
                return HISTORY_UNAVAILABLE
            if exc.retry_after is not None:
                delay = min(exc.retry_after, RETRY_AFTER_CAP)
            else:
                delay = BACKOFF[attempt]
            wait(delay)
        except RAW_NETWORK_ERRORS:
            if attempt == MAX_RETRIES:
                return HISTORY_UNAVAILABLE
            wait(BACKOFF[attempt])
        else:
            return result if isinstance(result, dict) else HISTORY_UNAVAILABLE
    raise AssertionError("unreachable")  # pragma: no cover


def fetch_marker(
    client: CloudClient,
    *,
    sleep: Callable[[float], None],
    stop: threading.Event | None = None,
) -> str | None:
    """sha256 of the newest ``__system`` history entry, or None when it cannot be read.

    Every rollback writes an entry there, so a changed marker means a key may
    have been restored to an earlier version with new history. The answer's
    ``exists`` is ignored: the service reports it false for ``__system`` while
    still returning entries. Fatal errors raise :class:`HistoryAbort`.
    """

    marker_client = dataclasses.replace(client, read_retry_attempts=1)

    def wait(delay: float) -> None:
        if stop is not None:
            if stop.wait(delay):
                raise HistoryCancelled()
        else:
            sleep(delay)

    result = _with_retries(
        lambda: marker_client.history(MARKER_KEY, limit=1, values="none"),
        wait,
        lambda: stop is not None and stop.is_set(),
    )
    if not isinstance(result, dict) or not isinstance(result.get("entries"), list):
        return None
    canonical = json.dumps(
        {"entries": result["entries"], "truncated": result.get("truncated")},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8", errors="replace")).hexdigest()
