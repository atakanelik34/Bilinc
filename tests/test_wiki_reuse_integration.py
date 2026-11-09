"""History reuse end to end: the real SDK client, a counting scripted transport, no network.

A rerun reuses a key's history block only when the key's stored entry and the
rollback marker (the newest ``__system`` history entry) are unchanged and the
previous page still holds the block it wrote. Every other case fetches again.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from bilinc.wiki import export as export_module
from bilinc.wiki.export import MARKER_UNREADABLE
from bilinc.wiki.manifest import MANIFEST_NAME
from tests.test_wiki_export import ENTRIES, SECOND, history_payload, normalised, public_entry, run, transport_for
from tests.test_wiki_integration import entries, paged
from tests.wiki_fakes import NO_ROLLBACK, RoutedTransport, not_found, snapshot, unavailable

KEYS = sorted(entry["key"] for entry in ENTRIES)
ROLLBACK = {
    "key": "__system",
    "exists": False,
    "entries": [{"op": "rollback", "at": 1762700000.0, "reason": "undo", "source": None}],
    "truncated": False,
    "values": "none",
}


def marker_hash(answer):
    text = json.dumps({"entries": answer["entries"], "truncated": answer["truncated"]}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def changed_history(key, note="after the change"):
    payload = history_payload(key)
    payload["entries"] = [dict(payload["entries"][0], reason=note, after=note)]
    return payload


def manifest(tmp_path):
    return json.loads((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))


def write_manifest(tmp_path, data):
    (tmp_path / MANIFEST_NAME).write_text(json.dumps(data), encoding="utf-8")


def page(tmp_path, rel="solo.md"):
    return (tmp_path / rel).read_text(encoding="utf-8")


def all_fresh(key_note="after the change"):
    return {key: [changed_history(key, key_note)] for key in KEYS}


# --- the target: a rerun with no changes makes only the list and marker calls ----


def test_second_run_on_unchanged_data_makes_only_list_and_marker_calls(tmp_path):
    items = entries(250)
    payload = history_payload("bulk")
    first = RoutedTransport(paged(items), default_history=payload)
    run(tmp_path, first)
    after_first = normalised(tmp_path)
    assert first.marker_calls() == 1  # start marker only: nothing was reused, so no end read
    assert first.total_history_calls() == 250

    second = RoutedTransport(paged(items), default_history=payload)
    result = run(tmp_path, second, clock=SECOND)

    assert second.total_history_calls() == 0
    assert second.marker_calls() == 2
    assert len(second.list_bodies()) == 3
    assert (result.history_fetched, result.history_reused) == (0, 250)
    assert normalised(tmp_path) == after_first


def test_marker_is_read_first_and_last(tmp_path):
    run(tmp_path, transport_for())
    second = transport_for()
    run(tmp_path, second, clock=SECOND)

    order = second.order
    assert order[0] == ("history", "__system", "none")
    assert order[-1] == ("history", "__system", "none")
    assert [item[0] for item in order[1:-1]] == ["list"]


def test_first_run_reads_only_the_start_marker_before_the_list(tmp_path):
    transport = transport_for()
    run(tmp_path, transport)

    assert transport.order[0] == ("history", "__system", "none")
    assert transport.order[1][0] == "list"
    assert transport.marker_calls() == 1
    assert manifest(tmp_path)["history_marker"] == marker_hash(NO_ROLLBACK)


# --- changed keys ---------------------------------------------------------------


@pytest.mark.parametrize("field, value", [("entryVersion", "v-solo-2"), ("updatedAt", "2026-11-09T02:00:00.000Z")])
def test_a_changed_key_is_the_only_one_fetched(tmp_path, field, value):
    run(tmp_path, transport_for())
    changed = [dict(entry, **{field: value}) if entry["key"] == "solo" else entry for entry in ENTRIES]
    second = transport_for(changed, history={"solo": [changed_history("solo")]})

    result = run(tmp_path, second, clock=SECOND)

    assert second.history_calls("solo") == 1 and second.total_history_calls() == 1
    assert (result.history_fetched, result.history_reused) == (1, 3)
    assert "after the change" in page(tmp_path)


def test_rollback_restoring_an_old_version_refetches_every_key(tmp_path):
    # Same entryVersion and updatedAt as the first run, but history gained entries:
    # only the changed rollback marker can tell. Reusing here would show stale history.
    run(tmp_path, transport_for())
    second = transport_for(history=all_fresh("restored by rollback"), marker=[ROLLBACK])

    result = run(tmp_path, second, clock=SECOND)

    assert second.total_history_calls() == len(KEYS)
    assert result.history_reused == 0
    assert "restored by rollback" in page(tmp_path)
    assert manifest(tmp_path)["history_marker"] == marker_hash(ROLLBACK)


def test_rollback_during_the_run_refetches_the_reused_keys_in_the_same_run(tmp_path):
    run(tmp_path, transport_for())
    second = transport_for(history=all_fresh("restored mid-run"), marker=[NO_ROLLBACK, ROLLBACK])

    result = run(tmp_path, second, clock=SECOND)

    assert second.marker_calls() == 2
    assert second.total_history_calls() == len(KEYS)
    assert (result.history_fetched, result.history_reused) == (len(KEYS), 0)
    assert "restored mid-run" in page(tmp_path)
    # The manifest keeps the start marker, so the next run refetches once more.
    assert manifest(tmp_path)["history_marker"] == marker_hash(NO_ROLLBACK)
    third = transport_for(history=all_fresh("restored mid-run"), marker=[ROLLBACK])
    run(tmp_path, third, clock=SECOND)
    assert third.total_history_calls() == len(KEYS)


# --- every rule that turns reuse off ----------------------------------------------


def test_refresh_history_fetches_everything_and_skips_the_marker(tmp_path):
    run(tmp_path, transport_for())
    second = transport_for()

    result = run(tmp_path, second, clock=SECOND, refresh_history=True)

    assert second.marker_calls() == 0 and second.total_history_calls() == len(KEYS)
    assert result.history_reused == 0
    assert manifest(tmp_path)["history_marker"] is None


def test_a_different_history_count_refetches(tmp_path):
    run(tmp_path, transport_for())
    second = transport_for()
    run(tmp_path, second, clock=SECOND, history=6)
    assert second.total_history_calls() == len(KEYS)


def test_history_zero_then_history_again_refetches(tmp_path):
    run(tmp_path, transport_for(), history=0)
    second = transport_for()
    run(tmp_path, second, clock=SECOND)
    assert second.total_history_calls() == len(KEYS)


def test_an_incomplete_previous_manifest_refetches(tmp_path):
    run(tmp_path, transport_for())
    data = manifest(tmp_path)
    data["complete"] = False
    write_manifest(tmp_path, data)
    second = transport_for()
    run(tmp_path, second, clock=SECOND)
    assert second.total_history_calls() == len(KEYS)


def test_another_tool_version_refetches(tmp_path, monkeypatch):
    run(tmp_path, transport_for())
    monkeypatch.setattr(export_module, "__version__", "9.9.9")
    second = transport_for()
    run(tmp_path, second, clock=SECOND)
    assert second.total_history_calls() == len(KEYS)


def test_another_history_format_refetches(tmp_path):
    run(tmp_path, transport_for())
    data = manifest(tmp_path)
    data["history_format"] = 99
    write_manifest(tmp_path, data)
    second = transport_for()
    run(tmp_path, second, clock=SECOND)
    assert second.total_history_calls() == len(KEYS)


def test_an_unreadable_marker_turns_reuse_off_with_a_note(tmp_path):
    run(tmp_path, transport_for())
    second = transport_for(marker=[unavailable()])

    result = run(tmp_path, second, clock=SECOND)

    assert second.total_history_calls() == len(KEYS)
    assert MARKER_UNREADABLE in result.warnings
    assert manifest(tmp_path)["history_marker"] is None
    third = transport_for()
    run(tmp_path, third, clock=SECOND)
    assert third.total_history_calls() == len(KEYS)  # a null marker never matches


def test_a_missing_page_refetches_that_key(tmp_path):
    run(tmp_path, transport_for())
    (tmp_path / "solo.md").unlink()
    second = transport_for()
    run(tmp_path, second, clock=SECOND)
    assert second.history_calls("solo") == 1 and second.total_history_calls() == 1
    assert (tmp_path / "solo.md").is_file()


def test_a_page_replaced_by_a_symlink_refetches_and_leaves_the_target_alone(tmp_path):
    wiki = tmp_path / "wiki"
    run(wiki, transport_for())
    outside = tmp_path / "outside.md"
    outside.write_bytes((wiki / "solo.md").read_bytes())
    (wiki / "solo.md").unlink()
    (wiki / "solo.md").symlink_to(outside)
    before = outside.read_bytes()
    second = transport_for()

    run(wiki, second, clock=SECOND)

    assert second.history_calls("solo") == 1 and second.total_history_calls() == 1
    assert outside.read_bytes() == before
    assert not (wiki / "solo.md").is_symlink()


def test_a_page_edited_inside_its_history_refetches(tmp_path):
    run(tmp_path, transport_for())
    text = page(tmp_path)
    assert "reason: release" in text
    (tmp_path / "solo.md").write_text(text.replace("reason: release", "reason: edited by hand"), encoding="utf-8")
    second = transport_for()

    run(tmp_path, second, clock=SECOND)

    assert second.history_calls("solo") == 1 and second.total_history_calls() == 1
    assert "edited by hand" not in page(tmp_path)


def test_a_page_edited_outside_its_history_still_reuses_and_is_rewritten(tmp_path):
    run(tmp_path, transport_for())
    text = page(tmp_path)
    (tmp_path / "solo.md").write_text(text.replace("standalone", "edited value"), encoding="utf-8")
    second = transport_for()

    run(tmp_path, second, clock=SECOND)

    assert second.total_history_calls() == 0
    assert "edited value" not in page(tmp_path) and "standalone" in page(tmp_path)


def test_an_unavailable_history_is_never_reused(tmp_path):
    run(tmp_path, transport_for(history={"solo": [not_found()]}))
    assert "History unavailable." in page(tmp_path)
    assert "history_sha256" not in manifest(tmp_path)["keys"]["solo"]
    second = transport_for()

    run(tmp_path, second, clock=SECOND)

    assert second.history_calls("solo") == 1 and second.total_history_calls() == 1
    assert "History unavailable." not in page(tmp_path)


def test_a_manifest_path_outside_the_previous_files_is_not_read(tmp_path):
    run(tmp_path, transport_for())
    data = manifest(tmp_path)
    data["files"].remove("solo.md")
    write_manifest(tmp_path, data)
    (tmp_path / "solo.md").unlink()  # otherwise it is a user file at a needed path
    second = transport_for()
    run(tmp_path, second, clock=SECOND)
    assert second.history_calls("solo") == 1 and second.total_history_calls() == 1


# --- other surfaces -----------------------------------------------------------------


def test_a_user_key_named_system_is_a_page_and_is_counted_apart(tmp_path):
    items = ENTRIES + [public_entry("__system", "a user's own key", minute=9)]
    transport = transport_for(items)

    run(tmp_path, transport)

    assert transport.history_calls("__system") == 1
    assert transport.marker_calls() == 1
    assert "a user's own key" in page(tmp_path, "__system.md")


def test_the_cloud_folder_warning_is_returned(tmp_path):
    home = tmp_path / "home"
    target = home / "Dropbox" / "wiki"
    target.parent.mkdir(parents=True)

    result = run(target, transport_for(), home=home)

    assert any("Dropbox" in line for line in result.warnings)


def test_wikilinks_reach_the_written_pages(tmp_path):
    run(tmp_path, transport_for(), wikilinks=True)
    assert "[[./plan.md|project:bilinc:plan]]" in page(tmp_path, "project/bilinc/release.md")


def test_reused_pages_match_freshly_fetched_ones(tmp_path):
    reused, fresh = tmp_path / "reused", tmp_path / "fresh"
    for target in (reused, fresh):
        run(target, transport_for())
    run(reused, transport_for(), clock=SECOND)
    run(fresh, transport_for(), clock=SECOND, refresh_history=True)

    def pages(tree):
        return {rel: value for rel, value in normalised(tree).items() if rel != MANIFEST_NAME}

    assert pages(reused) == pages(fresh)
    assert snapshot(reused).keys() == snapshot(fresh).keys()


def test_reuse_keeps_owner_only_permissions(tmp_path):
    run(tmp_path, transport_for())
    run(tmp_path, transport_for(), clock=SECOND)
    for rel, (_, mode) in snapshot(tmp_path).items():
        assert mode == (0o700 if rel.endswith("/") else 0o600), rel
    assert os.stat(tmp_path).st_mode & 0o777 == 0o700
