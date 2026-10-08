"""Sidecar contract for 2.3.8 memory review: history, list and confirm."""

from uuid import uuid4

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from bilinc.cloud.runtime import decode_cursor, encode_cursor, value_preview  # noqa: E402
from bilinc.cloud.service import create_app  # noqa: E402

HEADERS = {"X-Bilinc-Sidecar-Token": "secret"}


@pytest.fixture()
def sidecar(tmp_path):
    return TestClient(create_app(runtime_dir=tmp_path, sidecar_token="secret"))


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
    assert {"commit_if_absent", "memory_history", "memory_list", "memory_confirm"} <= set(capabilities)


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
