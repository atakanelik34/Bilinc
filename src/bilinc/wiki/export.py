"""``export_wiki``: list, fetch history, render, then write the folder."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from bilinc import __version__
from bilinc.client import MAX_HISTORY_LIMIT, CloudClient
from bilinc.wiki.fetch import HistoryAbort, fetch_entries, fetch_histories, fetch_marker
from bilinc.wiki.links import find_links
from bilinc.wiki.location import cloud_sync_warning
from bilinc.wiki.manifest import HISTORY_FORMAT, build_manifest
from bilinc.wiki.paths import build_paths
from bilinc.wiki.render import (
    HISTORY_UNAVAILABLE,
    ReusedHistory,
    render_agents,
    render_folder_indexes,
    render_index,
    render_page,
)
from bilinc.wiki.reuse import history_body, history_digest, read_previous_body, reusable_keys
from bilinc.wiki.writer import inspect_target, write_tree

DEFAULT_HISTORY = 5
MARKER_UNREADABLE = "note: history reuse is off for this run (the rollback marker could not be read)"


@dataclass
class ExportResult:
    pages: int = 0
    written: int = 0
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    history_unavailable: list[str] = field(default_factory=list)
    #: Keys whose history was requested in this run, and keys whose block was
    #: taken from the previous export instead.
    history_fetched: int = 0
    history_reused: int = 0
    #: Lines to show the user: the cloud-folder warning, the reuse note.
    warnings: list[str] = field(default_factory=list)


def summary_line(result: ExportResult, target: str | os.PathLike[str]) -> str:
    """The one line the CLI prints on success (the MCP tool returns it too)."""

    return (
        f"Wrote {result.pages} pages to {os.fspath(target)} (removed {len(result.removed)} stale files; "
        f"history: {result.history_fetched} fetched, {result.history_reused} reused)"
    )


def build_files(
    entries: list[dict[str, Any]],
    histories: dict[str, Any] | None,
    *,
    exported_at: str,
    version: str,
    prefix: str | None,
    wikilinks: bool = False,
) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(files, paths)``: relative path → text, and key → page path.

    ``histories`` is None when history is skipped (``--history 0``).
    """

    paths = build_paths(entry["key"] for entry in entries)
    outgoing, incoming = find_links({entry["key"]: entry.get("value") for entry in entries})
    files: dict[str, str] = {}
    for entry in entries:
        key = entry["key"]
        files[paths[key]] = render_page(
            entry,
            path=paths[key],
            paths=paths,
            outgoing=outgoing[key],
            incoming=incoming[key],
            history=None if histories is None else histories.get(key, HISTORY_UNAVAILABLE),
            exported_at=exported_at,
            wikilinks=wikilinks,
        )
    files.update(render_folder_indexes(paths, wikilinks=wikilinks))
    files["index.md"] = render_index(
        entries, paths, exported_at=exported_at, version=version, prefix=prefix, wikilinks=wikilinks
    )
    files["AGENTS.md"] = render_agents(version=version, exported_at=exported_at)
    return files, paths


def export_wiki(
    client: CloudClient,
    target: str | os.PathLike[str],
    *,
    history: int = DEFAULT_HISTORY,
    prefix: str | None = None,
    wikilinks: bool = False,
    refresh_history: bool = False,
    home: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ExportResult:
    """Write every memory under ``prefix`` as Markdown pages in ``target``.

    Nothing on disk changes until every memory (and, when ``history`` > 0,
    each key's last ``history`` changes) has been read. A key's history block
    is taken from the previous export instead of fetched when the key and the
    rollback marker are unchanged (see :mod:`bilinc.wiki.reuse`), unless
    ``refresh_history`` is set. ``sleep`` replaces the retry wait in tests;
    without it, waits can be cut short by Ctrl-C.
    """

    if isinstance(history, bool) or not isinstance(history, int) or not 0 <= history <= MAX_HISTORY_LIMIT:
        raise ValueError(f"history must be between 0 and {MAX_HISTORY_LIMIT}")
    target = Path(target)
    warnings = [line] if (line := cloud_sync_warning(target, home=home)) else []
    previous = inspect_target(target, base_url=client.base_url, prefix=prefix)
    stop = threading.Event() if sleep is None else None
    wait = sleep or time.sleep

    def guarded(call: Callable[[], Any]) -> Any:
        try:
            return call()
        except HistoryAbort as exc:
            raise exc.error from exc

    # The marker is read before the list, so any rollback after this point
    # changes what the next run sees.
    read_marker = history > 0 and not refresh_history
    start = guarded(lambda: fetch_marker(client, sleep=wait, stop=stop)) if read_marker else None
    if read_marker and start is None:
        warnings.append(MARKER_UNREADABLE)

    entries = fetch_entries(client, prefix=prefix)
    histories: dict[str, Any] | None = None
    reused: dict[str, ReusedHistory] = {}
    fetched = 0
    if history > 0:
        candidates = reusable_keys(
            entries,
            previous,
            history=history,
            marker=start,
            refresh=refresh_history,
            version=__version__,
            history_format=HISTORY_FORMAT,
        )
        owned = set(previous["files"]) if previous else set()
        for key in sorted(candidates):
            recorded = previous["keys"][key]
            if recorded["path"] not in owned:
                continue
            body = read_previous_body(target, recorded["path"])
            if body is not None and history_digest(body) == recorded["history_sha256"]:
                reused[key] = ReusedHistory(body)
        missing = [entry["key"] for entry in entries if entry["key"] not in reused]
        histories = guarded(
            lambda: fetch_histories(client, missing, limit=history, sleep=wait, progress=progress, stop=stop)
        )
        fetched = len(missing)
        if reused:
            end = guarded(lambda: fetch_marker(client, sleep=wait, stop=stop))
            if end != start:
                # A rollback ran during this export: none of the reused blocks can be trusted.
                again = sorted(reused)
                histories.update(
                    guarded(lambda: fetch_histories(client, again, limit=history, sleep=wait, stop=stop))
                )
                fetched += len(again)
                reused = {}
        histories.update(reused)

    moment = (clock or (lambda: datetime.now(timezone.utc)))()
    exported_at = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files, paths = build_files(
        entries, histories, exported_at=exported_at, version=__version__, prefix=prefix, wikilinks=wikilinks
    )
    keys = {}
    for entry in entries:
        key = entry["key"]
        record = {"path": paths[key], "entry_version": entry.get("entryVersion"), "updated_at": entry.get("updatedAt")}
        if histories is not None and histories.get(key, HISTORY_UNAVAILABLE) is not HISTORY_UNAVAILABLE:
            body = history_body(files[paths[key]])
            if body is not None:
                record["history_sha256"] = history_digest(body)
        keys[key] = record

    def manifest_for(complete: bool, listed: list[str]) -> dict[str, Any]:
        return build_manifest(
            version=__version__,
            base_url=client.base_url,
            prefix=prefix,
            history=history,
            exported_at=exported_at,
            complete=complete,
            files=listed,
            keys=keys,
            history_marker=start,
        )

    written = write_tree(target, files, previous=previous, manifest_for=manifest_for)
    unavailable = sorted(key for key, value in (histories or {}).items() if value is HISTORY_UNAVAILABLE)
    return ExportResult(
        pages=len(entries),
        written=written.written,
        removed=written.removed,
        skipped=written.skipped,
        history_unavailable=unavailable,
        history_fetched=fetched,
        history_reused=len(reused),
        warnings=warnings,
    )
