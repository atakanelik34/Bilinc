# Wiki export (`bilinc wiki`) Implementation Plan

> **For agentic workers:** Implement this plan task-by-task (one fresh subagent per task, or inline with checkpoints). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `bilinc wiki <dir> [--history N] [--prefix P]`, a one-way export of a Bilinc Cloud workspace into Obsidian-compatible Markdown pages.

**Architecture:** Pure functions turn the list and history responses into a `{relative path: text}` map (`paths`, `links`, `render`, `manifest`). `fetch` talks to the SDK with one retry layer; `writer` owns every disk operation (guard, temp build, move, stale delete, permissions). `export` wires them together; the CLI is a thin wrapper.

**Tech Stack:** Python 3.10+ standard library only (no new dependencies), pytest.

**Spec:** `docs/superpowers/specs/2026-11-09-wiki-export-design.md` (approved at G1 with the conditions below).

## Global Constraints

- No new runtime dependencies (`tests/test_cloud_only_package.py` pins them).
- Public API is additive only; no existing CLI flag or SDK behaviour changes.
- `client.py` diff stays minimal: two optional attributes and header plumbing, no refactors (G1 condition 1).
- Progress goes to stderr only when stderr is a TTY; stdout carries only the final summary (G1 condition 2).
- Tests never touch the network: fake transports or fake clients only. No API keys are read.
- Run tests as `PYTHONPATH=src ~/work/bilinc-dev/.venv-wiki/bin/python -m pytest -q -p no:cacheprovider <files>`; full suite after every 3 tasks; `ruff check src tests` before each commit.
- Commit messages: plain English imperative, no trailers. Stage explicit paths only.
- Folders 0700, files 0600 (POSIX).
- `--history` default 5, range 0–100; at most 4 concurrent history requests; at most 3 retries per key; `retry_after` capped at 60 s; fallback waits 1, 2, 4 s.
- Names capped at 120 UTF-8 bytes; suffix `~` + first 6 hex of sha256; reserved stems `index`, `_index`, `agents` (casefolded).
- History before/after/reason cut at 300 characters; JSON field-list values cut at 80.

## File map

| File | Responsibility |
|---|---|
| `src/bilinc/client.py` (modify) | `retry_after` on errors, `read_retry_attempts` on the client |
| `src/bilinc/wiki/__init__.py` | re-export `export_wiki`, `ExportResult`, `WikiExportError`, `WikiRefused` |
| `src/bilinc/wiki/paths.py` | key → relative page path |
| `src/bilinc/wiki/links.py` | outgoing / incoming mentions |
| `src/bilinc/wiki/render.py` | Markdown text for pages, `index.md`, `_index.md`, `AGENTS.md` |
| `src/bilinc/wiki/manifest.py` | manifest build, serialise, read and validate |
| `src/bilinc/wiki/fetch.py` | list + history with the single retry layer and the 4-worker pool |
| `src/bilinc/wiki/writer.py` | target inspection, temp build, checks, move, stale delete, permissions |
| `src/bilinc/wiki/export.py` | `export_wiki()` orchestration, `build_files()` |
| `src/bilinc/cli/main.py` (modify) | `wiki` subcommand |
| `tests/wiki_fakes.py` | thread-safe routed fake transport + fake client shared by wiki tests |
| `tests/test_wiki_*.py` | one test file per module, plus integration and CLI |
| `scripts/wiki_smoke.py` | S4 end-to-end smoke against a fake client |

The design named five modules; `fetch.py` and `writer.py` are split out of `export.py` so network and disk code can be built and reviewed in parallel on disjoint files.

## Parallel groups

Task 1 first. Then, on disjoint files, at most two at a time:
- Group A: Tasks 2–3 (`paths.py`) ∥ Task 7 (`links.py`)
- Group B: Tasks 4–6 (`render.py`) ∥ Task 8 (`manifest.py`)
- Group C: Task 9 (`fetch.py`) ∥ Tasks 10–11 (`writer.py`)
- Then sequential: 12 (`export.py`), 13 (CLI), 14 (integration), 15 (smoke).

---

### Task 1: SDK additions (`retry_after`, `read_retry_attempts`)

**Files:**
- Modify: `src/bilinc/client.py` (`BilincCloudError.__init__`, `error_for_response`, `_default_transport`, `CloudClient` fields, `_with_read_retries`)
- Test: `tests/test_wiki_sdk_additions.py`

**Interfaces:**
- Produces: `BilincCloudError.retry_after: float | None`; `error_for_response(status, payload, *, retry_after: str | None = None)`; `CloudClient.read_retry_attempts: int = READ_RETRY_ATTEMPTS` (validated `>= 1` in `__post_init__`, raising `BilincValidationError`); `_with_read_retries` becomes an instance method using `self.read_retry_attempts`.

- [ ] **Step 1: Write the failing tests**

```python
def _http_error(status, headers, body=b'{"error":"rate_limited"}'):
    import email.message, io, urllib.error
    msg = email.message.Message()
    for k, v in headers.items():
        msg[k] = v
    return urllib.error.HTTPError("https://x", status, "err", msg, io.BytesIO(body))

@pytest.mark.parametrize("header,expected", [("7", 7.0), ("0", 0.0), ("2.5", 2.5),
    ("-1", None), ("nan", None), ("inf", None), ("Wed, 21 Oct 2015 07:28:00 GMT", None), (None, None)])
def test_default_transport_parses_retry_after(monkeypatch, header, expected): ...
    # patch urllib.request.urlopen to raise _http_error(429, {"Retry-After": header} if header else {})
    # call client._default_transport(...) ; assert exc.retry_after == expected and type is BilincRateLimitError

def test_default_client_retry_behaviour_unchanged(monkeypatch):
    # G1 condition 1: default CloudClient makes READ_RETRY_ATTEMPTS (3) calls on a retryable 503,
    # sleeps 0.25 then 0.5 (time.sleep patched to record), raises BilincRuntimeUnavailableError
    # with the same message/code/status/retryable as error_for_response builds today, retry_after None.

def test_read_retry_attempts_one_makes_a_single_call(monkeypatch):
    # dataclasses.replace(client, read_retry_attempts=1).history("k") → 1 transport call, no sleep

def test_read_retry_attempts_must_be_positive():
    # CloudClient(api_key="bil_live_x", read_retry_attempts=0) raises BilincValidationError

def test_error_for_response_keeps_positional_signature():
    # error_for_response(429, {"error": "rate_limited"}).retry_after is None
```

- [ ] **Step 2: Run, expect FAIL** (`AttributeError: retry_after` / `TypeError: unexpected keyword read_retry_attempts`).
- [ ] **Step 3: Implement.** Parse with `float(text)`; accept only `math.isfinite(v) and v >= 0`. In `_default_transport`'s `HTTPError` branch pass `retry_after=exc.headers.get("Retry-After") if exc.headers else None`. Keep `_with_read_retries` body identical except the loop bound.
- [ ] **Step 4: Run** `tests/test_wiki_sdk_additions.py tests/test_cloud_memory_review_sdk.py tests/test_cli_error_paths.py` → PASS.
- [ ] **Step 5: Commit** `git add src/bilinc/client.py tests/test_wiki_sdk_additions.py && git commit -m "Expose Retry-After on Cloud errors and make read retries configurable"`

### Task 2: Segment escaping (`paths.escape_segment`)

**Files:** Create `src/bilinc/wiki/__init__.py` (empty docstring for now), `src/bilinc/wiki/paths.py`; Test `tests/test_wiki_paths.py`

**Interfaces:** Produces `escape_segment(segment: str) -> str`, `key_hash(text: str) -> str` (first 6 hex of sha256 of UTF-8).

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.parametrize("raw,escaped", [
    ("release", "release"), ("a/b", "a%2Fb"), ("a\\b", "a%5Cb"), ("50%", "50%25"),
    ("why?", "why%3F"), ('q"x', "q%22x"), ("a<b>c", "a%3Cb%3Ec"), ("a|b*c", "a%7Cb%2Ac"),
    ("nul\x00x", "nul%00x"), ("tab\tx", "tab%09x"), ("del\x7f", "del%7F"),
    (".env", "%2Eenv"), ("..", "%2E%2E"), ("x. ", "x%2E%20"), ("x..", "x%2E%2E"),
    ("CON", "%43ON"), ("com1.txt", "%63om1.txt"), ("lpt9", "%6Cpt9"), ("CONSOLE", "CONSOLE"),
    ("", "_"), ("ünïcode", "ünïcode"),
])
def test_escape_segment(raw, escaped): assert escape_segment(raw) == escaped

def test_escape_is_injective_on_tricky_pairs():
    assert escape_segment("%2F") != escape_segment("/")

def test_key_hash_is_sha256_prefix():
    assert key_hash("index") == hashlib.sha256(b"index").hexdigest()[:6]
```

Trailing rule: the whole trailing run of spaces and dots is escaped, so `"x.."` → `"x%2E%2E"`.

- [ ] **Step 2: Run, expect FAIL** (ImportError).
- [ ] **Step 3: Implement** in the spec's order: `%` → `%25`; each char in `/\?*|"<>:` or `ord < 0x20` or `== 0x7f` → `%XX` per UTF-8 byte (uppercase hex); leading `.` → `%2E`; trailing run of `[ .]` → escaped; Windows device stem (`re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", s, re.I)`) → first char as `%XX`; empty → `_`.
- [ ] **Step 4: PASS.** **Step 5: Commit** `"Add wiki key segment escaping"`.

### Task 3: Key → path map (`paths.build_paths`)

**Files:** Modify `src/bilinc/wiki/paths.py`; Test `tests/test_wiki_paths.py`

**Interfaces:** Produces `build_paths(keys: Iterable[str]) -> dict[str, str]` mapping each key to a POSIX relative path ending `.md`; `MAX_NAME_BYTES = 120`; `RESERVED_STEMS = frozenset({"index", "_index", "agents"})`; raises `ValueError` on an unresolvable collision.

- [ ] **Step 1: Failing tests**

```python
def test_nested_and_root_keys():
    assert build_paths(["project:bilinc:release", "solo"]) == {
        "project:bilinc:release": "project/bilinc/release.md", "solo": "solo.md"}

def test_reserved_names_get_suffix_at_any_level():
    p = build_paths(["index", "a:_index", "b:AGENTS", "c:indexes"])
    assert p["index"] == f"index~{key_hash('index')}.md"
    assert p["a:_index"] == f"a/_index~{key_hash('a:_index')}.md"
    assert p["b:AGENTS"] == f"b/AGENTS~{key_hash('b:AGENTS')}.md"
    assert p["c:indexes"] == "c/indexes.md"

def test_case_collision_suffixes_both():
    p = build_paths(["Team:x", "team:y", "Note", "note"])
    assert p["Note"] == f"Note~{key_hash('Note')}.md" and p["note"] == f"note~{key_hash('note')}.md"
    # folders Team/ and team/ collide: each folder gets the hash of its key prefix
    assert p["Team:x"] == f"Team~{key_hash('Team')}/x.md"
    assert p["team:y"] == f"team~{key_hash('team')}/y.md"

def test_nfc_collision():  # "é" precomposed vs "é"
    p = build_paths(["café", "café"]); assert len(set(p.values())) == 2
    assert all("~" in v for v in p.values())

def test_folder_page_name_clash():  # folder "a.md" (from key "a.md:b") vs page "a.md" (key "a")
    p = build_paths(["a", "a.md:b"]); assert p["a"] != p["a.md:b"].split("/")[0]
    assert len({p["a"].casefold(), p["a.md:b"].split("/")[0].casefold()}) == 2

def test_byte_cap_with_multibyte_never_splits():
    key = "ş" * 200
    path = build_paths([key])[key]
    assert len(path.encode()) <= 120 and path.endswith(f"~{key_hash(key)}.md")
    path.encode().decode()  # valid UTF-8

def test_byte_cap_never_splits_escape():
    key = "%" * 60  # escapes to %25 x60 = 180 bytes
    name = build_paths([key])[key]
    assert re.fullmatch(r"(%25)*~[0-9a-f]{6}\.md", name)

def test_literal_suffix_lookalike_still_collides():
    k1 = "x"; k2 = f"x~{key_hash('x')}"
    p = build_paths(["index", k1, k2]); assert len(set(p.values())) == 3

def test_empty_segments():
    assert build_paths(["a::b"])["a::b"] == "a/_/b.md"

def test_output_independent_of_input_order():
    keys = ["Team:x", "team:y", "index", "a", "a.md:b"]
    assert build_paths(keys) == build_paths(list(reversed(keys)))
```

- [ ] **Step 2: FAIL.** **Step 3: Implement:** build a tree of escaped names; per parent, compute final names in the spec's order (escape → reserved suffix → cap → collision pass on `unicodedata.normalize("NFC", name).casefold()` over folders and `stem.md` pages together, re-capping with the suffix kept); iterate in sorted order; raise `ValueError` if a duplicate remains. Folder hash input is the raw key prefix joined with `:`.
- [ ] **Step 4: PASS** (`tests/test_wiki_paths.py`). **Step 5: Commit** `"Map wiki keys to collision-free page paths"`.

### Task 4: Render primitives (`render.py` helpers)

**Files:** Create `src/bilinc/wiki/render.py`; Test `tests/test_wiki_render.py`

**Interfaces:** Produces `fence(content: str, lang: str) -> str`; `md_inline(text: str) -> str`; `yaml_scalar(value: Any) -> str`; `fold_lines(text: str) -> str`; `relative_link(from_path: str, to_path: str) -> str` (percent-encoded, `quote(rel, safe="/")`); `value_block(value: Any) -> str`; `clip(text: str, limit: int) -> str`.

- [ ] **Step 1: Failing tests**

```python
def test_fence_outgrows_backtick_runs():
    out = fence("a ``````` b", "text")
    assert out.startswith("````````text\n") and out.rstrip().endswith("````````")
def test_fence_minimum_three(): assert fence("x", "json").startswith("```json\n")
def test_yaml_scalar_is_json_and_escapes_line_separators():
    assert yaml_scalar('a"\n---') == '"a\\"\\n---"'
    assert yaml_scalar("x y\u0085z ") == '"x\\u2028y\\u0085z\\u2029"'
    assert yaml_scalar(None) == "null"
def test_md_inline_escapes_structure_but_not_colon():
    assert md_inline("project:bilinc:release") == "project:bilinc:release"
    assert md_inline("[x](javascript:y)") == "\\[x\\](javascript:y)"
    assert md_inline("# h") == "\\# h" and md_inline("a|b") == "a\\|b"
    assert md_inline("1. x") == "1\\. x" and md_inline("- x") == "\\- x"
    assert md_inline("a\r\nb c") == "a  b c"
def test_value_block_string(): assert value_block("hi") == "```text\nhi\n```\n"
def test_value_block_object_lists_fields_in_a_fence():
    out = value_block({"name": "x", "deep": {"a": [1, 2]}, "long": "y" * 200})
    assert out.startswith("```text\n- name: \"x\"\n- deep: {\"a\":[1,2]}\n- long: ")
    assert "…" in out and "```json\n{\n  \"name\": \"x\"," in out
def test_value_block_array_and_scalars_json_only():
    assert value_block([1]) == "```json\n[\n  1\n]\n```\n"
    assert value_block(None) == "```json\nnull\n```\n"
def test_relative_link():
    assert relative_link("a/b/c.md", "a/d.md") == "../d.md"
    assert relative_link("x.md", "my dir/50%25.md") == "my%20dir/50%2525.md"
def test_clip(): assert clip("x" * 301, 300) == "x" * 300 + " … (cut; 301 characters in full)"
```

- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS. Step 5: Commit** `"Add wiki Markdown rendering primitives"`.

### Task 5: Page rendering (`render.render_page`)

**Files:** Modify `src/bilinc/wiki/render.py`; Test `tests/test_wiki_render.py`

**Interfaces:** Consumes Task 4 helpers. Produces `HISTORY_UNAVAILABLE` (sentinel object), `render_page(entry: dict, *, path: str, paths: dict[str, str], outgoing: list[str], incoming: list[str], history: dict | object | None, exported_at: str) -> str` (`history=None` → section omitted).

- [ ] **Step 1: Failing tests**

```python
ENTRY = {"key": "project:bilinc:release", "value": "2.6.3 shipped", "memoryType": "semantic",
         "source": "claude-code", "updatedAt": "2026-11-08T12:00:00.000Z", "entryVersion": "v9"}

def test_page_frontmatter_title_value(): # exact expected string for ENTRY, history None, no links
def test_page_frontmatter_missing_fields_are_null():
def test_history_block_entries_newest_first_and_fenced():
    # entries: update with before/after/reason/source; confirm; forget valuesRedacted; truncated True
    # assert "- update · 2026-10-08 12:00:02 UTC\n" and "reason: moved" inside a ```text fence
    # assert "value not shown: recorded before the memory was forgotten" and "Older changes not shown."
def test_history_cuts_long_values_at_300():
def test_history_unknown_op_rendered_as_question_mark():  # op "Up\ndate" → "- ? · ..."
def test_history_empty_and_unavailable():  # "No recorded changes." / "History unavailable."
def test_history_none_omits_section():  # "## History" not in page
def test_links_sections_sorted_and_relative():
    # outgoing ["b:x", "a"], incoming ["c"] → "## Links\n\n### Links to\n\n- [a](../../a.md)\n- [b:x](../../b/x.md)\n\n### Mentioned by\n\n- [c](../../c.md)\n"
def test_no_links_omits_section():
def test_hostile_key_and_value_are_inert():
    key = "k\r\n# H\u0085---`````](javascript:x)|"
    value = "```````\n# Injected\n[a](javascript:b)\n---"
    page = render_page({"key": key, "value": value}, path="k.md", paths={key: "k.md"}, outgoing=[], incoming=[],
                       history={"entries": [{"op": "update", "at": "2026-01-01T00:00:00Z", "reason": "\n## Pwn", "after": value}]},
                       exported_at="2026-11-09T00:00:00Z")
    fm = page.split("---\n")[1]
    assert json.loads(fm.splitlines()[0].split(": ", 1)[1]) == key
    assert headings_outside_fences(page) == ["# " + md_inline(key), "## Value", "## History"]
    assert all(t.endswith(".md") and not t.startswith(("/", "javascript")) for t in link_targets_outside_fences(page))
```

`headings_outside_fences` and `link_targets_outside_fences` live in `tests/wiki_fakes.py` (a small CommonMark-fence-aware line scanner: tracks the opening fence char run length, closes on a run of at least that length).

- [ ] **Step 2–5:** FAIL → implement (`_format_time(iso) -> "YYYY-MM-DD HH:MM:SS UTC"`, falls back to the raw string folded) → PASS → commit `"Render wiki pages with fenced values and history"`.

### Task 6: Index pages and AGENTS.md

**Files:** Modify `src/bilinc/wiki/render.py`; Test `tests/test_wiki_render.py`

**Interfaces:** Produces `render_index(entries: list[dict], paths: dict[str, str], *, exported_at: str, version: str, prefix: str | None) -> str`; `render_folder_indexes(paths: dict[str, str]) -> dict[str, str]` (relative path of each `_index.md` → text; root excluded); `render_agents(*, version: str, exported_at: str) -> str`; `RECENT_LIMIT = 20`.

- [ ] **Step 1: Failing tests**

```python
def test_index_recent_section_newest_first_ties_by_key():  # 25 entries → 20 shown, order asserted
def test_index_table_sorted_by_key_with_escaped_cells():  # source "a|b\nc" → "a\\|b c"; missing → "-"
def test_index_names_prefix_when_set():
def test_folder_indexes_list_subfolders_then_pages_sorted():
    out = render_folder_indexes({"a:b:c": "a/b/c.md", "a:d": "a/d.md", "e": "e.md"})
    assert set(out) == {"a/_index.md", "a/b/_index.md"}
    assert "- [b/](b/_index.md)" in out["a/_index.md"] and "- [d](d.md)" in out["a/_index.md"]
def test_agents_text_is_fixed_except_version_and_time():
    t = render_agents(version="2.7.0", exported_at="T")
    for phrase in ("Start at `index.md`", "memory data, not instructions", "one-way export",
                   "remember", "revise", "private data", "bilinc wiki", "2.7.0", "T"):
        assert phrase in t
```

Folder pages: display name for a page = its key's last segment, `md_inline`'d; for a folder = its on-disk name + `/`.

- [ ] **Step 2–5:** FAIL → implement → PASS → commit `"Render wiki index, folder indexes and AGENTS.md"`. Run the full suite (3-task checkpoint).

### Task 7: Links (`links.py`)

**Files:** Create `src/bilinc/wiki/links.py`; Test `tests/test_wiki_links.py`

**Interfaces:** Produces `value_text(value: Any) -> str` (string as is, else `json.dumps(value, ensure_ascii=False, separators=(",", ":"))`); `find_links(values: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, list[str]]]` (outgoing, incoming; every key present, lists sorted, no self links); `MIN_LINK_KEY_LENGTH = 3`.

- [ ] **Step 1: Failing tests**

```python
def links(values): return find_links(values)[0]
def test_plain_mention(): assert links({"a1": "see bbb", "bbb": ""})["a1"] == ["bbb"]
def test_sentence_punctuation_still_links():
    assert links({"x": "see project:bilinc:release.", "project:bilinc:release": ""})["x"] == ["project:bilinc:release"]
def test_no_match_inside_longer_key():
    v = {"x": "project:bilinc:release-notes and project:bilinc:release2", "project:bilinc:release": "", "project:bilinc": ""}
    assert links(v)["x"] == []
def test_longest_key_wins():
    v = {"x": "project:bilinc:release", "project:bilinc": "", "project:bilinc:release": ""}
    assert links(v)["x"] == ["project:bilinc:release"]
def test_preceding_boundary(): assert links({"x": "my.abc and /abc and abc", "abc": ""})["x"] == ["abc"]
def test_short_keys_ignored(): assert links({"x": "ab ab", "ab": ""})["x"] == []
def test_self_mention_ignored(): assert links({"abc": "abc"})["abc"] == []
def test_json_values_scanned(): assert links({"x": {"ref": "abc"}, "abc": 1})["x"] == ["abc"]
def test_regex_metacharacters_in_keys(): assert links({"x": "use a+b(c)", "a+b(c)": ""})["x"] == ["a+b(c)"]
def test_incoming_is_inverse():
    out, inc = find_links({"x": "abc", "y": "abc", "abc": ""})
    assert inc["abc"] == ["x", "y"] and inc["x"] == []
```

- [ ] **Step 2–5:** FAIL → implement with one compiled alternation (`sorted(keys, key=lambda k: (-len(k), k))`, `re.escape`), lookbehind `(?<![A-Za-z0-9_:.\-/])`, lookahead `(?![A-Za-z0-9_:/])(?![.\-][A-Za-z0-9])`; `finditer` → PASS → commit `"Find mentions between wiki pages"`.

### Task 8: Manifest (`manifest.py`)

**Files:** Create `src/bilinc/wiki/manifest.py`; Test `tests/test_wiki_manifest.py`

**Interfaces:** Produces `MANIFEST_NAME = ".bilinc-wiki.json"`, `TMP_NAME = ".bilinc-wiki.tmp"`, `FORMAT = 1`, `TOOL = "bilinc wiki"`; `class ManifestError(ValueError)`; `validate_rel_path(path: str) -> str`; `build_manifest(*, version: str, base_url: str, prefix: str | None, history: int, exported_at: str, complete: bool, files: Iterable[str], keys: dict[str, dict]) -> dict`; `dumps_manifest(manifest: dict) -> str` (`json.dumps(indent=2, ensure_ascii=False, sort_keys=True) + "\n"`); `read_manifest(directory: Path) -> dict | None` (None when absent; `ManifestError` when not a regular file / symlink / unparsable / wrong `tool` or `format` / bad paths).

- [ ] **Step 1: Failing tests**

```python
def test_round_trip(tmp_path): # build → write → read equals, files sorted
@pytest.mark.parametrize("bad", ["../x", "/etc/x", "a//b", "a\\..\\b", "C:x", ".", "", "a/../b",
                                  ".obsidian/app.json", ".bilinc-wiki.json", "a/.hidden", "a/", "x\x00y"])
def test_invalid_paths_rejected(bad): with pytest.raises(ManifestError): validate_rel_path(bad)
def test_read_manifest_absent_is_none(tmp_path):
def test_read_manifest_symlink_rejected(tmp_path):
def test_read_manifest_garbage_rejected(tmp_path):  # "{", "[]", {"tool": "other"}, {"format": 2}
def test_read_manifest_bad_file_entry_rejected(tmp_path):
def test_dumps_is_deterministic(): # same dict built from differently ordered inputs → same text
```

- [ ] **Step 2–5:** FAIL → implement → PASS → commit `"Add the wiki manifest"`.

### Task 9: Fetching (`fetch.py`)

**Files:** Create `src/bilinc/wiki/fetch.py`, `tests/wiki_fakes.py` (if not already created by Task 5); Test `tests/test_wiki_fetch.py`

**Interfaces:** Consumes Task 1. Produces `class HistoryAbort(Exception)` (wraps the fatal error); `fetch_entries(client, *, prefix: str | None) -> list[dict]` (`iter_memories(prefix=prefix, values="full")`, sorted by key, duplicate keys → `BilincCloudError(code="invalid_response")`); `fetch_histories(client, keys: list[str], *, limit: int, sleep: Callable[[float], None], max_workers: int = 4, progress: Callable[[int, int], None] | None = None, stop: threading.Event | None = None) -> dict[str, dict | object]` (value is the history payload or `render.HISTORY_UNAVAILABLE`); `FATAL_ERRORS = (BilincAuthError, BilincEntitlementError, BilincPaymentRequiredError, BilincApiKeyRequired)`; `MAX_RETRIES = 3`, `RETRY_AFTER_CAP = 60.0`, `BACKOFF = (1.0, 2.0, 4.0)`.

`tests/wiki_fakes.py` provides `RoutedTransport(list_pages: list[dict], history: dict[str, list[dict | Exception]], default_history=None)` — a lock-protected transport that answers `/api/cloud/memory/list` by the request's `cursor` (None → page 0, `"c1"` → page 1 …) and `/api/cloud/memory/history` by the body's `key`, popping the next scripted response for that key (last one repeats); it records calls per key. Also `make_client(transport) -> CloudClient`.

- [ ] **Step 1: Failing tests**

```python
def test_fetch_entries_sorted_and_full_values():  # body values == "full", prefix forwarded
def test_history_uses_single_retry_layer(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: pytest.fail("real sleep"))
    t = RoutedTransport([], {"k": [rate_limited(retry_after=2)] * 3 + [{"key": "k", "entries": []}]})
    sleeps = []
    out = fetch_histories(make_client(t), ["k"], limit=5, sleep=sleeps.append)
    assert t.history_calls("k") == 4 and sleeps == [2, 2, 2] and out["k"]["entries"] == []
def test_retry_after_is_capped(): # retry_after=600 → sleeps [60, ...]
def test_fallback_backoff_without_retry_after(): # 503 x4 → sleeps [1, 2, 4], HISTORY_UNAVAILABLE, 4 calls
def test_non_retryable_error_marks_unavailable_without_retry():  # 404 → 1 call
def test_auth_error_aborts(): # BilincAuthError on one key → raises HistoryAbort
def test_at_most_four_in_flight():  # transport blocks on a barrier and records max concurrency <= 4 with 12 keys
def test_result_independent_of_completion_order():  # per-key Events release in reverse order; dict equal to sequential run
def test_progress_reports_each_key():  # progress called with (n, total) up to (len, len)
def test_stop_event_cancels_pending():  # set stop during first sleep → KeyboardInterrupt-equivalent `HistoryCancelled`
```

Add to Interfaces: `class HistoryCancelled(Exception)`, raised when `stop` is set; `export_wiki` maps a `KeyboardInterrupt` in the main thread to `stop.set()` + `shutdown(wait=False, cancel_futures=True)` and re-raises `KeyboardInterrupt`.

- [ ] **Step 2–5:** FAIL → implement (history client = `dataclasses.replace(client, read_retry_attempts=1)`; the wait uses `stop.wait(delay)` when a `stop` event is given, else `sleep(delay)`) → PASS → commit `"Fetch wiki pages and history with one bounded retry layer"`.

### Task 10: Target inspection (`writer.inspect_target`)

**Files:** Create `src/bilinc/wiki/writer.py`; Test `tests/test_wiki_writer.py`

**Interfaces:** Consumes Task 8. Produces `class WikiExportError(Exception)`, `class WikiRefused(WikiExportError)`; `IGNORED_ENTRIES = frozenset({".obsidian", ".trash", ".DS_Store"})`; `inspect_target(target: Path, *, base_url: str, prefix: str | None) -> dict | None` (previous manifest or None; raises `WikiRefused` with a message naming the reason).

- [ ] **Step 1: Failing tests**

```python
def test_missing_dir_ok_parent_required(tmp_path):  # tmp/new → None; tmp/no/such/new → WikiRefused
def test_empty_dir_ok(tmp_path):
def test_obsidian_only_dir_counts_as_empty(tmp_path):  # .obsidian/app.json, .trash/, .DS_Store
def test_non_empty_without_marker_refused(tmp_path):  # notes.md → WikiRefused("not a Bilinc wiki folder")
def test_stale_tmp_without_marker_refused_and_named(tmp_path):  # message contains ".bilinc-wiki.tmp"
def test_target_symlink_refused(tmp_path):
def test_target_is_file_refused(tmp_path):
def test_prefix_or_base_url_change_refused(tmp_path):  # message names both values
def test_valid_manifest_returned(tmp_path):
```

- [ ] **Step 2–5:** FAIL → implement → PASS → commit `"Guard the wiki target folder"`.

### Task 11: Writing the tree (`writer.write_tree`)

**Files:** Modify `src/bilinc/wiki/writer.py`; Test `tests/test_wiki_writer.py`

**Interfaces:** Produces `@dataclass WriteResult: written: int; removed: list[str]; skipped: list[str]`; `write_tree(target: Path, files: dict[str, str], *, previous: dict | None, manifest_for: Callable[[bool, list[str]], dict]) -> WriteResult` (`manifest_for(complete, files)` returns the manifest dict; the writer calls it for the interim and the final manifest).

Steps inside `write_tree`, in order: create `target` 0700 if missing; remove a stale `TMP_NAME` only if it is a real directory (not a symlink, else `WikiRefused`) and `previous` is not None; build every file in the temp folder (`os.open(..., O_WRONLY|O_CREAT|O_EXCL, 0o600)`, dirs `0o700`); pre-move checks (spec step 6) with `os.lstat`; interim manifest (`complete=False`, union of old and new `files`) via temp + `os.replace`; `os.replace` each file (creating real folders 0700, `chmod 0o600` on result); stale deletes with the lstat parent walk; `os.rmdir` emptied folders deepest first (ignore `OSError`); final manifest; `shutil.rmtree(tmp)`; `os.chmod(target, 0o700)`. Any `OSError` before the interim manifest → remove temp, re-raise as `WikiExportError`.

- [ ] **Step 1: Failing tests**

```python
def test_first_write_creates_files_and_manifest_with_permissions(tmp_path):  # 0700 dirs, 0600 files, manifest complete
def test_rewrite_removes_stale_and_keeps_user_files(tmp_path):  # user notes.md + .obsidian untouched (bytes and mtime)
def test_tightens_world_readable_files(tmp_path):  # previous page chmod 0644 → 0600 after run
def test_user_entry_at_needed_path_refused_before_move(tmp_path):  # file and dir variants; tree unchanged; tmp removed
def test_symlinked_folder_component_refused(tmp_path):
def test_owned_page_replaced_by_symlink_not_followed(tmp_path):  # outside target unchanged; page is now a regular file
def test_stale_delete_never_follows_symlinked_parent(tmp_path):  # outside file survives; reported in skipped
def test_tmp_symlink_refused(tmp_path):
def test_build_error_leaves_previous_intact(tmp_path, monkeypatch):  # os.open fails on 2nd file → WikiExportError; snapshot equal; no tmp
def test_crash_mid_move_then_rerun_recovers(tmp_path, monkeypatch):
    # os.replace raises on 3rd call → exception; manifest complete False; every non-user file on disk listed in files;
    # user file identical; rerun (unpatched) → complete True, no orphan files
```

`snapshot(tree) -> dict[path, (bytes, mode)]` helper in `tests/wiki_fakes.py`.

- [ ] **Step 2–5:** FAIL → implement → PASS → commit `"Write the wiki atomically with owner-only permissions"`. Full suite (checkpoint).

### Task 12: Orchestration (`export.py`) and determinism

**Files:** Create `src/bilinc/wiki/export.py`; Modify `src/bilinc/wiki/__init__.py`; Test `tests/test_wiki_export.py`

**Interfaces:** Consumes Tasks 3–11. Produces `@dataclass ExportResult: pages: int; written: int; removed: list[str]; skipped: list[str]; history_unavailable: list[str]`; `build_files(entries: list[dict], histories: dict | None, *, exported_at: str, version: str, prefix: str | None) -> tuple[dict[str, str], dict[str, str]]` (files, key→path); `export_wiki(client, target: str | os.PathLike, *, history: int = 5, prefix: str | None = None, clock: Callable[[], datetime] | None = None, sleep: Callable[[float], None] | None = None, progress: Callable[[int, int], None] | None = None) -> ExportResult`. `exported_at` = `clock().astimezone(utc)` formatted `%Y-%m-%dT%H:%M:%SZ`. Validates `0 <= history <= MAX_HISTORY_LIMIT` (`ValueError`).

- [ ] **Step 1: Failing tests**

```python
def test_list_fields_from_public_route_shape(tmp_path):
    # fixture mirrors publicList(): key, memoryType, importance, source, createdAt, updatedAt, entryVersion, value
    # assert page frontmatter memory_type/source/updated_at and manifest keys[k] == {"path", "entry_version", "updated_at"}
def test_refusal_writes_nothing(tmp_path):  # non-empty folder w/o marker → WikiRefused, client never called for history
def test_list_failure_leaves_previous_wiki_identical(tmp_path):  # run 1 ok; run 2 page 2 raises → snapshot equal
def test_history_auth_error_leaves_previous_wiki_identical(tmp_path):
def test_history_zero_skips_calls_and_section(tmp_path):
def test_history_unavailable_listed(tmp_path):
def test_determinism_in_process(tmp_path):  # two runs, two dirs, clock differs → equal after normalising exported_at
def test_determinism_across_processes(tmp_path):
    # subprocess.run([sys.executable, "-c", SCRIPT, out_dir], env={PYTHONHASHSEED: "1"/"2", TZ: "UTC"/"Asia/Tokyo", PYTHONPATH: src})
    # SCRIPT builds the fake from tests/wiki_fakes.py with shuffled entries (seeded differently) and reverse history completion
    # assert normalised snapshots equal
def test_user_files_untouched_across_runs(tmp_path):
```

- [ ] **Step 2–5:** FAIL → implement → PASS → commit `"Orchestrate the wiki export"`.

### Task 13: CLI (`bilinc wiki`)

**Files:** Modify `src/bilinc/cli/main.py`; Test `tests/test_wiki_cli.py`

**Interfaces:** Consumes `export_wiki`, `WikiExportError`, `WikiRefused`, `HISTORY_UNAVAILABLE`.

Parser: `wiki = sub.add_parser("wiki", help="Write every stored memory as Obsidian-compatible Markdown pages in a folder")`; `dir`; `--history` (`type=_history_count` accepting 0–100, default 5); `--prefix`. Dispatch: progress callback only `if sys.stderr.isatty()` (writes `\rhistory n/total` and a final newline); on success print to **stdout** one summary line `Wrote N pages to DIR (removed M stale files)`; for unavailable history print `warning: history unavailable for K keys: a, b, …` to stderr; `skipped` deletes are named on stderr; `WikiRefused`/`WikiExportError` → `bilinc: error: …` exit 1; `KeyboardInterrupt` → exit 130.

- [ ] **Step 1: Failing tests**

```python
def test_wiki_help_renders(capsys):  # SystemExit 0, "--history" and "--prefix" in out
@pytest.mark.parametrize("bad", ["101", "-1", "x"])
def test_wiki_history_bounds(bad, capsys):  # SystemExit 2
def test_wiki_success_summary_on_stdout_only(cli, tmp_path, capsys):  # stdout one line; stderr empty (not a TTY)
def test_wiki_history_failure_exit_zero_with_warning(cli, tmp_path, capsys):  # key named on stderr, exit 0
def test_wiki_refusal_exit_one(cli, tmp_path, capsys):
def test_wiki_list_failure_exit_one(cli, tmp_path, capsys):
def test_wiki_progress_only_on_tty(cli, tmp_path, capsys, monkeypatch):  # isatty True → "\rhistory" on stderr; stdout unchanged
def test_existing_commands_unchanged():  # build_parser() subcommand set == previous set | {"wiki"}
```

`cli` fixture follows `tests/test_cloud_memory_review_sdk.py`: monkeypatch `cli_main.CloudClient` with a fake built on `RoutedTransport`.

- [ ] **Step 2–5:** FAIL → implement → PASS → commit `"Add the bilinc wiki command"`.

### Task 14: Integration through the real SDK client and fake transport

**Files:** Test `tests/test_wiki_integration.py` (no source changes expected)

- [ ] **Step 1: Tests** (real `CloudClient` + `RoutedTransport`, `time.sleep` patched to fail):

```python
def test_three_list_pages_all_exported(tmp_path):  # 250 keys over cursors None/c1/c2 → 250 pages; list body limit 100, values full
def test_rate_limit_then_success(tmp_path):  # one key 429(retry_after=1) x2 then ok → page has history, sleeps [1, 1]
def test_partial_history_failure(tmp_path):  # one key 503 forever → "History unavailable." on its page, others fine, result lists it
def test_auth_error_on_list_writes_nothing(tmp_path):  # dir does not exist afterwards
def test_response_too_large_shrinks_pages(tmp_path):  # page 0 at limit 100 raises invalid_request/response_too_large → retried at 10
```

- [ ] **Step 2:** Run; fix any defect found in the module that owns it (with its own failing unit test first). **Step 3: Commit** `"Cover the wiki export end to end through the SDK"`. Full suite (checkpoint).

### Task 15: Smoke script (S4)

**Files:** Create `scripts/wiki_smoke.py`

Builds a fake client with ~30 synthetic keys (nested, `Team:x`/`team:y` case collision, `index`, `a:_index`, `b:AGENTS`, JSON object and array values, a value with seven backticks, a hostile key, one key whose history always fails), runs `export_wiki` twice into a temp folder (clock differs), adds `notes.md` between runs, and prints: page count, unavailable keys, `identical_except_exported_at: True`, `user_file_survived: True`, `refused_without_marker: True` (third run into a separate non-empty folder), `modes_ok: True` (all dirs 0700, files 0600). Exit 1 if any check is false. No network; no API key.

- [ ] Run `PYTHONPATH=src ~/work/bilinc-dev/.venv-wiki/bin/python scripts/wiki_smoke.py`; paste output into STATE.md; commit `"Add a local wiki export smoke script"`.

### After the plan (not tasks here)

- S5 reviews, S6 CHANGELOG (`Unreleased`, "Obsidian-compatible Markdown"), patches and bundle.
- Owner-only (hard stops): push + PR, version bump to 2.7.0, PyPI, MCP registry unchanged, GitHub release, site `/docs/wiki`, manual Obsidian acceptance, demo.
