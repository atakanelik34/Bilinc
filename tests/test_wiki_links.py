"""Mentions between wiki pages (``bilinc.wiki.links``)."""

from __future__ import annotations

from bilinc.wiki.links import MIN_LINK_KEY_LENGTH, find_links, value_text


def links(values):
    return find_links(values)[0]


def test_min_link_key_length_is_three():
    assert MIN_LINK_KEY_LENGTH == 3


def test_value_text_keeps_strings_and_compacts_json():
    assert value_text("ğüş text") == "ğüş text"
    assert value_text({"a": [1, "ş"]}) == '{"a":[1,"ş"]}'
    assert value_text(None) == "null"


def test_plain_mention():
    assert links({"a1": "see bbb", "bbb": ""})["a1"] == ["bbb"]


def test_sentence_punctuation_still_links():
    values = {"x": "see project:bilinc:release.", "project:bilinc:release": ""}
    assert links(values)["x"] == ["project:bilinc:release"]


def test_no_match_inside_longer_key():
    values = {
        "x": "project:bilinc:release-notes and project:bilinc:release2",
        "project:bilinc:release": "",
        "project:bilinc": "",
    }
    assert links(values)["x"] == []


def test_longest_key_wins():
    values = {"x": "project:bilinc:release", "project:bilinc": "", "project:bilinc:release": ""}
    assert links(values)["x"] == ["project:bilinc:release"]


def test_preceding_boundary():
    assert links({"x": "my.abc and /abc and abc", "abc": ""})["x"] == ["abc"]
    assert links({"x": "my.abc _abc :abc -abc 9abc", "abc": ""})["x"] == []


def test_following_boundary():
    assert links({"x": "abc_ abc: abc/ abcd abc.d abc-1", "abc": ""})["x"] == []
    assert links({"x": "(abc)", "abc": ""})["x"] == ["abc"]
    assert links({"x": "abc-", "abc": ""})["x"] == ["abc"]


def test_short_keys_ignored():
    assert links({"x": "ab ab", "ab": ""})["x"] == []


def test_self_mention_ignored():
    assert links({"abc": "abc"})["abc"] == []


def test_json_values_scanned():
    assert links({"x": {"ref": "abc"}, "abc": 1})["x"] == ["abc"]


def test_regex_metacharacters_in_keys():
    assert links({"x": "use a+b(c)", "a+b(c)": ""})["x"] == ["a+b(c)"]


def test_outgoing_sorted_and_deduplicated():
    values = {"x": "zzz then aaa then zzz", "aaa": "", "zzz": ""}
    assert links(values)["x"] == ["aaa", "zzz"]


def test_incoming_is_inverse():
    out, inc = find_links({"x": "abc", "y": "abc", "abc": ""})
    assert inc["abc"] == ["x", "y"] and inc["x"] == []
    assert set(out) == set(inc) == {"x", "y", "abc"}


def test_no_keys_long_enough():
    assert find_links({"a": "b", "b": "a"}) == ({"a": [], "b": []}, {"a": [], "b": []})
