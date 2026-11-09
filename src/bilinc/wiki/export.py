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
from bilinc.wiki.fetch import HistoryAbort, fetch_entries, fetch_histories
from bilinc.wiki.links import find_links
from bilinc.wiki.manifest import build_manifest
from bilinc.wiki.paths import build_paths
from bilinc.wiki.render import (
    HISTORY_UNAVAILABLE,
    render_agents,
    render_folder_indexes,
    render_index,
    render_page,
)
from bilinc.wiki.writer import inspect_target, write_tree

DEFAULT_HISTORY = 5


@dataclass
class ExportResult:
    pages: int = 0
    written: int = 0
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    history_unavailable: list[str] = field(default_factory=list)


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
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ExportResult:
    """Write every memory under ``prefix`` as Markdown pages in ``target``.

    Nothing on disk changes until every memory (and, when ``history`` > 0,
    each key's last ``history`` changes) has been read. ``sleep`` replaces the
    retry wait in tests; without it, waits can be cut short by Ctrl-C.
    """

    if isinstance(history, bool) or not isinstance(history, int) or not 0 <= history <= MAX_HISTORY_LIMIT:
        raise ValueError(f"history must be between 0 and {MAX_HISTORY_LIMIT}")
    target = Path(target)
    previous = inspect_target(target, base_url=client.base_url, prefix=prefix)

    entries = fetch_entries(client, prefix=prefix)
    histories: dict[str, Any] | None = None
    if history > 0:
        stop = threading.Event() if sleep is None else None
        try:
            histories = fetch_histories(
                client,
                [entry["key"] for entry in entries],
                limit=history,
                sleep=sleep or time.sleep,
                progress=progress,
                stop=stop,
            )
        except HistoryAbort as exc:
            raise exc.error from exc

    moment = (clock or (lambda: datetime.now(timezone.utc)))()
    exported_at = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files, paths = build_files(entries, histories, exported_at=exported_at, version=__version__, prefix=prefix)
    keys = {
        entry["key"]: {
            "path": paths[entry["key"]],
            "entry_version": entry.get("entryVersion"),
            "updated_at": entry.get("updatedAt"),
        }
        for entry in entries
    }

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
        )

    written = write_tree(target, files, previous=previous, manifest_for=manifest_for)
    unavailable = sorted(key for key, value in (histories or {}).items() if value is HISTORY_UNAVAILABLE)
    return ExportResult(
        pages=len(entries),
        written=written.written,
        removed=written.removed,
        skipped=written.skipped,
        history_unavailable=unavailable,
    )
