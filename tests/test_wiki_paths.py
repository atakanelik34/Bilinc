"""Tests for wiki key -> page path mapping (``bilinc.wiki.paths``)."""

from __future__ import annotations

import hashlib
import re
import unicodedata

import pytest

from bilinc.wiki.paths import (
    MAX_NAME_BYTES,
    RESERVED_STEMS,
    build_paths,
    escape_segment,
    key_hash,
)


@pytest.mark.parametrize(
    "raw,escaped",
    [
        ("release", "release"),
        ("a/b", "a%2Fb"),
        ("a\\b", "a%5Cb"),
        ("50%", "50%25"),
        ("why?", "why%3F"),
        ('q"x', "q%22x"),
        ("a<b>c", "a%3Cb%3Ec"),
        ("a|b*c", "a%7Cb%2Ac"),
        ("a:b", "a%3Ab"),
        ("nul\x00x", "nul%00x"),
        ("tab\tx", "tab%09x"),
        ("nl\nx", "nl%0Ax"),
        ("del\x7f", "del%7F"),
        (".env", "%2Eenv"),
        (".", "%2E"),
        ("..", "%2E%2E"),
        ("x. ", "x%2E%20"),
        ("x..", "x%2E%2E"),
        ("x  ", "x%20%20"),
        ("a.b", "a.b"),
        (" lead", " lead"),
        ("CON", "%43ON"),
        ("con", "%63on"),
        ("Aux", "%41ux"),
        ("nul", "%6Eul"),
        ("PRN.md", "%50RN.md"),
        ("com1.txt", "%63om1.txt"),
        ("lpt9", "%6Cpt9"),
        ("COM0", "COM0"),
        ("com\u00b9", "%63om\u00b9"),
        ("CONIN$", "%43ONIN$"),
        ("CONSOLE", "CONSOLE"),
        ("", "_"),
        ("_", "_"),
        ("ünïcode", "ünïcode"),
        ("%2F", "%252F"),
    ],
)
def test_escape_segment(raw: str, escaped: str) -> None:
    assert escape_segment(raw) == escaped


def test_escape_is_injective_on_tricky_pairs() -> None:
    assert escape_segment("%2F") != escape_segment("/")
    assert escape_segment("%43ON") != escape_segment("CON")
    assert escape_segment("%2Eenv") != escape_segment(".env")


def test_escape_uses_utf8_bytes_for_escaped_characters() -> None:
    # U+0085 is not a C0 control, so it stays; only C0 and DEL are escaped.
    assert escape_segment("\x1f") == "%1F"
    assert escape_segment("\x85") == "\x85"


def test_key_hash_is_sha256_prefix() -> None:
    assert key_hash("index") == hashlib.sha256(b"index").hexdigest()[:6]
    assert key_hash("ş") == hashlib.sha256("ş".encode()).hexdigest()[:6]


def _names(path: str) -> list[str]:
    return path.split("/")


def test_constants() -> None:
    assert MAX_NAME_BYTES == 120
    assert RESERVED_STEMS == frozenset({"index", "_index", "agents"})


def test_nested_and_root_keys() -> None:
    assert build_paths(["project:bilinc:release", "solo"]) == {
        "project:bilinc:release": "project/bilinc/release.md",
        "solo": "solo.md",
    }


def test_design_examples() -> None:
    p = build_paths(["a/b", ".env", "index"])
    assert p == {
        "a/b": "a%2Fb.md",
        ".env": "%2Eenv.md",
        "index": f"index~{key_hash('index')}.md",
    }


def test_escaping_applies_to_every_segment() -> None:
    assert build_paths(["..:CON:x?"])["..:CON:x?"] == "%2E%2E/%43ON/x%3F.md"


def test_reserved_names_get_suffix_at_any_level() -> None:
    p = build_paths(["index", "a:_index", "b:AGENTS", "c:indexes", "d:Index"])
    assert p["index"] == f"index~{key_hash('index')}.md"
    assert p["a:_index"] == f"a/_index~{key_hash('a:_index')}.md"
    assert p["b:AGENTS"] == f"b/AGENTS~{key_hash('b:AGENTS')}.md"
    assert p["c:indexes"] == "c/indexes.md"
    assert p["d:Index"] == f"d/Index~{key_hash('d:Index')}.md"


def test_folders_named_like_generated_files_get_suffix() -> None:
    # Deviation from the design (which reserves page stems only): a folder
    # called ``index.md`` / ``_index.md`` / ``AGENTS.md`` would sit exactly at
    # the path of a file the export writes itself.
    p = build_paths(["index.md:x", "a:_index.md:y", "AGENTS.md:z"])
    assert p["index.md:x"] == f"index.md~{key_hash('index.md')}/x.md"
    assert p["a:_index.md:y"] == f"a/_index.md~{key_hash('a:_index.md')}/y.md"
    assert p["AGENTS.md:z"] == f"AGENTS.md~{key_hash('AGENTS.md')}/z.md"


def test_folder_named_index_without_extension_is_fine() -> None:
    assert build_paths(["index:x"])["index:x"] == "index/x.md"


def test_case_collision_suffixes_both() -> None:
    p = build_paths(["Team:x", "team:y", "Note", "note"])
    assert p["Note"] == f"Note~{key_hash('Note')}.md"
    assert p["note"] == f"note~{key_hash('note')}.md"
    # folders Team/ and team/ collide: each folder gets the hash of its key prefix
    assert p["Team:x"] == f"Team~{key_hash('Team')}/x.md"
    assert p["team:y"] == f"team~{key_hash('team')}/y.md"


def test_no_suffix_without_collision() -> None:
    p = build_paths(["Team:x", "Team:y", "other"])
    assert p == {"Team:x": "Team/x.md", "Team:y": "Team/y.md", "other": "other.md"}


def test_nfc_collision() -> None:
    composed, decomposed = "caf\u00e9", "cafe\u0301"
    p = build_paths([composed, decomposed])
    assert p[composed] == f"{composed}~{key_hash(composed)}.md"
    assert p[decomposed] == f"{decomposed}~{key_hash(decomposed)}.md"


def test_folder_page_name_clash() -> None:
    # folder "a.md" (from key "a.md:b") vs page "a.md" (key "a")
    p = build_paths(["a", "a.md:b"])
    assert p["a"] == f"a~{key_hash('a')}.md"
    assert p["a.md:b"] == f"a.md~{key_hash('a.md')}/b.md"


def test_same_folder_from_many_keys_is_one_folder() -> None:
    p = build_paths(["x:a", "x:b", "x:c:d"])
    assert {path.split("/")[0] for path in p.values()} == {"x"}


def test_empty_segments() -> None:
    assert build_paths(["a::b"])["a::b"] == "a/_/b.md"


def test_empty_segment_folder_merges_with_underscore_folder() -> None:
    p = build_paths(["a::b", "a:_:c"])
    assert p == {"a::b": "a/_/b.md", "a:_:c": "a/_/c.md"}


def test_empty_and_underscore_pages_collide_and_split() -> None:
    p = build_paths(["a:", "a:_"])
    assert p["a:"] == f"a/_~{key_hash('a:')}.md"
    assert p["a:_"] == f"a/_~{key_hash('a:_')}.md"


def test_byte_cap_with_multibyte_never_splits() -> None:
    key = "\u015f" * 200
    path = build_paths([key])[key]
    assert len(path.encode("utf-8")) <= MAX_NAME_BYTES
    assert path.endswith(f"~{key_hash(key)}.md")
    assert set(path[: -len(f"~{key_hash(key)}.md")]) == {"\u015f"}
    # 120 - len("~hhhhhh.md") = 110 bytes -> 55 two-byte characters
    assert path == "\u015f" * 55 + f"~{key_hash(key)}.md"


def test_byte_cap_exact_limit_not_cut() -> None:
    key = "a" * (MAX_NAME_BYTES - 3)
    assert build_paths([key])[key] == key + ".md"
    longer = "a" * (MAX_NAME_BYTES - 2)
    assert build_paths([longer])[longer] == "a" * 110 + f"~{key_hash(longer)}.md"


def test_byte_cap_never_splits_escape() -> None:
    key = "%" * 60  # escapes to %25 x60 = 180 bytes
    name = build_paths([key])[key]
    assert re.fullmatch(r"(%25)*~[0-9a-f]{6}\.md", name)
    assert len(name.encode("utf-8")) <= MAX_NAME_BYTES


def test_byte_cap_folder_uses_prefix_hash() -> None:
    folder = "f" * 130
    key = f"{folder}:page"
    path = build_paths([key])[key]
    first, rest = path.split("/")
    assert first == "f" * 113 + f"~{key_hash(folder)}"
    assert len(first.encode("utf-8")) <= MAX_NAME_BYTES
    assert rest == "page.md"


def test_shared_truncated_prefix_gives_distinct_names() -> None:
    a, b = "x" * 200 + "a", "x" * 200 + "b"
    p = build_paths([a, b])
    assert p[a] != p[b]
    assert all(len(v.encode()) <= MAX_NAME_BYTES for v in p.values())


def test_literal_suffix_lookalike_still_collides() -> None:
    k1 = "x"
    k2 = f"x~{key_hash('x')}"
    p = build_paths(["index", k1, k2])
    assert len(set(p.values())) == 3


def test_reserved_suffix_lookalike_collides_visibly() -> None:
    literal = f"index~{key_hash('index')}"
    p = build_paths(["index", literal])
    assert p["index"] == f"index~{key_hash('index')}~{key_hash('index')}.md"
    assert p[literal] == f"{literal}~{key_hash(literal)}.md"


def test_collision_surviving_suffix_raises() -> None:
    # "Note" and "note" both get suffixed; "Note~<h>" (literal) then equals
    # the suffixed "Note" -- the design says this is an internal error.
    literal = f"Note~{key_hash('Note')}"
    with pytest.raises(ValueError, match="collision"):
        build_paths(["Note", "note", literal])


def test_paths_are_unique_case_and_nfc_insensitively() -> None:
    keys = ["A:b", "a:B", "a:b", "A:B", "x", "X", "x.md:y", "index", "Index"]
    p = build_paths(keys)
    folded = [unicodedata.normalize("NFC", v).casefold() for v in p.values()]
    assert len(set(folded)) == len(keys)
    for path in p.values():
        assert path.endswith(".md")
        for name in _names(path):
            assert len(name.encode("utf-8")) <= MAX_NAME_BYTES


def test_output_independent_of_input_order() -> None:
    keys = ["Team:x", "team:y", "index", "a", "a.md:b", "a::b", "a:_:c", "Note", "note"]
    assert build_paths(keys) == build_paths(list(reversed(keys)))
    assert build_paths(keys) == build_paths(sorted(keys))


def test_duplicate_keys_are_harmless() -> None:
    assert build_paths(["a", "a"]) == {"a": "a.md"}


def test_very_deep_key_does_not_recurse() -> None:
    key = ":".join(["d"] * 3000)
    assert build_paths([key])[key] == "/".join(["d"] * 3000) + ".md"


def test_empty_input() -> None:
    assert build_paths([]) == {}


def test_lone_surrogates_are_escaped_not_crashing():
    assert escape_segment("a\ud800b") == "a%ED%A0%80b"
    assert len(key_hash("\udfff")) == 6
    path = build_paths(["x:\ud800"])["x:\ud800"]
    path.encode("utf-8")  # a writable file name
