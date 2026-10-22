"""Sidecar contract for 2.3.8 memory review: history, list and confirm."""

from uuid import uuid4

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from bilinc.cloud.runtime import decode_cursor, encode_cursor, value_preview  # noqa: E402
from bilinc.cloud.service import create_app  # noqa: E402
from bilinc.core.models import MemoryEntry  # noqa: E402

HEADERS = {"X-Bilinc-Sidecar-Token": "secret"}


@pytest.fixture()
def sidecar(tmp_path):
    # One client context keeps every request on the same portal thread; without it each
    # request gets a new thread and the audit trail's SQLite connection may be used from
    # a thread other than the one that opened it.
    with TestClient(create_app(runtime_dir=tmp_path, sidecar_token="secret")) as client:
        yield client


def _commit(client, project, key, value, **extra):
    response = client.post(
        f"/v1/projects/{project}/commit",
        headers=HEADERS,
        json={"key": key, "value": value, **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _post(client, project, path, body):
    return client.post(f"/v1/projects/{project}/{path}", headers=HEADERS, json=body)


def test_health_advertises_the_memory_review_capabilities(sidecar):
    capabilities = sidecar.get("/health", headers=HEADERS).json()["capabilities"]
    assert {
        "commit_if_absent",
        "memory_history",
        "memory_list",
        "memory_confirm",
        "memory_list_source",
        "memory_list_order",
    } <= set(capabilities)


def test_new_routes_require_the_sidecar_token(sidecar):
    project = str(uuid4())
    for path, body in (
        ("history", {"key": "a"}),
        ("memories", {}),
        ("confirm", {"key": "a"}),
    ):
        assert sidecar.post(f"/v1/projects/{project}/{path}", json=body).status_code == 401


# --- history -----------------------------------------------------------------


def test_history_lists_create_revise_and_confirm_newest_first(sidecar):
    project = str(uuid4())
    _commit(sidecar, project, "team.deploy_day", "tuesday", source="claude")
    revised = _post(
        sidecar,
        project,
        "revise",
        {"key": "team.deploy_day", "value": "thursday", "reason": "moved"},
    )
    assert revised.status_code == 200
    assert _post(sidecar, project, "confirm", {"key": "team.deploy_day"}).status_code == 200

    history = _post(sidecar, project, "history", {"key": "team.deploy_day"}).json()

    ops = [entry["op"] for entry in history["entries"]]
    assert ops[0] == "confirm"
    assert ops[1] == "update"
    assert ops[-1] == "create"
    update = history["entries"][1]
    assert update["before"] == "tuesday"
    assert update["after"] == "thursday"
    assert update["reason"] == "moved"
    confirm = history["entries"][0]
    assert confirm["before"] == confirm["after"] == "thursday"
    assert history["exists"] is True
    assert history["truncated"] is False
    timestamps = [entry["at"] for entry in history["entries"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_history_never_returns_values_from_before_a_forget(sidecar):
    project = str(uuid4())
    _commit(sidecar, project, "person.phone", "+90 555 000 0000")
    assert _post(
        sidecar, project, "forget", {"key": "person.phone", "reason": "user asked"}
    ).status_code == 200
    _commit(sidecar, project, "person.phone", "redacted-later")

    history = _post(sidecar, project, "history", {"key": "person.phone"}).json()
    serialized = str(history)

    assert "+90 555" not in serialized
    ops = [entry["op"] for entry in history["entries"]]
    # The paired FORGET rows read as one event, and it carries the reason.
    assert ops.count("forget") == 1
    forget = next(entry for entry in history["entries"] if entry["op"] == "forget")
    assert forget["reason"] == "user asked"
    assert forget["values_redacted"] is True
    # The write after the forget is visible as usual.
    assert history["entries"][0]["after"] == "redacted-later"


def test_history_of_a_forgotten_key_reports_it_no_longer_exists(sidecar):
    project = str(uuid4())
    _commit(sidecar, project, "temp.note", "secret-ish")
    _post(sidecar, project, "forget", {"key": "temp.note", "reason": "done"})

    history = _post(sidecar, project, "history", {"key": "temp.note"}).json()

    assert history["exists"] is False
    assert "secret-ish" not in str(history)


def test_history_value_modes(sidecar):
    project = str(uuid4())
    _commit(sidecar, project, "doc.long", "x" * 500)

    none = _post(sidecar, project, "history", {"key": "doc.long", "values": "none"}).json()
    preview = _post(sidecar, project, "history", {"key": "doc.long", "values": "preview"}).json()

    assert "after" not in none["entries"][0]
    assert preview["entries"][0]["after"] == "x" * 200 + "…"
    assert _post(sidecar, project, "history", {"key": "doc.long", "values": "raw"}).status_code == 422


def test_history_limit_and_truncation(sidecar):
    project = str(uuid4())
    _commit(sidecar, project, "counter", 0)
    for value in range(1, 6):
        _post(sidecar, project, "revise", {"key": "counter", "value": value})

    page = _post(sidecar, project, "history", {"key": "counter", "limit": 2}).json()

    assert [entry["after"] for entry in page["entries"]] == [5, 4]
    assert page["truncated"] is True
    assert _post(sidecar, project, "history", {"key": "counter", "limit": 101}).status_code == 422


def test_history_is_project_isolated(sidecar):
    project_a, project_b = str(uuid4()), str(uuid4())
    _commit(sidecar, project_a, "shared.key", "tenant-a")

    other = _post(sidecar, project_b, "history", {"key": "shared.key"}).json()

    assert other["entries"] == []
    assert other["exists"] is False


def test_history_of_unknown_key_is_empty_not_an_error(sidecar):
    response = _post(sidecar, str(uuid4()), "history", {"key": "never.written"})
    assert response.status_code == 200
    assert response.json()["entries"] == []


# --- list --------------------------------------------------------------------


def test_list_pages_by_key_with_a_stable_cursor(sidecar):
    project = str(uuid4())
    for index in range(5):
        _commit(sidecar, project, f"k.{index}", index)

    first = _post(sidecar, project, "memories", {"limit": 2}).json()
    assert [entry["key"] for entry in first["entries"]] == ["k.0", "k.1"]
    assert first["total"] == 5

    # A write that sorts before the cursor must not shift the next page.
    _commit(sidecar, project, "a.first", "new")
    second = _post(sidecar, project, "memories", {"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [entry["key"] for entry in second["entries"]] == ["k.2", "k.3"]

    third = _post(sidecar, project, "memories", {"limit": 2, "cursor": second["next_cursor"]}).json()
    assert [entry["key"] for entry in third["entries"]] == ["k.4"]
    assert third["next_cursor"] is None


def test_list_filters_by_prefix_type_and_update_time(sidecar):
    project = str(uuid4())
    _commit(sidecar, project, "team.a", 1, memory_type="semantic")
    _commit(sidecar, project, "team_b", 2, memory_type="semantic")
    _commit(sidecar, project, "team.c", 3, memory_type="working")
    _commit(sidecar, project, "other", 4)

    by_prefix = _post(sidecar, project, "memories", {"prefix": "team."}).json()
    # `_` and `%` are literal, never wildcards.
    assert [entry["key"] for entry in by_prefix["entries"]] == ["team.a", "team.c"]
    assert by_prefix["total"] == 2

    by_type = _post(sidecar, project, "memories", {"prefix": "team.", "memory_type": "working"}).json()
    assert [entry["key"] for entry in by_type["entries"]] == ["team.c"]

    newest_team = max(entry["updated_at"] for entry in by_prefix["entries"])
    later = _post(sidecar, project, "memories", {"updated_after": newest_team}).json()
    assert [entry["key"] for entry in later["entries"]] == ["other"]
    before = _post(sidecar, project, "memories", {"updated_before": 0}).json()
    assert before["entries"] == [] and before["total"] == 0


def test_list_rejects_unknown_memory_type_and_bad_cursor(sidecar):
    project = str(uuid4())
    assert _post(sidecar, project, "memories", {"memory_type": "imaginary"}).status_code == 400
    response = _post(sidecar, project, "memories", {"cursor": "%%%not-base64%%%"})
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_cursor"


def test_list_entries_carry_version_and_respect_value_modes(sidecar):
    project = str(uuid4())
    committed = _commit(sidecar, project, "doc.long", "y" * 300)

    preview = _post(sidecar, project, "memories", {}).json()["entries"][0]
    full = _post(sidecar, project, "memories", {"values": "full"}).json()["entries"][0]
    none = _post(sidecar, project, "memories", {"values": "none"}).json()["entries"][0]

    assert preview["value"] == "y" * 200 + "…"
    assert full["value"] == "y" * 300
    assert "value" not in none
    assert preview["entry_version"] == committed["entry_version"]
    assert preview["memory_type"] == "semantic"


def test_list_is_project_isolated(sidecar):
    project_a, project_b = str(uuid4()), str(uuid4())
    _commit(sidecar, project_a, "only.a", "a")

    listing = _post(sidecar, project_b, "memories", {}).json()

    assert listing["entries"] == [] and listing["total"] == 0


def test_list_filters_by_source_before_paging(sidecar):
    project = str(uuid4())
    for index in range(5):
        _commit(sidecar, project, f"k.{index}", index, source="claude" if index % 2 == 0 else "codex")
    _commit(sidecar, project, "k.5", 5)  # no source: stored as "bilinc_cloud"
    _commit(sidecar, project, "k.6", 6, source="hermes")

    first = _post(sidecar, project, "memories", {"sources": ["claude"], "limit": 2}).json()
    assert [entry["key"] for entry in first["entries"]] == ["k.0", "k.2"]
    assert {entry["source"] for entry in first["entries"]} == {"claude"}
    assert first["total"] == 3
    assert first["next_cursor"]

    # A matching write that sorts before the cursor must not shift the next page.
    _commit(sidecar, project, "a.first", "new", source="claude")
    second = _post(
        sidecar, project, "memories", {"sources": ["claude"], "limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert [entry["key"] for entry in second["entries"]] == ["k.4"]
    assert second["next_cursor"] is None
    assert second["total"] == 4

    several = _post(sidecar, project, "memories", {"sources": ["codex", "hermes"]}).json()
    assert [entry["key"] for entry in several["entries"]] == ["k.1", "k.3", "k.6"]
    assert several["total"] == 3

    default = _post(sidecar, project, "memories", {"sources": ["bilinc_cloud"]}).json()
    assert [entry["key"] for entry in default["entries"]] == ["k.5"]
    assert default["entries"][0]["source"] == "bilinc_cloud"

    combined = _post(sidecar, project, "memories", {"sources": ["claude"], "prefix": "k."}).json()
    assert [entry["key"] for entry in combined["entries"]] == ["k.0", "k.2", "k.4"]
    assert combined["total"] == 3

    # Exact match: no prefix, case or wildcard semantics.
    for near_miss in (["claud"], ["Claude"], ["claude%"], ["unknown"], [""]):
        listing = _post(sidecar, project, "memories", {"sources": near_miss}).json()
        assert listing["entries"] == [] and listing["total"] == 0


def test_list_without_sources_is_unchanged(sidecar):
    project = str(uuid4())
    _commit(sidecar, project, "a", 1, source="claude")
    _commit(sidecar, project, "b", 2)

    omitted = _post(sidecar, project, "memories", {}).json()
    assert omitted == _post(sidecar, project, "memories", {"sources": None}).json()
    # Unknown fields are still ignored, so old and new clients see the same list.
    assert omitted == _post(sidecar, project, "memories", {"not_a_field": ["x"]}).json()
    assert [entry["key"] for entry in omitted["entries"]] == ["a", "b"]
    assert omitted["total"] == 2


@pytest.mark.parametrize(
    "sources",
    [[], [f"s{index}" for index in range(21)], ["x" * 257], ["a\x00b"]],
)
def test_list_rejects_out_of_bounds_source_filters(sidecar, sources):
    response = _post(sidecar, str(uuid4()), "memories", {"sources": sources})
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_request"


def test_list_accepts_source_filters_at_the_bounds(sidecar):
    project = str(uuid4())
    _commit(sidecar, project, "edge", 1, source="x" * 256)
    at_bounds = [f"s{index}" for index in range(19)] + ["x" * 256]
    listing = _post(sidecar, project, "memories", {"sources": at_bounds}).json()
    assert [entry["key"] for entry in listing["entries"]] == ["edge"]


def _seed_source_rows(backend, run):
    """Rows covering every way a source can be stored."""
    rows = [
        ("a.1", "claude", {}),
        ("a.2", "", {"source": "codex"}),  # legacy: only metadata.source
        ("a.3", "", {}),  # no source at all
        ("a.4", "claude", {}),
        ("a.5", "bilinc_cloud", {}),
        ("a.6", "hermes", {"source": "codex"}),  # the column wins
        ("a.7", "", {"source": 5}),  # a non-string metadata.source is no source
    ]
    for key, source, metadata in rows:
        run(backend.save(MemoryEntry(key=key, value=key, source=source, metadata=metadata)))


def _assert_source_filter_contract(backend, run):
    async def keys(**kwargs):
        return [entry.key for entry in await backend.list_page(**kwargs)]

    everything = run(keys(limit=50))
    assert everything == [f"a.{index}" for index in range(1, 8)]
    assert run(backend.count_filtered()) == 7

    assert run(keys(sources=["claude", "codex"], limit=50)) == ["a.1", "a.2", "a.4"]
    assert run(backend.count_filtered(sources=["claude", "codex"])) == 3
    assert run(keys(sources=["claude", "codex"], limit=2)) == ["a.1", "a.2"]
    assert run(keys(sources=["claude", "codex"], after_key="a.2", limit=2)) == ["a.4"]
    assert run(keys(sources=["hermes"], limit=50)) == ["a.6"]
    assert run(keys(sources=[""], limit=50)) == ["a.3", "a.7"]
    assert run(backend.count_filtered(sources=[""])) == 2
    assert run(keys(sources=["bilinc_cloud"], prefix="a.", limit=50)) == ["a.5"]
    assert run(keys(sources=["nobody"], limit=50)) == []


def test_sqlite_list_page_filters_by_effective_source(tmp_path):
    import asyncio

    from bilinc.storage.sqlite import SQLiteBackend

    loop = asyncio.new_event_loop()
    try:
        backend = SQLiteBackend(db_path=str(tmp_path / "sources.db"))
        loop.run_until_complete(backend.init())
        _seed_source_rows(backend, loop.run_until_complete)
        _assert_source_filter_contract(backend, loop.run_until_complete)
        loop.run_until_complete(backend.close())
    finally:
        loop.close()


# --- confirm -----------------------------------------------------------------


def test_confirm_keeps_the_value_and_moves_updated_at(sidecar):
    project = str(uuid4())
    committed = _commit(sidecar, project, "home.city", "Istanbul", importance=0.7)
    before = _post(sidecar, project, "memories", {"values": "full"}).json()["entries"][0]

    confirmed = _post(
        sidecar,
        project,
        "confirm",
        {"key": "home.city", "expected_version": committed["entry_version"]},
    )

    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["confirmed"] is True
    assert body["updated_at"] >= before["updated_at"]
    after = _post(sidecar, project, "memories", {"values": "full"}).json()["entries"][0]
    assert after["value"] == "Istanbul"
    assert after["importance"] == pytest.approx(0.7)
    assert after["created_at"] == pytest.approx(before["created_at"])
    assert after["entry_version"] == body["entry_version"]


def test_confirm_refuses_a_stale_version_and_a_missing_key(sidecar):
    project = str(uuid4())
    committed = _commit(sidecar, project, "home.city", "Istanbul")
    _post(sidecar, project, "revise", {"key": "home.city", "value": "Ankara"})

    stale = _post(
        sidecar,
        project,
        "confirm",
        {"key": "home.city", "expected_version": committed["entry_version"]},
    )
    missing = _post(sidecar, project, "confirm", {"key": "never.written"})

    assert stale.status_code == 409 and stale.json()["detail"] == "version_conflict"
    assert missing.status_code == 404 and missing.json()["detail"] == "memory_not_found"


# --- helpers -----------------------------------------------------------------


def test_cursor_round_trips_unicode_keys():
    for key in ("a", "çalışma.notu", "emoji.🙂", "x" * 512):
        assert decode_cursor(encode_cursor(key)) == key


def test_value_preview_renders_structured_values_as_json():
    assert value_preview({"a": "ö"}) == '{"a": "ö"}'
    assert value_preview("short") == "short"


def test_a_single_entry_is_returned_whole_however_large(tmp_path):
    from bilinc.core.audit import OpType
    from bilinc.core.models import MemoryEntry, MemoryType

    app = create_app(runtime_dir=tmp_path, sidecar_token="secret")
    project = str(uuid4())
    big = "z" * 600_000

    # Seed through the backend and audit trail directly: the full write path
    # is not what this test is about, and it is slow on values this large.
    async def seed():
        plane = await app.state.runtime_manager.get_plane(project)
        for key in ("big.one", "big.two"):
            entry = MemoryEntry(key=key, value=big, memory_type=MemoryType.SEMANTIC)
            await plane.backend.save(entry)
            plane.audit.log(OpType.CREATE, key, after_value=entry.to_dict())

    with TestClient(app) as client:
        # Seed on the app's own loop thread, where the runtime's connections live.
        client.portal.call(seed)
        _assert_single_entries_come_back_whole(client, project, big)


def _assert_single_entries_come_back_whole(client, project, big):
    # Two big entries on one page exceed the bound...
    assert _post(client, project, "memories", {"values": "full"}).status_code == 400
    # ...but a page of one always comes back with the full value.
    single = _post(client, project, "memories", {"values": "full", "limit": 1})
    assert single.status_code == 200
    assert single.json()["entries"][0]["value"] == big
    one_change = _post(client, project, "history", {"key": "big.one", "limit": 1})
    assert one_change.status_code == 200
    assert one_change.json()["entries"][0]["after"] == big


def test_confirm_works_on_an_entry_restored_by_rollback(sidecar):
    """Rollback restores the backend only; confirm must not trip on the stale belief."""
    project = str(uuid4())
    _commit(sidecar, project, "plan", "old plan", importance=0.2)
    snapshot = _post(sidecar, project, "snapshots", {"label": "before"}).json()["snapshot"]["id"]
    assert _post(sidecar, project, "revise", {"key": "plan", "value": "new plan", "importance": 1.0}).status_code == 200
    preview = _post(sidecar, project, "rollback/preview", {"snapshot_id": snapshot}).json()
    restored = _post(
        sidecar,
        project,
        "rollback",
        {"snapshot_id": snapshot, "reason": "undo", "expected_current_root": preview["current_root_hash"]},
    )
    assert restored.status_code == 200, restored.text

    confirmed = _post(sidecar, project, "confirm", {"key": "plan"})

    assert confirmed.status_code == 200, confirmed.text
    listed = _post(sidecar, project, "memories", {"values": "full"}).json()["entries"][0]
    assert listed["value"] == "old plan"
    assert _post(sidecar, project, "history", {"key": "plan", "limit": 1}).json()["entries"][0]["op"] == "confirm"


def test_history_pages_count_events_not_raw_rows(sidecar):
    """Each forget writes two rows; pages must still fill with logical events."""
    project = str(uuid4())
    for cycle in range(6):
        _commit(sidecar, project, "cycled", f"v{cycle}")
        _post(sidecar, project, "forget", {"key": "cycled", "reason": f"cycle {cycle}"})

    page = _post(sidecar, project, "history", {"key": "cycled", "limit": 8, "values": "none"}).json()

    assert len(page["entries"]) == 8
    assert page["truncated"] is True
    everything = _post(sidecar, project, "history", {"key": "cycled", "limit": 100, "values": "none"}).json()
    assert [entry["op"] for entry in everything["entries"]] == ["forget", "create"] * 6
    assert everything["truncated"] is False


@pytest.mark.parametrize("cursor", ["%%%", "a", "abc=", "YQ==", "YQ", "Y Q", ""])
def test_list_rejects_cursors_it_could_not_have_issued(sidecar, cursor):
    project = str(uuid4())
    _commit(sidecar, project, "a", 1)
    _commit(sidecar, project, "b", 2)

    response = _post(sidecar, project, "memories", {"cursor": cursor})

    if cursor == "YQ":  # the canonical cursor for key "a"
        assert response.status_code == 200
        assert [entry["key"] for entry in response.json()["entries"]] == ["b"]
    else:
        assert response.status_code == 400, cursor
        assert response.json()["detail"] == "invalid_cursor"


def test_cursors_page_past_the_widest_possible_key(sidecar):
    project = str(uuid4())
    widest = "🙂" * 512  # 512 characters, 2,048 UTF-8 bytes
    _commit(sidecar, project, widest, "wide")
    _commit(sidecar, project, "\U0010ffff", "after")

    first = _post(sidecar, project, "memories", {"limit": 1}).json()
    assert first["entries"][0]["key"] == widest
    assert len(first["next_cursor"]) > 2700

    second = _post(sidecar, project, "memories", {"limit": 1, "cursor": first["next_cursor"]})
    assert second.status_code == 200, second.text
    assert second.json()["entries"][0]["key"] == "\U0010ffff"


def test_revise_after_rollback_is_judged_against_the_restored_entry(sidecar):
    """Entrenchment from the rolled-back revision must not outrank later edits."""
    project = str(uuid4())
    _commit(sidecar, project, "plan", "v1", importance=0.2)
    snapshot = _post(sidecar, project, "snapshots", {}).json()["snapshot"]["id"]
    _post(sidecar, project, "revise", {"key": "plan", "value": "v2", "importance": 1.0})
    preview = _post(sidecar, project, "rollback/preview", {"snapshot_id": snapshot}).json()
    _post(
        sidecar,
        project,
        "rollback",
        {"snapshot_id": snapshot, "reason": "undo", "expected_current_root": preview["current_root_hash"]},
    )

    revised = _post(sidecar, project, "revise", {"key": "plan", "value": "v3", "importance": 0.5})

    assert revised.status_code == 200 and revised.json()["success"] is True, revised.text
    listed = _post(sidecar, project, "memories", {"values": "full"}).json()["entries"][0]
    assert listed["value"] == "v3"


def test_iterated_revision_keeps_agm_entrenchment_outside_rollback(sidecar):
    """A recency revision keeps the replaced belief's entrenchment (AGM max rule)."""
    project = str(uuid4())
    _commit(sidecar, project, "policy", "a", importance=1.0)
    first = _post(sidecar, project, "revise", {"key": "policy", "value": "b", "importance": 0.2, "strategy": "recency"})
    assert first.json()["success"] is True

    second = _post(
        sidecar, project, "revise", {"key": "policy", "value": "c", "importance": 0.5, "strategy": "entrenchment"}
    )

    assert second.status_code == 200
    assert second.json()["success"] is False
    listed = _post(sidecar, project, "memories", {"values": "full"}).json()["entries"][0]
    assert listed["value"] == "b"


def test_confirm_changes_only_the_update_time(tmp_path):
    """No re-verification, no revision: every other stored field stays exactly as it was."""
    app = create_app(runtime_dir=tmp_path, sidecar_token="secret")
    project = str(uuid4())

    with TestClient(app) as client:
        _commit(client, project, "fact", "stated once", importance=0.4, metadata={"note": "kept"})

        async def mark_unverified():
            plane = await app.state.runtime_manager.get_plane(project)
            entry = await plane.backend.load("fact")
            entry.is_verified = False
            entry.verification_score = 0.123
            entry.verification_method = "legacy-rule"
            await plane.backend.save(entry)
            return entry.to_dict()

        before = client.portal.call(mark_unverified)
        assert _post(client, project, "confirm", {"key": "fact"}).status_code == 200

        async def load():
            plane = await app.state.runtime_manager.get_plane(project)
            return (await plane.backend.load("fact")).to_dict()

        after = client.portal.call(load)

    assert after["updated_at"] > before["updated_at"]
    # Read counters move on every backend load, including this test's own.
    read_counters = {"access_count", "last_accessed"}
    changed = {name for name in before if before[name] != after[name]} - read_counters
    assert changed == {"updated_at"}


def test_agm_judges_a_revision_against_the_persisted_entry(tmp_path):
    """After a backend-only restore (as a rollback does), AGM must see the stored
    instance, timestamps included, so recency compares against what is stored."""
    app = create_app(runtime_dir=tmp_path, sidecar_token="secret")
    project = str(uuid4())
    seen = {}

    with TestClient(app) as client:
        _commit(client, project, "status", "green")

        async def restore_older_instance_and_spy():
            plane = await app.state.runtime_manager.get_plane(project)
            conn = plane.backend._get_conn()
            conn.execute(
                "UPDATE memories SET created_at = created_at - 3600, updated_at = updated_at - 3600 WHERE key = ?",
                ("status",),
            )
            conn.commit()
            entry = await plane.backend.load("status")
            assert plane.agm_engine.belief_state.get_belief("status").created_at > entry.created_at

            original = plane.agm_engine.revise

            def spy(new_entry, *args, **kwargs):
                seen["cached_created_at"] = plane.agm_engine.belief_state.get_belief("status").created_at
                return original(new_entry, *args, **kwargs)

            plane.agm_engine.revise = spy
            return entry.created_at

        persisted_created_at = client.portal.call(restore_older_instance_and_spy)
        revised = _post(client, project, "revise", {"key": "status", "value": "amber", "strategy": "recency"})

    assert revised.status_code == 200
    assert seen["cached_created_at"] == pytest.approx(persisted_created_at)


def test_list_reports_the_same_source_the_filter_matches():
    from bilinc.cloud.runtime import _effective_source

    assert _effective_source({"source": "mcp:Claude", "metadata": {"source": "x"}}) == "mcp:Claude"
    assert _effective_source({"source": "", "metadata": {"source": "agent"}}) == "agent"
    # A non-string metadata.source is no source, exactly as the backends' filter treats it.
    assert _effective_source({"source": "", "metadata": {"source": 5}}) is None
    assert _effective_source({"source": None, "metadata": None}) is None


# --- list order ---------------------------------------------------------------

@pytest.mark.parametrize("order", ["newest", "oldest"])
def test_list_orders_by_update_time_with_a_stable_cursor(sidecar, order):
    import time

    project = str(uuid4())
    for key in ("b", "a", "c", "d"):
        _commit(sidecar, project, key, key)
        time.sleep(0.01)
    expected = ["d", "c", "a", "b"] if order == "newest" else ["b", "a", "c", "d"]

    first = _post(sidecar, project, "memories", {"limit": 2, "order": order}).json()
    assert first["order"] == order
    assert [entry["key"] for entry in first["entries"]] == expected[:2]
    assert first["total"] == 4
    second = _post(sidecar, project, "memories", {"limit": 2, "order": order, "cursor": first["next_cursor"]}).json()
    assert [entry["key"] for entry in second["entries"]] == expected[2:]
    assert second["next_cursor"] is None


def test_list_order_cursors_are_bound_to_their_order(sidecar):
    project = str(uuid4())
    for key in ("a", "b", "c"):
        _commit(sidecar, project, key, key)
    newest = _post(sidecar, project, "memories", {"limit": 1, "order": "newest"}).json()["next_cursor"]
    by_key = _post(sidecar, project, "memories", {"limit": 1}).json()["next_cursor"]
    for body in (
        {"order": "oldest", "cursor": newest},
        {"cursor": newest},
        {"order": "newest", "cursor": by_key},
    ):
        response = _post(sidecar, project, "memories", {"limit": 1, **body})
        assert response.status_code == 400, (body, response.text)
    assert _post(sidecar, project, "memories", {"order": "sideways"}).status_code == 422


def test_list_without_order_is_key_ordered_as_before(sidecar):
    project = str(uuid4())
    for key in ("b", "a"):
        _commit(sidecar, project, key, key)
    body = _post(sidecar, project, "memories", {}).json()
    assert [entry["key"] for entry in body["entries"]] == ["a", "b"]
    assert body["order"] == "key"


@pytest.mark.parametrize("order", ["newest", "oldest"])
def test_sqlite_list_page_orders_ties_by_key_and_pages_through_them(tmp_path, order):
    import asyncio

    from bilinc.storage.sqlite import SQLiteBackend

    async def scenario():
        backend = SQLiteBackend(str(tmp_path / "order.sqlite"))
        await backend.init()
        conn = backend._get_conn()
        for key, stamp in (("x", 5.0), ("a", 5.0), ("m", 9.0), ("z", 1.0)):
            await backend.save(MemoryEntry(key=key, value=key))
            # save() stamps the clock; fixed times make ties and order explicit.
            conn.execute("UPDATE memories SET updated_at = ? WHERE key = ?", (stamp, key))
        conn.commit()
        seen, after = [], None
        while True:
            page = await backend.list_page(
                order=order, after_key=after[1] if after else None, after_updated=after[0] if after else None, limit=1
            )
            if not page:
                break
            seen.append(page[0].key)
            after = (page[0].updated_at, page[0].key)
        return seen

    expected = ["m", "a", "x", "z"] if order == "newest" else ["z", "a", "x", "m"]
    assert asyncio.run(scenario()) == expected


def test_order_cursor_for_a_long_non_ascii_key_stays_within_the_cursor_limit():
    from bilinc.cloud.runtime import decode_order_cursor, encode_order_cursor
    from bilinc.cloud.service import MAX_CURSOR_LENGTH

    for key in ("ş" * 512, "\U0001F600" * 512):
        cursor = encode_order_cursor("newest", 1792675712.123456, key)
        assert len(cursor) <= MAX_CURSOR_LENGTH
        assert decode_order_cursor(cursor, "newest") == (1792675712.123456, key)


@pytest.mark.parametrize(
    "payload",
    [
        '{"o":"newest","u":NaN,"k":"a"}',
        '{"o":"newest","u":Infinity,"k":"a"}',
        '{"o":"newest","u":1e400,"k":"a"}',
        '{"o":"newest","u":' + "9" * 400 + ',"k":"a"}',
        "[" * 3000,
    ],
)
def test_crafted_order_cursors_are_a_400_not_a_500(sidecar, payload):
    project = str(uuid4())
    _commit(sidecar, project, "a", "a")
    cursor = encode_cursor(payload)
    for order in ("newest", "key"):
        response = _post(sidecar, project, "memories", {"order": order, "cursor": cursor})
        assert response.status_code in (400, 200), response.text
        assert response.status_code != 500


@pytest.mark.parametrize("order", ["newest", "oldest"])
def test_sqlite_update_time_order_reads_text_timestamps_and_terminates(tmp_path, order):
    import asyncio

    from bilinc.storage.sqlite import SQLiteBackend

    async def scenario():
        backend = SQLiteBackend(str(tmp_path / "text.sqlite"))
        await backend.init()
        conn = backend._get_conn()
        stamps = {"a": 100.0, "b": "1970-01-01T00:03:20+00:00", "c": 300.0, "d": "1970-01-01T00:06:40Z", "e": "50"}
        for key, stamp in stamps.items():
            await backend.save(MemoryEntry(key=key, value=key))
            conn.execute("UPDATE memories SET updated_at = ? WHERE key = ?", (stamp, key))
        conn.commit()
        seen, after = [], None
        for _ in range(20):
            page = await backend.list_page(
                order=order, after_key=after[1] if after else None, after_updated=after[0] if after else None, limit=1
            )
            if not page:
                return seen
            seen.append(page[0].key)
            after = (page[0].list_stamp, page[0].key)
        raise AssertionError(f"no end: {seen}")

    expected = ["e", "a", "b", "c", "d"]  # 50, 100, 200, 300, 400 seconds
    assert asyncio.run(scenario()) == (expected[::-1] if order == "newest" else expected)
