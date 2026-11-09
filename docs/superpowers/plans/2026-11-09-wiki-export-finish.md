# Wiki export finish (history reuse, MCP tool, wikilinks, cloud warning) Implementation Plan

> **For agentic workers:** Implement this plan task-by-task (one fresh subagent per task, or inline with checkpoints). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish `bilinc wiki` for 2.7.0: reuse unchanged history blocks on reruns, add `--wikilinks` and `--refresh-history`, warn about cloud-synced folders, add the local MCP `export_wiki` tool, and fix case-only renames and two `md_inline` escapes.

**Architecture:** Two new pure modules: `wiki/reuse.py` (find, hash and read back a page's history section; decide reuse) and `wiki/location.py` (cloud-folder warning, MCP path containment). `fetch.py` gains a marker fetch through the existing retry loop; `manifest.py` gains three optional fields; `render.py` gains a link-style switch and accepts a pre-rendered history block; `export.py` wires the marker, the reuse decision and a second history pass; `writer.py` fixes on-disk spelling. CLI and MCP are thin wrappers over `export_wiki`.

**Tech Stack:** Python 3.10+ standard library only, pytest, `mcp` (already a dependency).

**Spec:** `docs/superpowers/specs/2026-11-09-wiki-export-design.md`, section "Addendum: finishing the export" (A1–A6), approved at G1 (`APPROVAL-RESPONSE-1`: D1 = no runtime change, residual documented; D4 + Bilinc config folder refused).

## Global Constraints

- No new runtime dependencies; public API additive only; existing CLI flags and SDK behaviour unchanged. No change to `src/bilinc/cloud/runtime.py` (G1 D1 = b).
- Tests never touch the network or read API keys: `tests/wiki_fakes.py` transports only.
- Run tests as `PYTHONPATH=src ~/work/bilinc-dev/.venv-wiki/bin/python -m pytest -q -p no:cacheprovider <files>`; full suite after every 3 tasks; `~/work/bilinc-dev/.venv-wiki/bin/ruff check src tests` before each commit.
- Commit messages: plain English imperative, no trailers. Stage explicit paths only.
- Reuse must never show a block the service would now return differently, except the residual stated in A1 (a rollback still restoring keys during the run).
- Marker call: `history("__system", limit=1, values="none")`; marker = sha256 hex of `json.dumps({"entries": e, "truncated": t}, sort_keys=True, ensure_ascii=False)`; `exists` ignored.
- `HISTORY_FORMAT = 1`; page read cap 8 MiB; `history_sha256` over the body encoded `utf-8`, `errors="replace"`.
- `CLOUD_MCP_TOOLS` stays unchanged; `LOCAL_MCP_TOOLS = ("export_wiki",)`.
- User-facing text claims only "history is reused when nothing changed"; never "verifies", "only", "first".

## File map

| File | Change |
|---|---|
| `src/bilinc/wiki/render.py` | `~` and e-mail escapes; `wikilinks` switch for every link; `ReusedHistory` pass-through |
| `src/bilinc/wiki/reuse.py` (new) | `history_body`, `history_digest`, `read_previous_body`, `reusable_keys` |
| `src/bilinc/wiki/manifest.py` | `HISTORY_FORMAT`; optional `history_marker`, `history_format`, per-key `history_sha256` |
| `src/bilinc/wiki/fetch.py` | shared retry loop; `fetch_marker` |
| `src/bilinc/wiki/export.py` | marker start/end, reuse, second pass, new result counts, `wikilinks`, `refresh_history`, `warnings` |
| `src/bilinc/wiki/writer.py` | case-only spelling fix through `.bilinc-wiki.tmp/.old/<n>` |
| `src/bilinc/wiki/location.py` (new) | `cloud_sync_warning`, `check_mcp_target` |
| `src/bilinc/cli/main.py` | `--wikilinks`, `--refresh-history`, warning lines, new summary |
| `src/bilinc/cloud_mcp.py` | `export_wiki` tool, `LOCAL_MCP_TOOLS` |
| `docs/public/product-truth.json`, `scripts/validate_public_truth.py`, `scripts/generate_public_truth_doc.py`, generated doc, `scripts/verify_cloud_lifecycle_smoke.py`, `docs/mcp-server.md` | local tool list |
| `tests/wiki_fakes.py` | ordered call log, marker counting, `__system` script |
| tests | `test_wiki_render.py`, `test_wiki_reuse.py` (new), `test_wiki_manifest.py`, `test_wiki_fetch.py`, `test_wiki_reuse_integration.py` (new), `test_wiki_writer.py`, `test_wiki_location.py` (new), `test_wiki_cli.py`, `test_wiki_mcp.py` (new), `test_cloud_memory_review_sdk.py` |

## Order and parallelism

- Wave 1 (independent files; at most 2 subagents at once, I take the rest): **T1→T2** (render.py, sequential), **T3** (reuse.py), **T4** (manifest.py), **T5** (fetch.py + wiki_fakes.py), **T6** (writer.py), **T7** (location.py). Parallel-safe pairs: T3‖T7, T4‖T6, T5‖T1.
- Wave 2: **T8** export integration (needs T2–T5).
- Wave 3: **T9** CLI and **T10** MCP (need T7, T8); T9‖T10 (disjoint files).
- S4 (not a task here): extend `scripts/wiki_smoke.py`; S6: CHANGELOG.

---

### Task 1: `md_inline` escapes single `~` and e-mail autolinks

**Files:** Modify `src/bilinc/wiki/render.py` (constants near line 43–47, `md_inline` ~line 66). Test `tests/test_wiki_render.py`.

**Interfaces:** Produces: `md_inline(text: str) -> str` (same signature).

- [ ] **Step 1: failing tests**

```python
def test_md_inline_escapes_every_tilde() -> None:
    assert md_inline("a ~x~ b") == "a \\~x\\~ b"
    assert md_inline("~~gone~~") == "\\~\\~gone\\~\\~"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("mail jin@example.com now", "mail jin\\@example\\.com now"),
        ("a.b+c@sub.example.org", "a.b+c\\@sub\\.example\\.org"),
        ("user@localhost", "user@localhost"),  # no dot after @: GFM does not link it
        ("@handle", "@handle"),
    ],
)
def test_md_inline_keeps_email_like_text_inert(raw: str, expected: str) -> None:
    assert md_inline(raw) == expected
```

- [ ] **Step 2:** run `tests/test_wiki_render.py -k "tilde or email"` → FAIL.
- [ ] **Step 3: implement**

```python
#: Obsidian's ``$`` math and GFM's ``~x~`` strike (a single tilde is enough
#: there), and Obsidian's ``%%`` comments and ``==`` highlights (doubled only).
_OBSIDIAN_SINGLE = re.compile(r"([$~])")
_OBSIDIAN_DOUBLED = re.compile(r"([%=])\1+")
#: An e-mail address GFM would turn into a mailto: link on its own.
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
```

In `md_inline`, after the `_AUTOLINK` line (the earlier substitutions never touch `@`, `.` or `-`; `%` and `_` inside the run may already carry a backslash, so match on the escaped text with a pattern that tolerates `\\` before `_`/`%`):

```python
_EMAIL = re.compile(r"(?:[A-Za-z0-9.+\-]|\\[_%])+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
...
    out = _EMAIL.sub(lambda match: _inert_email(match.group()), out)


def _inert_email(text: str) -> str:
    local, _, domain = text.partition("@")
    return local + "\\@" + domain.replace(".", "\\.")
```

- [ ] **Step 4:** run the whole `tests/test_wiki_render.py` → PASS (existing `~~` test still passes: every `~` escaped).
- [ ] **Step 5:** `git add src/bilinc/wiki/render.py tests/test_wiki_render.py && git commit -m "Escape single tildes and e-mail addresses in wiki inline text"`

### Task 2: `--wikilinks` link style in every generated link

**Files:** Modify `src/bilinc/wiki/render.py` (`_link_list`, `render_page`, `_page_link`, `render_index`, `render_folder_indexes`), `src/bilinc/wiki/export.py` (`build_files` signature only). Test `tests/test_wiki_render.py`.

**Interfaces:**
- Produces: `link(text: str, from_path: str, to_path: str, *, wikilinks: bool, in_table: bool = False) -> str`; keyword `wikilinks: bool = False` on `render_page`, `render_index`, `render_folder_indexes`, `build_files`.
- Produces: `class ReusedHistory(str)`; `render_page(history=ReusedHistory(body))` writes `"## History\n\n" + body + "\n"` (body has its trailing newlines stripped, see Task 3).

- [ ] **Step 1: failing tests**

```python
def test_link_markdown_default() -> None:
    assert link("a:b", "x/y.md", "a/b.md", wikilinks=False) == "[a:b](../a/b.md)"


def test_wikilink_relative_with_dot_and_extension() -> None:
    assert link("a:b", "a/c.md", "a/b.md", wikilinks=True) == "[[./b.md|a:b]]"
    assert link("a:b", "x/y.md", "a/b.md", wikilinks=True) == "[[../a/b.md|a:b]]"
    assert link("a:b", "index.md", "a/b.md", wikilinks=True, in_table=True) == "[[./a/b.md\\|a:b]]"


@pytest.mark.parametrize("key", ["a[1]", "a|b", "a#b", "a^b", "a\\b", "a`b"])
def test_wikilink_falls_back_to_markdown_for_unsafe_text(key: str) -> None:
    out = link(key, "index.md", "p.md", wikilinks=True)
    assert out.startswith("[") and not out.startswith("[[") and out.endswith("(p.md)")


def test_wikilink_target_is_not_percent_encoded() -> None:
    assert link("a/b", "index.md", "a%2Fb.md", wikilinks=True) == "[[./a%2Fb.md|a/b]]"


def test_wikilinks_reach_pages_index_and_folder_indexes() -> None:
    entries = [{"key": "a:b", "value": "see a:c"}, {"key": "a:c", "value": "x"}]
    files, _ = build_files(entries, None, exported_at="2026-11-09T01:00:00Z", version="2.7.0", prefix=None, wikilinks=True)
    assert "[[./c.md|a:c]]" in files["a/b.md"]
    assert "[[./b.md|a:b]]" in files["a/c.md"]
    assert "[[./a/b.md\\|a:b]]" in files["index.md"]
    assert "[[./b.md|b]]" in files["a/_index.md"]
    for text in files.values():
        assert not [t for t in link_targets_outside_fences(text) if t.endswith(".md")]


def test_reused_history_is_inserted_verbatim() -> None:
    entry = {"key": "k", "value": "v"}
    page = render_page(entry, path="k.md", paths={"k": "k.md"}, outgoing=[], incoming=[],
                       history=ReusedHistory("- update · 2026-11-08 12:00:00 UTC"), exported_at="t")
    assert page.endswith("## History\n\n- update · 2026-11-08 12:00:00 UTC\n")
```

(`link_targets_outside_fences` is the existing helper in `tests/wiki_md.py`; it returns Markdown link targets outside fences.)

- [ ] **Step 2:** run → FAIL (`link`, `ReusedHistory` undefined).
- [ ] **Step 3: implement**

```python
_WIKILINK_UNSAFE = frozenset("[]|#^\\`")


class ReusedHistory(str):
    """A history section body taken byte for byte from the previous page."""


def link(text: str, from_path: str, to_path: str, *, wikilinks: bool, in_table: bool = False) -> str:
    """One generated link: standard Markdown, or ``[[./rel.md|alias]]`` with ``wikilinks``.

    A wikilink is used only when neither the target nor the alias holds a
    character that cannot be written inside one; that link falls back to the
    Markdown form.
    """
    start = posixpath.dirname(from_path) or "."
    relative = posixpath.relpath(to_path, start)
    alias = fold_lines(text)
    if wikilinks and not (_WIKILINK_UNSAFE & set(relative + alias)):
        target = relative if relative.startswith("../") else "./" + relative
        return f"[[{target}{'\\|' if in_table else '|'}{alias}]]"
    return f"[{md_inline(text)}]({urllib.parse.quote(relative, safe='/')})"
```

(Python 3.10 cannot hold a backslash inside an f-string expression: compute `separator = "\\|" if in_table else "|"` first.)
`_link_list(keys, path, paths, wikilinks)` → `f"- {link(key, path, paths[key], wikilinks=wikilinks)}\n"`. `_page_link(key, path)` becomes `link(key, "index.md", path, wikilinks=wikilinks, in_table=...)` (recent list `in_table=False`, table `True`). In `render_folder_indexes`, subfolder lines use `link(sub + "/", f"{folder}/_index.md", f"{folder}/{sub}/_index.md", ...)` and page lines `link(display, f"{folder}/_index.md", f"{folder}/{name}", ...)`; with `wikilinks=False` the output must stay byte-identical to today (existing tests prove it). `render_page`: `if isinstance(history, ReusedHistory): sections.append("## History\n\n" + history + "\n")`, else as today. `build_files(..., wikilinks=False)` passes it through.
- [ ] **Step 4:** run `tests/test_wiki_render.py tests/test_wiki_export.py` → PASS (determinism and hostile-key tests unchanged).
- [ ] **Step 5:** commit `"Add a wikilink style for every link the wiki writes"`.

### Task 3: find, hash and read back a page's history section (`reuse.py`)

**Files:** Create `src/bilinc/wiki/reuse.py`, `tests/test_wiki_reuse.py`.

**Interfaces:**
- Produces: `PAGE_READ_LIMIT = 8 * 1024 * 1024`; `history_body(page: str) -> str | None`; `history_digest(body: str) -> str`; `read_previous_body(target: Path, rel: str) -> str | None`; `reusable_keys(entries, previous, *, history, marker, refresh, version, history_format) -> set[str]`.
- Consumes: `render_page`, `history_section` (render.py), `validate_rel_path` (manifest.py).

- [ ] **Step 1: failing tests** (each builds pages with the real `render_page`, so the parser is tested against our own format)

```python
def page(value, history, links=()):
    paths = {"k": "k.md", **{other: f"{other}.md" for other in links}}
    return render_page({"key": "k", "value": value}, path="k.md", paths=paths, outgoing=list(links),
                       incoming=[], history=history, exported_at="2026-11-09T01:00:00Z")


HIST = {"entries": [{"op": "update", "at": 1762600000.0, "reason": "## Links\n```", "after": "x"}], "truncated": False}


def test_body_is_the_rendered_section_without_trailing_newlines():
    assert history_body(page("v", HIST)) == history_section(HIST).rstrip("\n")


def test_body_is_the_same_with_or_without_a_links_section():
    assert history_body(page("v", HIST, links=["other"])) == history_body(page("v", HIST))


def test_headings_inside_value_fences_are_ignored():
    tricky = "x\n## History\n\nfake\n## Links\n" + "`" * 7
    assert history_body(page(tricky, HIST)) == history_section(HIST).rstrip("\n")


def test_no_history_section_gives_none():
    assert history_body(page("v", None)) is None


def test_digest_hashes_bytes_as_written():
    assert history_digest("a\ud800b") == hashlib.sha256("a?b".encode()).hexdigest()


def test_read_previous_body_refuses_symlink_folder_and_big_files(tmp_path):
    (tmp_path / "k.md").write_text(page("v", HIST))
    assert read_previous_body(tmp_path, "k.md") == history_section(HIST).rstrip("\n")
    (tmp_path / "real").mkdir(); (tmp_path / "real" / "p.md").write_text(page("v", HIST))
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
```

`reusable_keys` tests (pure; no disk): a base `previous` manifest dict `{"complete": True, "tool_version": "2.7.0", "history_format": 1, "history": 5, "history_marker": "m"*... , "keys": {"k": {"path": "k.md", "entry_version": "v1", "updated_at": "t1", "history_sha256": "h"}}}` and entry `{"key": "k", "entryVersion": "v1", "updatedAt": "t1"}`; `reusable_keys([...], previous, history=5, marker=M, refresh=False, version="2.7.0", history_format=1) == {"k"}`; then one parametrized test per off-rule, each mutating one field and expecting `set()`: `refresh=True`; `history=0`; `history=6`; `previous=None`; `complete False`; `tool_version "2.6.3"`; `history_format 2` / missing; `marker None`; manifest `history_marker None` / different; `entryVersion` changed; `updatedAt` changed; either side missing or non-string; `history_sha256` missing or not 64-hex.

- [ ] **Step 2:** run → FAIL (module missing).
- [ ] **Step 3: implement**

```python
"""Reusing history blocks from the previous run of a wiki export.

A block is reused only when the previous manifest says the key's stored
entry is unchanged, the run marker (the newest ``__system`` history entry,
which every rollback changes) is unchanged, and the block read back from the
previous page hashes to what that run recorded. See the design addendum A1.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Any

from bilinc.wiki.manifest import ManifestError, validate_rel_path

PAGE_READ_LIMIT = 8 * 1024 * 1024
_HEX64 = re.compile(r"[0-9a-f]{64}")
_FENCE = re.compile(r"(`{3,})[^`]*")


def history_body(page: str) -> str | None:
    """The ``## History`` section body of one of our pages, trailing newlines stripped."""
    lines = page.split("\n")
    fence = None
    start = None
    for index, line in enumerate(lines):
        if fence is not None:
            if line == fence:
                fence = None
            continue
        opened = _FENCE.fullmatch(line)
        if opened:
            fence = opened.group(1)
            continue
        if line.startswith("## "):
            if start is not None:
                return "\n".join(lines[start:index]).rstrip("\n")
            if line == "## History" and index + 1 < len(lines) and lines[index + 1] == "":
                start = index + 2
    if start is None:
        return None
    return "\n".join(lines[start:]).rstrip("\n")


def history_digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()


def read_previous_body(target: Path, rel: str) -> str | None:
    """Read the history body of ``target/rel`` without following any symlink; None when unusable."""
    try:
        validate_rel_path(rel)
    except ManifestError:
        return None
    current = Path(target)
    for part in rel.split("/")[:-1]:
        current = current / part
        try:
            if not stat.S_ISDIR(os.lstat(current).st_mode):
                return None
        except OSError:
            return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(Path(target) / rel, flags)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > PAGE_READ_LIMIT:
            return None
        raw = handle.read(PAGE_READ_LIMIT + 1)
    if len(raw) > PAGE_READ_LIMIT:
        return None
    try:
        return history_body(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return None


def reusable_keys(entries, previous, *, history, marker, refresh, version, history_format) -> set[str]:
    """Keys whose block may be read back from the previous page (manifest rules only)."""
    if refresh or history <= 0 or previous is None or marker is None:
        return set()
    if (
        previous.get("complete") is not True
        or previous.get("tool_version") != version
        or previous.get("history_format") != history_format
        or previous.get("history") != history
        or previous.get("history_marker") != marker
    ):
        return set()
    keys = previous.get("keys") or {}
    result = set()
    for entry in entries:
        old = keys.get(entry["key"])
        if not isinstance(old, dict):
            continue
        version_now, updated_now = entry.get("entryVersion"), entry.get("updatedAt")
        if not (isinstance(version_now, str) and version_now and isinstance(updated_now, str) and updated_now):
            continue
        if old.get("entry_version") != version_now or old.get("updated_at") != updated_now:
            continue
        if not (isinstance(old.get("history_sha256"), str) and _HEX64.fullmatch(old["history_sha256"])):
            continue
        result.add(entry["key"])
    return result
```

(`bool` for `history`: callers validate it earlier; `previous.get("history") != history` also rejects `True` vs `1` because `export_wiki` refuses bools.)
- [ ] **Step 4:** run `tests/test_wiki_reuse.py` → PASS.
- [ ] **Step 5:** commit `"Read back and hash a wiki page's history section"`.

### Task 4: manifest fields for reuse

**Files:** Modify `src/bilinc/wiki/manifest.py`; test `tests/test_wiki_manifest.py`.

**Interfaces:** Produces: `HISTORY_FORMAT = 1`; `build_manifest(..., history_marker: str | None = None)` writes `history_marker` and `history_format`; per-key dicts pass `history_sha256` through. `read_manifest` keeps malformed reuse fields from causing refusals: it drops a malformed `history_marker` (→ None), `history_format` (→ None) or per-key `history_sha256` (removed).

- [ ] **Step 1: failing tests**

```python
def test_manifest_round_trips_reuse_fields(tmp_path):
    manifest = build_manifest(version="2.7.0", base_url=BASE, prefix=None, history=5, exported_at="t",
                              complete=True, files=["k.md"], history_marker="a" * 64,
                              keys={"k": {"path": "k.md", "entry_version": "v", "updated_at": "u", "history_sha256": "b" * 64}})
    (tmp_path / MANIFEST_NAME).write_text(dumps_manifest(manifest))
    read = read_manifest(tmp_path)
    assert read["history_marker"] == "a" * 64 and read["history_format"] == HISTORY_FORMAT == 1
    assert read["keys"]["k"]["history_sha256"] == "b" * 64


@pytest.mark.parametrize("field, bad", [("history_marker", 5), ("history_marker", "zz"), ("history_format", "1"), ("history_format", True)])
def test_malformed_reuse_fields_disable_reuse_without_refusing(tmp_path, field, bad):
    ...  # write a valid manifest with `field` replaced by `bad`; read_manifest succeeds; the field reads back as None


def test_malformed_key_digest_is_dropped(tmp_path):
    ...  # history_sha256 = "x" → read back without the field; the key and its path are kept


def test_old_manifest_without_reuse_fields_still_reads(tmp_path):
    ...  # a 2.7.0-dev manifest (no fields) reads; history_marker and history_format are None
```

(Write each `...` body in full in the test file: build with `build_manifest`, edit the dict, `dumps_manifest`, `read_manifest`, assert.)
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: implement**: add `HISTORY_FORMAT = 1`, `_HEX64 = re.compile(r"[0-9a-f]{64}")`; `build_manifest` gains `history_marker: str | None = None` and writes `"history_format": HISTORY_FORMAT, "history_marker": history_marker`; `_validated_keys` drops `history_sha256` unless it is a 64-hex string; `read_manifest` normalises `history_marker` (None unless 64-hex) and `history_format` (None unless `int` and not `bool`).
- [ ] **Step 4:** run `tests/test_wiki_manifest.py tests/test_wiki_writer.py` → PASS.
- [ ] **Step 5:** commit `"Record history reuse data in the wiki manifest"`.

### Task 5: marker fetch through the same retry loop; fakes record call order

**Files:** Modify `src/bilinc/wiki/fetch.py`, `tests/wiki_fakes.py`; test `tests/test_wiki_fetch.py`.

**Interfaces:**
- Produces: `MARKER_KEY = "__system"`; `fetch_marker(client, *, sleep, stop=None) -> str | None` (sha256 hex, or None when unavailable after retries; fatal errors raise `HistoryAbort`).
- Produces in fakes: `RoutedTransport.order` → list of `("list", cursor)` / `("history", key, values)` tuples in call order; `marker_calls()` counts history calls with key `__system` and `values == "none"`; `history_calls(key)` and `total_history_calls()` exclude marker calls; a `marker` constructor argument (list script like `history`, default `[{"key": "__system", "exists": False, "entries": [], "truncated": False}]`).

- [ ] **Step 1: failing tests**

```python
def test_marker_hashes_entries_and_truncated_and_ignores_exists():
    rows = [{"op": "rollback", "at": 1.0, "reason": "r", "source": None}]
    a = fetch_marker(make_client(RoutedTransport(marker=[{"exists": False, "entries": rows, "truncated": True}])), sleep=no_sleep)
    b = fetch_marker(make_client(RoutedTransport(marker=[{"exists": True, "entries": rows, "truncated": True}])), sleep=no_sleep)
    expected = hashlib.sha256(json.dumps({"entries": rows, "truncated": True}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert a == b == expected


def test_marker_request_shape():
    transport = RoutedTransport()
    fetch_marker(make_client(transport), sleep=no_sleep)
    assert transport.history_bodies() == [{"key": "__system", "limit": 1, "values": "none"}]
    assert transport.marker_calls() == 1 and transport.total_history_calls() == 0


def test_marker_retries_then_gives_none():
    sleeps = []
    transport = RoutedTransport(marker=[unavailable()])
    assert fetch_marker(make_client(transport), sleep=sleeps.append) is None
    assert transport.marker_calls() == 4 and sleeps == [1.0, 2.0, 4.0]


def test_marker_auth_error_aborts():
    with pytest.raises(HistoryAbort):
        fetch_marker(make_client(RoutedTransport(marker=[auth_error()])), sleep=no_sleep)


def test_marker_non_dict_or_bad_entries_gives_none():
    assert fetch_marker(make_client(RoutedTransport(marker=[{"entries": "x"}])), sleep=no_sleep) is None
```

(Check the exact request body the SDK sends in `CloudClient.history` and match it in `test_marker_request_shape`.) Keep every existing `test_wiki_fetch.py` / integration test green: per-key counts must not include marker calls.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: implement**: move the body of `fetch_one` into a module function `_with_retries(call: Callable[[], Any], wait, stopped) -> Any` returning the result or `HISTORY_UNAVAILABLE`, raising `HistoryAbort` on `FATAL_ERRORS` (the caller of the pool still records it in `fatal` and sets `halt`); `fetch_one(key)` becomes `_with_retries(lambda: history_client.history(key, limit=limit, values="full"), wait, stopped)`. Then:

```python
MARKER_KEY = "__system"


def fetch_marker(client: CloudClient, *, sleep: Callable[[float], None], stop: threading.Event | None = None) -> str | None:
    """Hash of the newest ``__system`` history entry, which every rollback changes; None when unavailable."""
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
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8", errors="replace")).hexdigest()
```

Fakes: `_answer_history` routes `key == "__system" and payload.get("values") == "none"` to the `marker` script and a separate counter; append to `self._order` under the lock in `__call__`.
- [ ] **Step 4:** run `tests/test_wiki_fetch.py tests/test_wiki_integration.py` → PASS.
- [ ] **Step 5:** commit `"Fetch the rollback marker through the wiki retry layer"`.

### Task 6: case-only rename makes the disk spelling match the manifest

**Files:** Modify `src/bilinc/wiki/writer.py` (`write_tree` move loop, new helper); test `tests/test_wiki_writer.py`.

**Interfaces:** Produces: internal `_fix_spelling(target, temp, rel, parked: list[int]) -> None`; `write_tree` signature unchanged.

- [ ] **Step 1: failing tests** (use the existing `case_insensitive` fixture; extend it with `rename` and `listdir` passthroughs so the writer's calls go through the emulation: `rename(src, dst)` resolves `existing(src)`; `listdir` is real)

```python
def test_case_rename_leaves_the_manifest_spelling_on_disk(tmp_path, case_insensitive):
    first_run(tmp_path, {"Foo.md": "old\n"})
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)
    write_tree(tmp_path, {"foo.md": "new\n"}, previous=previous, manifest_for=manifest_for)
    assert [n for n in os.listdir(tmp_path) if n.endswith(".md")] == ["foo.md"]
    assert (tmp_path / "foo.md").read_text() == "new\n"
    assert not (tmp_path / TMP_NAME).exists()


def test_existing_2_7_0_state_is_repaired(tmp_path, case_insensitive):
    # The 2.7.0 writer left "Foo.md" on disk while its manifest says "foo.md".
    (tmp_path / "Foo.md").write_text("stale\n")
    owned = manifest_for(True, ["foo.md"])
    write_tree(tmp_path, {"foo.md": "new\n"}, previous=owned, manifest_for=manifest_for)
    assert [n for n in os.listdir(tmp_path) if n.endswith(".md")] == ["foo.md"]


def test_a_users_case_twin_is_still_refused(tmp_path, case_insensitive):
    first_run(tmp_path, {"bar.md": "x\n"})
    (tmp_path / "Foo.md").write_text("the user's file")
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)
    with pytest.raises(WikiRefused):
        write_tree(tmp_path, {"bar.md": "x\n", "foo.md": "new\n"}, previous=previous, manifest_for=manifest_for)
    assert (tmp_path / "Foo.md").read_text() == "the user's file"


def test_parked_copy_never_lands_on_a_page_path(tmp_path, case_insensitive):
    first_run(tmp_path, {"Foo.md": "old\n", "old/1.md": "page\n"})
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)
    write_tree(tmp_path, {"foo.md": "new\n", "old/1.md": "page\n"}, previous=previous, manifest_for=manifest_for)
    assert (tmp_path / "old" / "1.md").read_text() == "page\n" and (tmp_path / "foo.md").read_text() == "new\n"


def test_crash_after_parking_keeps_the_old_copy_inside_the_temp_folder(tmp_path, case_insensitive, monkeypatch):
    ...  # make the os.replace of foo.md raise once; WikiExportError; Foo.md content only under .bilinc-wiki.tmp/.old/; manifest complete False owns foo.md; rerun completes with only foo.md


def test_nfd_spelling_is_not_churned(tmp_path):
    ...  # on-disk "café.md" in NFD and wanted NFC: no rename happens (spy on os.rename: never called)
```

(Write the `...` bodies in full.)
- [ ] **Step 2:** run → FAIL (disk keeps `Foo.md`).
- [ ] **Step 3: implement**: in the move loop, before `os.replace(source, target / rel)`, call `_fix_spelling(target, temp, rel, parked)`:

```python
def _fix_spelling(target: Path, temp: Path, rel: str, parked: list[int]) -> None:
    """On a case-insensitive folder, move an owned entry with another spelling out of the way first.

    ``_check_paths`` has already refused any entry at ``rel`` that is not ours,
    so whatever sits there now is a page this tool wrote. It is parked under
    ``.bilinc-wiki.tmp/.old/`` (no key maps to a leading-dot folder) and
    removed with the temp folder.
    """
    parent = (target / rel).parent
    name = Path(rel).name
    if _lstat(target / rel) is None:
        return
    on_disk = next(
        (entry for entry in os.listdir(parent) if _fold(entry) == _fold(name) and entry != name), None
    )
    if on_disk is None or unicodedata.normalize("NFC", on_disk) == unicodedata.normalize("NFC", name):
        return
    old = temp / ".old"
    if not parked:
        os.mkdir(old, DIR_MODE)
    parked.append(len(parked))
    os.rename(parent / on_disk, old / str(parked[-1]))
```

Cache `os.listdir(parent)` per parent in a dict passed alongside `parked` if profiling shows it matters (2200 pages: one listdir per folder is enough; implement the cache directly: `listings: dict[Path, list[str]]`). Also ensure `_discard_temp` (rmtree) removes `.old`.
- [ ] **Step 4:** run `tests/test_wiki_writer.py` → PASS, including the two existing case tests.
- [ ] **Step 5:** commit `"Make a case-only page rename change the spelling on disk"`.

### Task 7: cloud-folder warning and MCP path containment (`location.py`)

**Files:** Create `src/bilinc/wiki/location.py`, `tests/test_wiki_location.py`.

**Interfaces:** Produces:
- `cloud_sync_warning(target: str | os.PathLike, *, home: Path | None = None) -> str | None`;
- `check_mcp_target(directory: str, *, home: Path | None = None, config_dir: Path | None = None, refused_roots: tuple[str, ...] | None = None, temp_dirs: tuple[str, ...] | None = None) -> Path` (returns the resolved target; raises `WikiRefused` with the reason);
- `SYSTEM_ROOTS` (POSIX tuple from A2), `WINDOWS_ROOTS()` (from `%SystemRoot%`, `%ProgramFiles%`, `%ProgramFiles(x86)%`).

- [ ] **Step 1: failing tests** (all inject `home=tmp_path/"home"`, `config_dir`, `refused_roots`, `temp_dirs` built under `tmp_path`, so they run the same on Linux and macOS)

```python
@pytest.mark.parametrize("rel, name", [
    ("Library/Mobile Documents/com~apple~CloudDocs/wiki", "iCloud Drive"),
    ("Library/CloudStorage/Dropbox/wiki", "Dropbox"),
    ("Library/CloudStorage/OneDrive-Personal/wiki", "OneDrive-Personal"),
    ("Dropbox/notes/wiki", "Dropbox"),
    ("OneDrive - Acme/wiki", "OneDrive - Acme"),
])
def test_cloud_warning_names_the_service(home, rel, name):
    message = cloud_sync_warning(home / rel, home=home)
    assert message and name in message and "warning:" in message


def test_cloud_warning_follows_symlinks(home, tmp_path):
    (home / "Dropbox").mkdir(); (tmp_path / "w").symlink_to(home / "Dropbox")
    assert cloud_sync_warning(tmp_path / "w" / "wiki", home=home)


def test_no_warning_elsewhere(home):
    assert cloud_sync_warning(home / "Documents" / "wiki", home=home) is None
    assert cloud_sync_warning(home / "DropboxBackup", home=home) is None


@pytest.mark.parametrize("given", ["relative/wiki", "", "./x"])
def test_mcp_refuses_relative(env, given): ...
@pytest.mark.parametrize("rel", [".", ".."])  # home itself, ancestor of home
def test_mcp_refuses_home_and_ancestors(env, rel): ...
def test_mcp_refuses_filesystem_root(env): ...           # "/"
def test_mcp_refuses_system_roots_and_inside(env): ...   # injected root R: R and R/sub refused
def test_mcp_refuses_hidden_home_folders(env): ...       # ~/.ssh/wiki, ~/.config/x
def test_mcp_refuses_library_but_not_cloud_folders(env): ...  # ~/Library/x refused; Mobile Documents and CloudStorage allowed
def test_mcp_refuses_config_dir_equal_inside_or_containing(env): ...
def test_mcp_refuses_symlinked_last_component(env): ...  # ~/wiki -> ~/Documents/real
def test_mcp_follows_symlinks_in_parents(env): ...       # ~/link -> /injected/system/root → refused (resolved inside a refused root)
def test_mcp_compares_by_identity_not_spelling(env, case_alias): ...  # a hard-linked / bind alias spelling of ~/.ssh is still refused; uses os.stat identity
def test_mcp_temp_carve_out_wins_over_system_root(env): ...  # temp dir under an injected refused root is allowed
def test_mcp_refuses_unc_and_strips_long_prefix(env): ...    # "\\\\server\\share\\x" refused; "\\\\?\\" prefix stripped (string-level, any OS)
def test_mcp_accepts_a_normal_folder_and_returns_resolved(env): ...  # ~/Documents/wiki (missing, parent exists) → resolved path
def test_mcp_expands_tilde(env, monkeypatch): ...         # HOME patched → "~/Documents/wiki" accepted
```

(Write every body in full. `case_alias`: on Linux, create the alias as a symlinked parent spelling `~/SSH-ALIAS -> ~/.ssh`; the realpath lands in `~/.ssh` and identity comparison refuses it.)
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: implement** (sketch of the core; write it fully):

```python
CLOUD_FOLDERS = (("Library/Mobile Documents", "iCloud Drive"),)
SYSTEM_ROOTS = ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/opt", "/proc", "/root",
                "/run", "/sbin", "/srv", "/sys", "/usr", "/var", "/private", "/System", "/Library",
                "/Applications", "/cores")
CONTAINER_ROOTS = ("/Volumes", "/mnt")


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_dev, info.st_ino) if info.st_ino else None


def _chain(resolved: Path) -> list[Path]:
    """``resolved`` and its existing ancestors, nearest first."""
    return [p for p in (resolved, *resolved.parents) if os.path.lexists(p)]


def _inside(resolved: Path, root: Path) -> bool:
    """True when ``resolved`` is ``root`` or below it, by file identity where available, else casefolded text."""
    wanted = _identity(root)
    if wanted is not None:
        return any(_identity(p) == wanted for p in _chain(resolved))
    text, base = os.path.normcase(str(resolved)).casefold(), os.path.normcase(str(root)).casefold()
    return text == base or text.startswith(base.rstrip(os.sep) + os.sep)
```

`cloud_sync_warning`: resolve with `os.path.realpath`; check `_inside` against `home/"Library/Mobile Documents"` (iCloud Drive), each child of `home/"Library/CloudStorage"` (name = child name), `home/"Dropbox"`, and each `home` child whose name starts with `OneDrive`; message `f"warning: {target} is inside a cloud-synced folder ({name}); the sync client may upload this export, which can hold private data, or keep conflicting copies"`.
`check_mcp_target`: strip `\\?\`; refuse a leading `\\` (UNC); `expanduser`; refuse non-absolute; `resolved = Path(os.path.realpath(given))`; refuse when `os.path.islink(given)`; refuse `resolved == resolved.anchor-path`; refuse home or any ancestor of home (`_inside(home, resolved)`); refuse config dir equal/inside/containing (`_inside(resolved, config) or _inside(config, resolved)`); compute `temp_ok = any(_inside(resolved, t) for t in temp_dirs)`; unless `temp_ok`, refuse `_inside(resolved, root)` for every system root that exists; refuse `resolved` equal to a container root; refuse any component under home starting with `.`; refuse `_inside(resolved, home/"Library")` unless inside Mobile Documents or CloudStorage. Defaults: `home = Path.home()`, `config_dir = config_path().parent` (from `bilinc.client`), `refused_roots = SYSTEM_ROOTS` (+ Windows roots on `os.name == "nt"`), `temp_dirs = (realpath(tempfile.gettempdir()), "/private/tmp")`.
- [ ] **Step 4:** run `tests/test_wiki_location.py` → PASS.
- [ ] **Step 5:** commit `"Add the cloud-folder warning and MCP target checks for the wiki"`.

### Task 8: history reuse, marker and new options in `export_wiki`

**Files:** Modify `src/bilinc/wiki/export.py`; create `tests/test_wiki_reuse_integration.py`.

**Interfaces:**
- Consumes: T2 `build_files(..., wikilinks)`, `ReusedHistory`; T3 `reusable_keys`, `read_previous_body`, `history_body`, `history_digest`; T4 `HISTORY_FORMAT`, `build_manifest(history_marker=...)`; T5 `fetch_marker`; T7 `cloud_sync_warning`.
- Produces: `export_wiki(client, target, *, history=5, prefix=None, wikilinks=False, refresh_history=False, home=None, clock=None, sleep=None, progress=None) -> ExportResult`; `ExportResult` gains `history_fetched: int`, `history_reused: int`, `warnings: list[str]`; `summary_line(result, target) -> str` returning `f"Wrote {pages} pages to {target} (removed {n} stale files; history: {fetched} fetched, {reused} reused)"` (used by CLI and MCP).

Run sequence inside `export_wiki`:
1. validate; `warnings = [w] if (w := cloud_sync_warning(target, home=home)) else []`; `previous = inspect_target(...)`.
2. `read_marker = history > 0 and not refresh_history` (a fresh folder included, so the first run records a marker the next run can compare with).
3. if `read_marker`: `start = fetch_marker(...)` (before the list); if `None`, append `"note: history reuse is off for this run (the rollback marker could not be read)"` to `warnings`.
4. `entries = fetch_entries(...)`.
5. `candidates = reusable_keys(entries, previous, history=history, marker=start, refresh=refresh_history, version=__version__, history_format=HISTORY_FORMAT)`; for each candidate read `body = read_previous_body(target, previous["keys"][key]["path"])` and keep it only when `history_digest(body) == previous["keys"][key]["history_sha256"]`.
6. fetch the remaining keys with `fetch_histories`.
7. if `read_marker` and reused blocks exist: `end = fetch_marker(...)`; if `end != start`, fetch the reused keys with a second `fetch_histories` call and drop the reused blocks.
8. histories = fetched dicts ∪ `{key: ReusedHistory(body)}`; build files; per-key manifest entry gets `history_sha256 = history_digest(history_body(files[path]))` when the key's history is a dict or a `ReusedHistory`; never for `HISTORY_UNAVAILABLE`.
9. manifest gets `history_marker=start` (None when not read).
10. counts: `history_fetched` = per-key history fetches that ran (not retries), `history_reused` = blocks kept.

- [ ] **Step 1: failing tests** (all with `RoutedTransport` and the real client; `clock` fixed; `sleep` recorded)

```python
def test_second_run_on_unchanged_data_makes_only_list_and_marker_calls(tmp_path):
    items = entries(250)
    first = RoutedTransport(paged(items), default_history=HIST)
    export(tmp_path, first)
    after_first = snapshot(tmp_path)
    assert first.marker_calls() == 1  # start marker only: nothing reused, so no end read
    second = RoutedTransport(paged(items), default_history=HIST)
    result = export(tmp_path, second, clock=SECOND)
    assert second.total_history_calls() == 0 and second.marker_calls() == 2
    assert len(second.list_bodies()) == 3
    assert result.history_reused == 250 and result.history_fetched == 0
    assert normalised(snapshot(tmp_path)) == normalised(after_first)
```

```python
def test_marker_is_read_first_and_last(tmp_path): ...
    # second run: transport.order[0] == ("history", "__system", "none"); the last order item is the end marker,
    # after every list call; with no reuse candidates the end marker is not read
def test_changed_entry_version_refetches_only_that_key(tmp_path): ...
    # key 7's entryVersion and history change; exactly history_calls(key7) == 1; page shows the new block
def test_changed_updated_at_only_refetches_that_key(tmp_path): ...
def test_rollback_restores_old_version_but_marker_change_refetches_all(tmp_path): ...
    # second run: same entries, new per-key history, marker script returns a new rollback row → every key fetched, pages show new blocks
    # this is the test that must fail if reusable_keys ignores the marker
def test_rollback_during_the_run_refetches_reused_keys_in_the_same_run(tmp_path): ...
    # marker script [M1, M2] on run 2 → start != end → second pass fetches all; manifest history_marker == hash(M1); run 3 with marker M2 refetches all again
def test_refresh_history_fetches_everything_and_skips_the_marker(tmp_path): ...
def test_different_history_count_refetches(tmp_path): ...
def test_incomplete_previous_manifest_refetches(tmp_path): ...
def test_other_tool_version_refetches(tmp_path, monkeypatch): ...  # patch export.__version__
def test_marker_failure_turns_reuse_off_with_a_note(tmp_path): ...  # marker script [unavailable()] → all fetched; warnings has the note; manifest history_marker None; next run fetches all again
def test_missing_page_refetches_that_key(tmp_path): ...
def test_page_replaced_by_symlink_refetches_and_target_untouched(tmp_path): ...
def test_page_edited_inside_history_refetches(tmp_path): ...
def test_page_edited_outside_history_still_reuses(tmp_path): ...  # value fence edited → block reused, page rewritten from data
def test_unavailable_history_is_never_reused(tmp_path): ...  # key whose run-1 history failed has no history_sha256; run 2 fetches it
def test_user_key_named_system_is_exported_and_counted_apart(tmp_path): ...
def test_cloud_warning_is_returned(tmp_path): ...  # home injected so target sits in home/Dropbox
def test_wikilinks_option_reaches_the_files(tmp_path): ...
def test_reused_pages_are_byte_identical_to_fetched_pages(tmp_path): ...  # run 2 reused vs run 2' with refresh: identical files except exported_at
```

(Write every body in full; reuse `entries`, `paged`, `export`, `snapshot` and a `normalised` helper that replaces `exported_at` values, as `tests/test_wiki_integration.py` and `tests/test_wiki_export.py` do.)
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: implement** the sequence above in `export_wiki`; keep `fetch_histories` and `HistoryAbort` handling identical for both passes; keep `KeyboardInterrupt` behaviour (the marker uses the same `stop` event).
- [ ] **Step 4:** run `tests/test_wiki_reuse_integration.py tests/test_wiki_integration.py tests/test_wiki_export.py` → PASS. Then the mutation check: temporarily delete `or previous.get("history_marker") != marker` in `reuse.py`, run `-k rollback_restores` → must FAIL; restore. Record the result in STATE.md.
- [ ] **Step 5:** commit `"Reuse unchanged history blocks when the rollback marker is unchanged"`.

### Task 9: CLI options, warnings and summary

**Files:** Modify `src/bilinc/cli/main.py` (`_run_wiki`, `wiki` parser); test `tests/test_wiki_cli.py`.

**Interfaces:** Consumes `export_wiki(..., wikilinks, refresh_history)`, `ExportResult.warnings`, `summary_line`.

- [ ] **Step 1: failing tests**

```python
def test_help_lists_new_flags(cli, capsys):
    with pytest.raises(SystemExit):
        cli.main(["wiki", "--help"])
    out = capsys.readouterr().out
    assert "--wikilinks" in out and "--refresh-history" in out


def test_flags_reach_export(cli, monkeypatch, tmp_path): ...   # spy on export_wiki kwargs
def test_summary_line_reports_fetched_and_reused(cli, ...): ...  # stdout == summary_line(...) + "\n"
def test_warnings_go_to_stderr_before_the_summary(cli, ...): ...  # result.warnings printed to stderr, stdout only the summary
```

- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: implement**: `wiki.add_argument("--wikilinks", action="store_true", help="Write [[...]] links (Obsidian style) instead of standard Markdown links")`; `wiki.add_argument("--refresh-history", action="store_true", help="Fetch every page's history again instead of reusing unchanged blocks")`; pass both; print each `result.warnings` line to stderr; print `summary_line(result, args.dir)`.
- [ ] **Step 4:** run `tests/test_wiki_cli.py` → PASS.
- [ ] **Step 5:** commit `"Add --wikilinks and --refresh-history to bilinc wiki"`.

### Task 10: MCP `export_wiki` in the local stdio adapter, tool lists and product truth

**Files:** Modify `src/bilinc/cloud_mcp.py`, `tests/test_cloud_memory_review_sdk.py`, `docs/public/product-truth.json`, `scripts/validate_public_truth.py`, `scripts/generate_public_truth_doc.py` and the doc it generates (run it with `--check` to find it), `scripts/verify_cloud_lifecycle_smoke.py`, `docs/mcp-server.md`; create `tests/test_wiki_mcp.py`.

**Interfaces:** Produces `LOCAL_MCP_TOOLS = ("export_wiki",)`; tool `export_wiki(directory: str, history: int = 5, prefix: str | None = None, wikilinks: bool = False, refresh_history: bool = False) -> dict`.

- [ ] **Step 1: failing tests**

```python
def test_registered_tools_are_cloud_plus_local():
    from bilinc.cloud_mcp import CLOUD_MCP_TOOLS, LOCAL_MCP_TOOLS
    assert set(_tools()) == set(CLOUD_MCP_TOOLS) | set(LOCAL_MCP_TOOLS)
    assert "export_wiki" not in CLOUD_MCP_TOOLS


def test_export_wiki_annotations():
    tool = _tools()["export_wiki"]
    assert tool.title == "Export memory as a Markdown wiki"
    assert tool.annotations.readOnlyHint is False and tool.annotations.destructiveHint is True
    assert tool.annotations.idempotentHint is False and tool.annotations.openWorldHint is False


def test_export_wiki_returns_the_cli_summary_as_data(tmp_path, monkeypatch): ...
    # patch create_client to a make_client(RoutedTransport(...)); patch check_mcp_target defaults via monkeypatch of location.Path.home / pass through;
    # result keys: directory, pages, written, removed, removed_paths, skipped, history_unavailable, history_fetched, history_reused, warnings, summary
def test_export_wiki_refuses_a_contained_path_before_any_call(tmp_path, monkeypatch): ...  # "/etc/wiki" → raises, transport has no calls
def test_export_wiki_refuses_relative_path(...): ...
def test_description_states_facts_and_the_time_note(): ...  # no "you should"/"you must"; mentions that a first export of a large workspace can take minutes
```

Update `test_cloud_mcp_tool_constant_matches_the_registered_tools` to the union; product truth: `"cloud_mcp": {"transport": "stdio", "tools": [... unchanged ...], "local_tools": ["export_wiki"]}`; validator compares `tools + local_tools` with the AST scan and checks `local_tools` ∩ `tools` is empty; regenerate the doc; lifecycle smoke compares with `CLOUD_MCP_TOOLS + LOCAL_MCP_TOOLS`; `docs/mcp-server.md` adds one paragraph naming `export_wiki` as local-only.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: implement**

```python
#: Tools only this stdio adapter has: they act on the user's own disk, so the
#: hosted server never offers them.
LOCAL_MCP_TOOLS = ("export_wiki",)
...
    @mcp.tool(
        title="Export memory as a Markdown wiki",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            # Replaces and removes pages an earlier export wrote in the folder.
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def export_wiki(
        directory: str,
        history: int = 5,
        prefix: str | None = None,
        wikilinks: bool = False,
        refresh_history: bool = False,
    ) -> dict[str, Any]:
        """Write every stored memory as Markdown pages in a folder on this machine.

        `directory` is an absolute path (`~` allowed): a new folder, an empty
        one, or an earlier export. The root, the home folder, system and
        hidden folders, and the Bilinc config folder are refused, and so is a
        non-empty folder that is not an earlier export. Files the user added
        are never changed. `history` (0-100) is the number of recorded changes
        per page; unchanged blocks are reused from the previous export unless
        `refresh_history` is set. A first export of a large workspace can take
        minutes. Returns the counts the CLI prints and any warnings.
        """

        from bilinc.wiki import export_wiki as run_export, summary_line
        from bilinc.wiki.location import check_mcp_target

        resolved = check_mcp_target(directory)
        result = run_export(create_client(), resolved, history=history, prefix=prefix,
                            wikilinks=wikilinks, refresh_history=refresh_history)
        return {
            "directory": str(resolved),
            "pages": result.pages,
            "written": result.written,
            "removed": len(result.removed),
            "removed_paths": result.removed,
            "skipped": result.skipped,
            "history_unavailable": result.history_unavailable,
            "history_fetched": result.history_fetched,
            "history_reused": result.history_reused,
            "warnings": result.warnings,
            "summary": summary_line(result, resolved),
        }
```

Export `summary_line` from `bilinc/wiki/__init__.py`. Imports stay lazy so `import bilinc.cloud_mcp` does not load the wiki package.
- [ ] **Step 4:** run `tests/test_wiki_mcp.py tests/test_cloud_memory_review_sdk.py tests/test_public_truth_contract.py tests/test_cloud_lifecycle_contract.py tests/test_cloud_only_package.py` → PASS; `python scripts/validate_public_truth.py` exit 0.
- [ ] **Step 5:** commit `"Add the export_wiki tool to the local MCP adapter"`.

---

## After the tasks (S4–S6, from TASK.md)

- S4: full suite vs baseline 1649/201/1; `ruff`; extend `scripts/wiki_smoke.py` (second run on unchanged data: 0 per-key history calls, 2 marker calls; one changed key refreshed); wheel + `bilinc wiki --help` from a fresh venv; `plugin-scanner==3.46.0` score ≥ 80, no high findings.
- S6: CHANGELOG `[Unreleased] (2.7.0)` additions ("history is reused only when nothing changed", `--wikilinks`, `--refresh-history`, local MCP `export_wiki`, cloud-folder warning, case-rename and escaping fixes; claim rules from the 2.7.0 task); owner steps include the Obsidian wikilink check and the synchronized release chain.

## Self-review

- Spec coverage: A1 → T3, T4, T5, T8; A2 → T7, T10; A3 → T2, T9; A4 → T7, T8, T9; A5 → T1, T6; A6 → T10 + S6. G1 D4 config folder → T7.
- First-run marker: the start marker is read on every run with history > 0 and no `--refresh-history`, so the first run records it (otherwise reuse could never start); the design addendum says the same.
- Names checked across tasks: `ReusedHistory`, `link`, `history_body`, `history_digest`, `read_previous_body`, `reusable_keys`, `HISTORY_FORMAT`, `fetch_marker`, `MARKER_KEY`, `cloud_sync_warning`, `check_mcp_target`, `summary_line`, `LOCAL_MCP_TOOLS`.
