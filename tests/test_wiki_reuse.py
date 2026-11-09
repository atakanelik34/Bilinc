"""Tests for reading back and reusing history blocks (``bilinc.wiki.reuse``)."""

from __future__ import annotations

import copy
import hashlib
import os
import threading

import pytest

from bilinc.wiki.render import HISTORY_UNAVAILABLE, history_section, render_page
from bilinc.wiki.reuse import (
    PAGE_READ_LIMIT,
    history_body,
    history_digest,
    read_previous_body,
    reusable_keys,
)


def page(value, history, links=()):
    """One page in our own format, built by the real renderer."""
    paths = {"k": "k.md", **{other: f"{other}.md" for other in links}}
    return render_page(
        {"key": "k", "value": value},
        path="k.md",
        paths=paths,
        outgoing=list(links),
        incoming=[],
        history=history,
        exported_at="2026-11-09T01:00:00Z",
    )


HIST = {
    "entries": [{"op": "update", "at": 1762600000.0, "reason": "## Links\n```", "after": "x"}],
    "truncated": False,
}
BODY = history_section(HIST).rstrip("\n")

# --- history_body ---------------------------------------------------------------


def test_body_is_the_rendered_section_without_trailing_newlines() -> None:
    assert history_body(page("v", HIST)) == BODY


def test_body_is_the_same_with_or_without_a_links_section() -> None:
    with_links = page("v", HIST, links=["other"])
    assert "\n## Links\n" in with_links
    assert history_body(with_links) == history_body(page("v", HIST)) == BODY


def test_headings_inside_value_fences_are_ignored() -> None:
    tricky = "x\n## History\n\nfake\n## Links\n" + "`" * 7
    assert history_body(page(tricky, HIST)) == BODY
    assert history_body(page(tricky, HIST, links=["other"])) == BODY


def test_headings_inside_object_value_fences_are_ignored() -> None:
    tricky = {"## History": "\n## Links\n```\n", "n": "`" * 7 + "\n## History\n\nfake"}
    assert history_body(page(tricky, HIST, links=["other"])) == BODY


@pytest.mark.parametrize(
    "history, expected",
    [
        ({"entries": [], "truncated": False}, "No recorded changes."),
        (HISTORY_UNAVAILABLE, "History unavailable."),
    ],
)
def test_body_of_plain_sections(history, expected) -> None:
    assert history_body(page("v", history)) == expected


def test_truncated_history_keeps_its_last_line() -> None:
    hist = {**HIST, "truncated": True}
    assert history_body(page("v", hist)).endswith("Older changes not shown.")


def test_no_history_section_gives_none() -> None:
    assert history_body(page("v", None)) is None
    assert history_body(page("x\n## History\n\nfake", None, links=["other"])) is None


def test_body_matches_what_a_reused_block_renders_back() -> None:
    body = history_body(page("v", HIST))
    assert page("v", HIST).endswith("## History\n\n" + body + "\n")


# --- history_digest ---------------------------------------------------------------


def test_digest_hashes_bytes_as_written() -> None:
    assert history_digest("a\ud800b") == hashlib.sha256("a?b".encode()).hexdigest()
    assert history_digest(BODY) == hashlib.sha256(BODY.encode("utf-8")).hexdigest()


# --- read_previous_body -------------------------------------------------------------


def test_read_previous_body_refuses_symlink_folder_and_big_files(tmp_path) -> None:
    (tmp_path / "k.md").write_text(page("v", HIST), encoding="utf-8")
    assert read_previous_body(tmp_path, "k.md") == BODY
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "p.md").write_text(page("v", HIST), encoding="utf-8")
    assert read_previous_body(tmp_path, "real/p.md") == BODY
    (tmp_path / "link").symlink_to(tmp_path / "real")
    assert read_previous_body(tmp_path, "link/p.md") is None
    (tmp_path / "s.md").symlink_to(tmp_path / "k.md")
    assert read_previous_body(tmp_path, "s.md") is None
    (tmp_path / "big.md").write_bytes(b"x" * (PAGE_READ_LIMIT + 1))
    assert read_previous_body(tmp_path, "big.md") is None
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe")
    assert read_previous_body(tmp_path, "bad.md") is None
    assert read_previous_body(tmp_path, "missing.md") is None
    assert read_previous_body(tmp_path, "../k.md") is None
    (tmp_path / "dir.md").mkdir()
    assert read_previous_body(tmp_path, "dir.md") is None
    (tmp_path / "file").write_text("x", encoding="utf-8")
    assert read_previous_body(tmp_path, "file/p.md") is None


def test_read_previous_body_without_history_section(tmp_path) -> None:
    (tmp_path / "k.md").write_text(page("v", None), encoding="utf-8")
    assert read_previous_body(tmp_path, "k.md") is None


# --- reusable_keys -----------------------------------------------------------------

MARKER = "m" * 64
DIGEST = "a" * 64
ENTRY = {"key": "k", "entryVersion": "v1", "updatedAt": "t1"}
PREVIOUS = {
    "complete": True,
    "tool_version": "2.7.0",
    "history_format": 1,
    "history": 5,
    "history_marker": MARKER,
    "files": ["k.md"],
    "keys": {"k": {"path": "k.md", "entry_version": "v1", "updated_at": "t1", "history_sha256": DIGEST}},
}
CALL = {"history": 5, "marker": MARKER, "refresh": False, "version": "2.7.0", "history_format": 1}


def reuse(entries=None, previous=PREVIOUS, **changes):
    return reusable_keys([ENTRY] if entries is None else entries, previous, **{**CALL, **changes})


def mutated(path, value):
    """A copy of ``PREVIOUS`` with one field set (``_DROP`` removes it)."""
    previous = copy.deepcopy(PREVIOUS)
    target = previous
    for part in path[:-1]:
        target = target[part]
    if value is _DROP:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return previous


_DROP = object()


def test_unchanged_key_is_reusable() -> None:
    assert reuse() == {"k"}


def test_only_matching_keys_are_reusable() -> None:
    entries = [ENTRY, {"key": "new", "entryVersion": "v1", "updatedAt": "t1"}]
    assert reuse(entries) == {"k"}


@pytest.mark.parametrize(
    "changes",
    [
        {"refresh": True},
        {"history": 0},
        {"history": 6},
        {"previous": None},
        {"marker": None},
        {"marker": "n" * 64},
        {"version": "2.7.1"},
        {"history_format": 2},
    ],
    ids=["refresh", "history-0", "history-differs", "no-previous", "marker-none",
         "marker-differs", "version-differs", "format-differs"],
)
def test_call_off_rules(changes) -> None:
    assert reuse(**changes) == set()


@pytest.mark.parametrize(
    "path, value",
    [
        (("complete",), False),
        (("complete",), _DROP),
        (("complete",), 1),
        (("tool_version",), "2.6.3"),
        (("tool_version",), _DROP),
        (("history_format",), 2),
        (("history_format",), _DROP),
        (("history_format",), None),
        (("history",), 6),
        (("history",), _DROP),
        (("history_marker",), None),
        (("history_marker",), _DROP),
        (("history_marker",), "n" * 64),
        (("keys", "k", "entry_version"), "v2"),
        (("keys", "k", "updated_at"), "t2"),
        (("keys", "k", "entry_version"), _DROP),
        (("keys", "k", "updated_at"), _DROP),
        (("keys", "k", "entry_version"), 1),
        (("keys", "k", "updated_at"), None),
        (("keys", "k", "history_sha256"), _DROP),
        (("keys", "k", "history_sha256"), None),
        (("keys", "k", "history_sha256"), "a" * 63),
        (("keys", "k", "history_sha256"), "a" * 65),
        (("keys", "k", "history_sha256"), "A" * 64),
        (("keys", "k", "history_sha256"), "g" * 64),
        (("keys", "k", "history_sha256"), "a" * 64 + "\n"),
        (("keys", "k"), _DROP),
        (("keys", "k"), "k.md"),
        (("keys",), _DROP),
    ],
)
def test_manifest_off_rules(path, value) -> None:
    assert reuse(previous=mutated(path, value)) == set()


@pytest.mark.parametrize(
    "entry",
    [
        {**ENTRY, "entryVersion": "v2"},
        {**ENTRY, "updatedAt": "t2"},
        {"key": "k", "updatedAt": "t1"},
        {"key": "k", "entryVersion": "v1"},
        {**ENTRY, "entryVersion": None},
        {**ENTRY, "updatedAt": 1},
        {**ENTRY, "entryVersion": ""},
        {**ENTRY, "updatedAt": ""},
    ],
)
def test_entry_off_rules(entry) -> None:
    assert reuse([entry]) == set()


def test_empty_strings_on_both_sides_are_not_reusable() -> None:
    previous = mutated(("keys", "k", "entry_version"), "")
    assert reuse([{**ENTRY, "entryVersion": ""}], previous) == set()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFOs")
def test_read_previous_body_never_blocks_on_a_fifo(tmp_path):
    os.mkfifo(tmp_path / "k.md")
    result = {}
    worker = threading.Thread(target=lambda: result.setdefault("body", read_previous_body(tmp_path, "k.md")))
    worker.start()
    worker.join(5)
    alive = worker.is_alive()
    if alive:  # unblock the stuck reader so the test run can finish
        with open(tmp_path / "k.md", "wb"):
            pass
        worker.join(5)
    assert not alive and result["body"] is None
