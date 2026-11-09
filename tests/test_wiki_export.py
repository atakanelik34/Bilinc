"""export_wiki end to end over a fake transport: fields, refusals, failures, determinism."""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.wiki_fakes import (
    RoutedTransport,
    auth_error,
    list_page,
    make_client,
    not_found,
    snapshot,
)

from bilinc.client import error_for_response
from bilinc.wiki.export import ExportResult, export_wiki
from bilinc.wiki.manifest import MANIFEST_NAME
from bilinc.wiki.reuse import history_body, history_digest
from bilinc.wiki.writer import WikiRefused

ROOT = Path(__file__).resolve().parents[1]
FIRST = datetime(2026, 11, 9, 1, 0, 0, tzinfo=timezone.utc)
SECOND = FIRST + timedelta(hours=3)


def public_entry(key, value, *, minute=0, memory_type="semantic", source="claude-code"):
    """One entry in the exact shape the public list route returns (``publicList``)."""
    return {
        "key": key,
        "memoryType": memory_type,
        "importance": 0.5,
        "source": source,
        "createdAt": "2026-11-01T00:00:00.000Z",
        "updatedAt": f"2026-11-08T12:{minute:02d}:00.000Z",
        "entryVersion": f"v-{key}",
        "value": value,
    }


ENTRIES = [
    public_entry("project:bilinc:release", "2.6.3 shipped; see project:bilinc:plan.", minute=5),
    public_entry("project:bilinc:plan", {"next": "wiki", "owner": "team"}, minute=3),
    public_entry("solo", "standalone", minute=1, source=None),
    public_entry("index", "a key named like a reserved page", minute=2),
]


def history_payload(key):
    return {
        "key": key,
        "exists": True,
        "entries": [
            {"op": "update", "at": "2026-11-08T12:05:00.000Z", "reason": "release", "source": "claude-code",
             "before": "draft", "after": "2.6.3 shipped"},
        ],
        "truncated": False,
        "values": "full",
    }


def transport_for(entries=ENTRIES, history=None, pages=1, **kwargs):
    entries = list(entries)
    size = -(-len(entries) // pages)
    chunks = [entries[i : i + size] for i in range(0, len(entries), size)]
    list_pages = [
        list_page(chunk, f"c{index + 1}" if index + 1 < len(chunks) else None) for index, chunk in enumerate(chunks)
    ]
    script = {entry["key"]: [history_payload(entry["key"])] for entry in entries}
    script.update(history or {})
    return RoutedTransport(list_pages, script, **kwargs)


def run(target, transport, *, clock=FIRST, **kwargs) -> ExportResult:
    client = make_client(transport, read_retry_attempts=1)
    return export_wiki(client, target, clock=lambda: clock, sleep=lambda seconds: None, **kwargs)


def normalised(tree: Path) -> dict:
    out = {}
    for rel, (content, mode) in snapshot(tree).items():
        if content:
            content = content.replace(b"2026-11-09T04:00:00Z", b"2026-11-09T01:00:00Z")
        out[rel] = (content, mode)
    return out


def frontmatter(page: str) -> dict:
    lines = page.split("---\n")[1].splitlines()
    return {name: json.loads(value) for name, value in (line.split(": ", 1) for line in lines)}


def test_list_fields_from_the_public_route_shape(tmp_path):
    result = run(tmp_path, transport_for())

    assert result.pages == 4
    page = (tmp_path / "project" / "bilinc" / "release.md").read_text(encoding="utf-8")
    assert frontmatter(page) == {
        "key": "project:bilinc:release",
        "memory_type": "semantic",
        "source": "claude-code",
        "updated_at": "2026-11-08T12:05:00.000Z",
        "exported_at": "2026-11-09T01:00:00Z",
    }
    assert frontmatter((tmp_path / "solo.md").read_text(encoding="utf-8"))["source"] is None
    manifest = json.loads((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))
    page_text = (tmp_path / "project" / "bilinc" / "release.md").read_text(encoding="utf-8")
    assert manifest["keys"]["project:bilinc:release"] == {
        "path": "project/bilinc/release.md",
        "entry_version": "v-project:bilinc:release",
        "updated_at": "2026-11-08T12:05:00.000Z",
        "history_sha256": history_digest(history_body(page_text)),
    }
    assert manifest["history"] == 5 and manifest["prefix"] is None
    assert manifest["base_url"] == "https://bilinc.space"


def test_pages_link_to_each_other_and_the_index(tmp_path):
    run(tmp_path, transport_for())

    release = (tmp_path / "project" / "bilinc" / "release.md").read_text(encoding="utf-8")
    plan = (tmp_path / "project" / "bilinc" / "plan.md").read_text(encoding="utf-8")
    assert "[project:bilinc:plan](plan.md)" in release
    assert "Mentioned by" in plan and "[project:bilinc:release](release.md)" in plan
    index = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "project/bilinc/release.md" in index
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / "project" / "_index.md").is_file()
    assert (tmp_path / "project" / "bilinc" / "_index.md").is_file()
    reserved = [name for name in os.listdir(tmp_path) if name.startswith("index~")]
    assert len(reserved) == 1


def test_refusal_touches_nothing_and_calls_nothing(tmp_path):
    (tmp_path / "notes.md").write_text("mine")
    transport = transport_for()

    with pytest.raises(WikiRefused):
        run(tmp_path, transport)

    assert transport.calls == []
    assert sorted(os.listdir(tmp_path)) == ["notes.md"]


def test_list_failure_leaves_the_previous_wiki_identical(tmp_path):
    run(tmp_path, transport_for())
    before = snapshot(tmp_path)
    broken = transport_for(pages=2)
    broken.list_pages[1] = error_for_response(500, {"error": "internal", "retryable": False})

    with pytest.raises(Exception, match="internal"):
        run(tmp_path, broken, clock=SECOND)

    assert snapshot(tmp_path) == before


def test_history_auth_error_leaves_the_previous_wiki_identical(tmp_path):
    run(tmp_path, transport_for())
    before = snapshot(tmp_path)

    with pytest.raises(Exception, match="(?i)auth|key|invalid"):
        run(tmp_path, transport_for(history={"solo": [auth_error()]}), clock=SECOND, refresh_history=True)

    assert snapshot(tmp_path) == before


def test_history_auth_error_on_a_first_run_writes_nothing(tmp_path):
    target = tmp_path / "wiki"

    with pytest.raises(Exception):
        run(target, transport_for(history={"solo": [auth_error()]}))

    assert not target.exists()


def test_history_zero_skips_calls_and_the_section(tmp_path):
    transport = transport_for()

    run(tmp_path, transport, history=0)

    assert transport.total_history_calls() == 0
    assert "## History" not in (tmp_path / "solo.md").read_text(encoding="utf-8")
    assert json.loads((tmp_path / MANIFEST_NAME).read_text())["history"] == 0


def test_history_limit_is_sent(tmp_path):
    transport = transport_for()

    run(tmp_path, transport, history=7)

    per_key = [body for body in transport.history_bodies() if body["key"] != "__system"]
    assert {body["limit"] for body in per_key} == {7}
    assert {body["values"] for body in per_key} == {"full"}


@pytest.mark.parametrize("bad", [-1, 101])
def test_history_count_is_bounded(tmp_path, bad):
    with pytest.raises(ValueError):
        run(tmp_path, transport_for(), history=bad)


def test_unavailable_history_is_listed_and_written(tmp_path):
    result = run(tmp_path, transport_for(history={"solo": [not_found()]}))

    assert result.history_unavailable == ["solo"]
    assert "History unavailable." in (tmp_path / "solo.md").read_text(encoding="utf-8")


def test_prefix_is_forwarded_and_recorded(tmp_path):
    transport = transport_for()

    run(tmp_path, transport, prefix="project:")

    assert {body.get("prefix") for body in transport.list_bodies()} == {"project:"}
    assert json.loads((tmp_path / MANIFEST_NAME).read_text())["prefix"] == "project:"


def test_user_files_survive_reruns(tmp_path):
    run(tmp_path, transport_for())
    (tmp_path / "notes.md").write_text("mine")
    (tmp_path / "project" / "mine.md").write_text("mine too")

    result = run(tmp_path, transport_for(ENTRIES[2:]), clock=SECOND)

    assert (tmp_path / "notes.md").read_text() == "mine"
    assert (tmp_path / "project" / "mine.md").read_text() == "mine too"
    assert not (tmp_path / "project" / "bilinc").exists()
    assert "project/bilinc/release.md" in result.removed


def test_determinism_in_process(tmp_path):
    run(tmp_path / "one", transport_for())
    shuffled = list(ENTRIES)
    random.Random(7).shuffle(shuffled)

    run(tmp_path / "two", transport_for(shuffled, pages=2), clock=SECOND)

    assert normalised(tmp_path / "one") == normalised(tmp_path / "two")


DETERMINISM_SCRIPT = r"""
import random, sys, time
from datetime import datetime, timedelta, timezone
sys.path.insert(0, sys.argv[2])
import tests.test_wiki_export as t
seed = int(sys.argv[3])
entries = list(t.ENTRIES) + [t.public_entry(f"bulk:item{i:02d}", {"n": i, "see": "solo"}, minute=i) for i in range(12)]
entries += [t.public_entry("Team:x", "upper"), t.public_entry("team:y", "lower")]
random.Random(seed).shuffle(entries)
order = {e["key"]: i for i, e in enumerate(entries)}
delay = (lambda key: time.sleep(0.002 * order[key])) if seed % 2 else (lambda key: time.sleep(0.002 * (len(order) - order[key])))
clock = t.FIRST if seed % 2 else t.SECOND
transport = t.transport_for(entries, pages=3, on_history=delay)
t.run(sys.argv[1], transport, clock=clock)
"""


def test_determinism_across_processes(tmp_path):
    outputs = []
    for seed, tz in ((1, "UTC"), (2, "Asia/Tokyo")):
        out = tmp_path / f"run{seed}"
        env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("BILINC_")},
            "PYTHONHASHSEED": str(seed),
            "TZ": tz,
            "PYTHONPATH": str(ROOT / "src"),
        }
        completed = subprocess.run(
            [sys.executable, "-c", DETERMINISM_SCRIPT, str(out), str(ROOT), str(seed)],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append(normalised(out))

    assert outputs[0] == outputs[1]
    assert len(outputs[0]) > 20
