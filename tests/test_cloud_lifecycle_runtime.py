"""Runtime behavior for the hosted revise, forget, diff, and rollback lifecycle.

These exercise ``ProjectRuntimeManager`` directly, which is the highest stable
seam where equivalence with local Bilinc semantics can be asserted without a
control plane or a sidecar in the way.
"""

import json
from uuid import uuid4

import pytest
import pytest_asyncio

from bilinc.cloud.runtime import ProjectRuntimeManager


@pytest_asyncio.fixture
async def manager(tmp_path):
    runtime = ProjectRuntimeManager(tmp_path)
    yield runtime
    await runtime.close()


@pytest.fixture
def project_id():
    return str(uuid4())


async def audit_reasons(manager, project_id, key):
    """Read back the reasons recorded against one key. Audit metadata is JSON text."""
    plane = await manager.get_plane(project_id)
    reasons = []
    for record in plane.audit.get_history(key=key, limit=20):
        if not record.metadata:
            continue
        payload = json.loads(record.metadata)
        if isinstance(payload, dict) and payload.get("reason"):
            reasons.append(payload["reason"])
    return reasons


# ---------------------------------------------------------------------------
# revise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revise_replaces_a_known_memory(manager, project_id):
    await manager.commit(project_id, key="plan", value={"step": 1})

    result = await manager.revise(project_id, key="plan", value={"step": 2}, reason="replanned")

    recalled = await manager.recall(project_id, query="step", profile="fast")
    assert result["success"] is True
    assert result["entry_version"].startswith("v1_")
    assert [item["value"] for item in recalled["results"]] == [{"step": 2}]


@pytest.mark.asyncio
async def test_revise_refuses_to_create_a_missing_memory(manager, project_id):
    """A revision that silently inserts is indistinguishable from an overwrite."""
    with pytest.raises(ValueError, match="memory_not_found"):
        await manager.revise(project_id, key="never.written", value={"step": 1})


@pytest.mark.asyncio
async def test_revise_honours_optimistic_concurrency(manager, project_id):
    first = await manager.commit(project_id, key="plan", value={"step": 1})

    accepted = await manager.revise(
        project_id, key="plan", value={"step": 2}, expected_version=first["entry_version"]
    )
    assert accepted["success"] is True

    # The stale version from before the accepted revision must now be rejected.
    with pytest.raises(ValueError, match="version_conflict"):
        await manager.revise(
            project_id, key="plan", value={"step": 3}, expected_version=first["entry_version"]
        )


@pytest.mark.asyncio
async def test_revise_records_the_reason_in_the_audit_trail(manager, project_id):
    await manager.commit(project_id, key="plan", value={"step": 1})
    await manager.revise(project_id, key="plan", value={"step": 2}, reason="superseded by user")

    reasons = await audit_reasons(manager, project_id, "plan")

    assert "superseded by user" in reasons


@pytest.mark.asyncio
async def test_revise_rejects_an_unknown_strategy(manager, project_id):
    await manager.commit(project_id, key="plan", value={"step": 1})

    with pytest.raises(ValueError, match="invalid_request"):
        await manager.revise(project_id, key="plan", value={"step": 2}, strategy="vibes")


@pytest.mark.asyncio
async def test_revise_is_isolated_per_project(manager):
    project_a = str(uuid4())
    project_b = str(uuid4())
    await manager.commit(project_a, key="plan", value={"tenant": "a"})

    with pytest.raises(ValueError, match="memory_not_found"):
        await manager.revise(project_b, key="plan", value={"tenant": "b"})


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forget_removes_the_memory_from_active_recall(manager, project_id):
    await manager.commit(project_id, key="obsolete", value={"stale": True})

    result = await manager.forget(project_id, key="obsolete", reason="superseded")

    recalled = await manager.recall(project_id, query="stale", profile="fast")
    assert result["removed"] is True
    assert recalled["results"] == []


@pytest.mark.asyncio
async def test_forget_never_returns_the_deleted_value(manager, project_id):
    await manager.commit(project_id, key="secretish", value={"token": "abc123"})

    result = await manager.forget(project_id, key="secretish", reason="cleanup")

    assert "abc123" not in str(result)
    assert "value" not in result


@pytest.mark.asyncio
async def test_forget_requires_the_memory_to_exist(manager, project_id):
    with pytest.raises(ValueError, match="memory_not_found"):
        await manager.forget(project_id, key="never.written", reason="cleanup")


@pytest.mark.asyncio
async def test_forget_keeps_an_audit_receipt_carrying_the_reason(manager, project_id):
    await manager.commit(project_id, key="obsolete", value={"stale": True})
    await manager.forget(project_id, key="obsolete", reason="policy change 2026-07")

    reasons = await audit_reasons(manager, project_id, "obsolete")

    assert "policy change 2026-07" in reasons


@pytest.mark.asyncio
async def test_forget_honours_optimistic_concurrency(manager, project_id):
    first = await manager.commit(project_id, key="plan", value={"step": 1})
    await manager.commit(project_id, key="plan", value={"step": 2})

    with pytest.raises(ValueError, match="version_conflict"):
        await manager.forget(
            project_id, key="plan", reason="cleanup", expected_version=first["entry_version"]
        )


@pytest.mark.asyncio
async def test_forget_is_isolated_per_project(manager):
    project_a = str(uuid4())
    project_b = str(uuid4())
    await manager.commit(project_a, key="plan", value={"tenant": "a"})

    with pytest.raises(ValueError, match="memory_not_found"):
        await manager.forget(project_b, key="plan", reason="cross-tenant probe")

    survivors = await manager.recall(project_a, query="tenant", profile="fast")
    assert [item["value"] for item in survivors["results"]] == [{"tenant": "a"}]


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_reports_added_modified_and_removed_keys(manager, project_id):
    await manager.commit(project_id, key="keep", value={"n": 1})
    await manager.commit(project_id, key="drop", value={"n": 2})
    baseline = await manager.create_snapshot(project_id)

    await manager.revise(project_id, key="keep", value={"n": 99})
    await manager.forget(project_id, key="drop", reason="cleanup")
    await manager.commit(project_id, key="fresh", value={"n": 3})

    result = await manager.diff(project_id, from_snapshot_id=baseline.id)

    assert result["counts"] == {"added": 1, "modified": 1, "removed": 1}
    assert [record["key"] for record in result["added"]] == ["fresh"]
    assert [record["key"] for record in result["modified"]] == ["keep"]
    assert [record["key"] for record in result["removed"]] == ["drop"]
    assert result["target"] == "current"


@pytest.mark.asyncio
async def test_diff_redacts_values_by_default(manager, project_id):
    await manager.commit(project_id, key="secretish", value={"token": "abc123"})
    baseline = await manager.create_snapshot(project_id)
    await manager.revise(project_id, key="secretish", value={"token": "def456"})

    redacted = await manager.diff(project_id, from_snapshot_id=baseline.id)
    revealed = await manager.diff(project_id, from_snapshot_id=baseline.id, include_values=True)

    assert "abc123" not in str(redacted)
    assert "def456" not in str(redacted)
    assert redacted["values_included"] is False
    assert revealed["modified"][0]["before"] == {"token": "abc123"}
    assert revealed["modified"][0]["after"] == {"token": "def456"}


@pytest.mark.asyncio
async def test_diff_between_two_snapshots(manager, project_id):
    await manager.commit(project_id, key="k", value={"n": 1})
    first = await manager.create_snapshot(project_id)
    await manager.commit(project_id, key="k2", value={"n": 2})
    second = await manager.create_snapshot(project_id)

    result = await manager.diff(project_id, from_snapshot_id=first.id, to_snapshot_id=second.id)

    assert result["target"] == "snapshot"
    assert result["counts"] == {"added": 1, "modified": 0, "removed": 0}


@pytest.mark.asyncio
async def test_diff_of_a_snapshot_against_itself_is_empty(manager, project_id):
    await manager.commit(project_id, key="k", value={"n": 1})
    snapshot = await manager.create_snapshot(project_id)

    result = await manager.diff(project_id, from_snapshot_id=snapshot.id, to_snapshot_id=snapshot.id)

    assert result["counts"] == {"added": 0, "modified": 0, "removed": 0}
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_diff_marks_a_bounded_response_as_truncated(manager, project_id):
    baseline = await manager.create_snapshot(project_id)
    for index in range(6):
        await manager.commit(project_id, key=f"k{index}", value={"n": index})

    result = await manager.diff(project_id, from_snapshot_id=baseline.id, limit=2)

    assert result["counts"]["added"] == 6
    assert len(result["added"]) == 2
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_diff_rejects_an_oversized_value_bearing_response(manager, project_id, monkeypatch):
    from bilinc.cloud import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "MAX_DIFF_RESPONSE_BYTES", 200)
    baseline = await manager.create_snapshot(project_id)
    await manager.commit(project_id, key="big", value={"blob": "x" * 5000})

    # Redacted diffs stay small and are still answerable.
    assert (await manager.diff(project_id, from_snapshot_id=baseline.id))["counts"]["added"] == 1

    with pytest.raises(ValueError, match="response_too_large"):
        await manager.diff(project_id, from_snapshot_id=baseline.id, include_values=True)


@pytest.mark.asyncio
async def test_diff_cannot_read_another_projects_snapshot(manager):
    project_a = str(uuid4())
    project_b = str(uuid4())
    await manager.commit(project_a, key="k", value={"tenant": "a"})
    snapshot = await manager.create_snapshot(project_a)
    await manager.commit(project_b, key="k", value={"tenant": "b"})

    with pytest.raises(ValueError, match="snapshot_not_found"):
        await manager.diff(project_b, from_snapshot_id=snapshot.id)


@pytest.mark.asyncio
async def test_diff_reports_a_missing_snapshot_as_not_found(manager, project_id):
    with pytest.raises(ValueError, match="snapshot_not_found"):
        await manager.diff(project_id, from_snapshot_id="snap_0000000000000_deadbeefdeadbeef")
