#!/usr/bin/env python3
"""Local smoke for ``bilinc wiki``: two runs against a fake Bilinc Cloud.

No network and no API key: a scripted transport answers the SDK's list and
history routes. It checks that two runs are byte-identical apart from
``exported_at``, that a file the user added survives, that a non-empty folder
without the marker is refused, and that folders are 0700 and files 0600.

Usage: python scripts/wiki_smoke.py   (exit 1 if any check fails)
"""

from __future__ import annotations

import json
import os
import secrets
import stat
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import bilinc
from bilinc.client import CloudClient, error_for_response
from bilinc.wiki import WikiRefused, export_wiki

# A throwaway key per run, as in verify_cloud_lifecycle_smoke.py; the fake transport never checks it.
API_KEY = f"bil_live_{secrets.token_hex(8)}"

FIRST = datetime(2026, 11, 9, 1, 0, 0, tzinfo=timezone.utc)
SECOND = datetime(2026, 11, 9, 2, 30, 0, tzinfo=timezone.utc)
FAILING_KEY = "ops:flaky-history"


def entry(key, value, minute):
    return {
        "key": key,
        "memoryType": "semantic",
        "importance": 0.5,
        "source": "smoke",
        "createdAt": "2026-11-01T00:00:00.000Z",
        "updatedAt": f"2026-11-08T12:{minute:02d}:00.000Z",
        "entryVersion": f"v-{minute}",
        "value": value,
    }


def synthetic_entries():
    values = [
        ("project:bilinc:release", "2.6.3 shipped; next is project:bilinc:plan."),
        ("project:bilinc:plan", {"next": "wiki export", "owner": "team", "steps": [1, 2, 3]}),
        ("project:bilinc:notes:deep:er", "nested four levels"),
        ("Team:x", "upper-case folder"),
        ("team:y", "lower-case folder, collides with Team on macOS"),
        ("Note", "case collision A"),
        ("note", "case collision B"),
        ("index", "a key named like the catalog"),
        ("a:_index", "a key named like a folder index"),
        ("b:AGENTS", "a key named like AGENTS.md"),
        (".env", "a leading dot"),
        ("a/b\\c?d", "characters a file system rejects"),
        ("trailing. ", "trailing dot and space"),
        ("CON", "a Windows device name"),
        ("empty::segment", "an empty segment"),
        ("ş" * 80, "a long multi-byte key"),
        ("fence", "a value with ``````` seven backticks\n# not a heading"),
        ("hostile\n# Injected", "[link](javascript:alert(1))\n---\n| table |"),
        ("json:array", [1, "two", {"three": 3}]),
        ("json:null", None),
        ("json:number", 42),
        ("json:bool", True),
        ("json:object", {"a": "x" * 200, "b": {"c": ["d"]}}),
        ("ops:deploy-day", "thursday; see ops:on-call."),
        ("ops:on-call", "the team rotates weekly"),
        (FAILING_KEY, "its history call always fails"),
        ("solo", "a root page mentioned by nobody"),
        ("unicode:çağrı", "Turkish characters"),
        ("unicode:café", "NFD e-acute"),
        ("unicode:café", "NFC e-acute, collides with the NFD one"),
    ]
    return [entry(key, value, minute) for minute, (key, value) in enumerate(values)]


class FakeCloud:
    """Answers list (two pages) and history; FAILING_KEY's history is always 503."""

    def __init__(self, entries):
        self.entries = sorted(entries, key=lambda item: item["key"])
        self.lock = threading.Lock()
        self.history_calls = 0

    def __call__(self, method, url, *, headers, body, timeout):
        path = urlsplit(url).path
        payload = json.loads(body.decode("utf-8"))
        if path == "/api/cloud/memory/list":
            half = len(self.entries) // 2
            if payload.get("cursor") is None:
                return {"entries": self.entries[:half], "nextCursor": "c1", "total": len(self.entries)}
            return {"entries": self.entries[half:], "nextCursor": None, "total": len(self.entries)}
        if path == "/api/cloud/memory/history":
            with self.lock:
                self.history_calls += 1
            key = payload["key"]
            if key == FAILING_KEY:
                raise error_for_response(503, {"error": "cloud_runtime_unavailable"})
            return {
                "key": key,
                "exists": True,
                "entries": [
                    {"op": "update", "at": "2026-11-08T12:00:00.000Z", "reason": "smoke", "source": "smoke",
                     "before": "old", "after": "new"},
                    {"op": "commit", "at": "2026-11-01T00:00:00.000Z", "source": "smoke", "after": "old"},
                ],
                "truncated": False,
                "values": "full",
            }
        raise AssertionError(f"unexpected route {path}")


def run(target: Path, clock: datetime):
    client = CloudClient(api_key=API_KEY, transport=FakeCloud(synthetic_entries()))
    return export_wiki(client, target, clock=lambda: clock, sleep=lambda seconds: None)


def tree(root: Path, skip=()):
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if rel in skip:
                continue
            mode = stat.S_IMODE(path.lstat().st_mode)
            out[rel] = (path.read_bytes() if path.is_file() else None, mode)
    return out


def normalised(snapshot, stamp: str, into: str):
    return {
        rel: (content.replace(stamp.encode(), into.encode()) if content else content, mode)
        for rel, (content, mode) in snapshot.items()
    }


def main() -> int:
    print(f"bilinc {bilinc.__version__} from {bilinc.__file__}")
    checks = {}
    with tempfile.TemporaryDirectory(prefix="bilinc-wiki-smoke-") as scratch:
        target = Path(scratch) / "wiki"
        first = run(target, FIRST)
        first_tree = tree(target)
        (target / "notes.md").write_text("the user's own note\n", encoding="utf-8")
        second = run(target, SECOND)
        second_tree = tree(target, skip={"notes.md"})

        print(f"pages: {first.pages}, files written: {first.written}, removed on rerun: {len(second.removed)}")
        print(f"history unavailable: {first.history_unavailable}")
        checks["history_failure_reported"] = first.history_unavailable == [FAILING_KEY]
        checks["identical_except_exported_at"] = normalised(
            second_tree, "2026-11-09T02:30:00Z", "2026-11-09T01:00:00Z"
        ) == first_tree
        checks["user_file_survived"] = (target / "notes.md").read_text(encoding="utf-8") == "the user's own note\n"
        checks["modes_ok"] = all(
            mode == (0o600 if content is not None else 0o700) for content, mode in second_tree.values()
        ) and stat.S_IMODE(target.stat().st_mode) == 0o700

        foreign = Path(scratch) / "foreign"
        foreign.mkdir()
        (foreign / "mine.md").write_text("not a wiki", encoding="utf-8")
        try:
            run(foreign, FIRST)
            checks["refused_without_marker"] = False
        except WikiRefused as exc:
            checks["refused_without_marker"] = sorted(os.listdir(foreign)) == ["mine.md"]
            print(f"refusal: {exc}")

        names = sorted(path.relative_to(target).as_posix() for path in target.rglob("*.md"))
        print(f"sample paths: {[name for name in names if '~' in name or '%' in name][:8]}")

    for name, ok in checks.items():
        print(f"{name}: {ok}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
