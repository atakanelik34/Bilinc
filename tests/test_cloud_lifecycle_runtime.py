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
