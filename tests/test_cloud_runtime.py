from uuid import uuid4

import pytest

from bilinc.cloud.runtime import ProjectRuntimeManager


@pytest.mark.asyncio
async def test_project_runtime_uses_separate_physical_databases(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project_a = str(uuid4())
    project_b = str(uuid4())

    await manager.commit(project_a, key="agent.memory", value={"tenant": "a"})
    await manager.commit(project_b, key="agent.memory", value={"tenant": "b"})

    recall_a = await manager.recall(project_a, query="tenant", profile="balanced")
    recall_b = await manager.recall(project_b, query="tenant", profile="balanced")

    assert [item["value"] for item in recall_a["results"]] == [{"tenant": "a"}]
    assert [item["value"] for item in recall_b["results"]] == [{"tenant": "b"}]
    assert manager.db_path(project_a) != manager.db_path(project_b)
    assert manager.db_path(project_a).exists()
    assert manager.db_path(project_b).exists()

    await manager.close()


@pytest.mark.asyncio
async def test_project_runtime_persists_snapshots_per_project(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project_id = str(uuid4())

    await manager.commit(project_id, key="agent.memory", value={"state": "ready"})
    snapshot = await manager.create_snapshot(project_id)
    listed = await manager.list_snapshots(project_id)

    assert snapshot.total_entries == 1
    assert listed[0].id == snapshot.id
    assert listed[0].root_hash == snapshot.root_hash

    await manager.close()


@pytest.mark.asyncio
async def test_commit_carries_the_hermes_provenance_contract(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project_id = str(uuid4())

    result = await manager.commit(
        project_id,
        key="agent.memory",
        value={"state": "ready"},
        metadata={"team": "core"},
        source="hermes_session",
        session_id="sess-1",
        canonical=True,
        priority=0.9,
    )

    plane = await manager.get_plane(project_id)
    stored = await plane.backend.load("agent.memory")

    assert result["success"] is True
    assert stored.source == "hermes_session"
    assert stored.session_id == "sess-1"
    assert stored.metadata["team"] == "core"
    assert stored.metadata["canonical"] is True
    assert stored.metadata["priority"] == 0.9

    await manager.close()


@pytest.mark.asyncio
async def test_commit_returns_an_opaque_version_that_changes_with_the_entry(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project_id = str(uuid4())

    first = await manager.commit(project_id, key="k", value={"n": 1})
    second = await manager.commit(project_id, key="k", value={"n": 2})

    assert first["entry_version"].startswith("v1_")
    assert first["entry_version"] != second["entry_version"]
    # The version must not leak a timestamp or a monotonic counter.
    assert not first["entry_version"][3:].isdigit()

    await manager.close()


@pytest.mark.asyncio
async def test_recall_rejects_an_unknown_memory_type(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project_id = str(uuid4())

    with pytest.raises(ValueError, match="invalid_memory_type"):
        await manager.recall(project_id, query="anything", profile="fast", memory_types=["dreams"])

    await manager.close()


def test_project_runtime_rejects_non_uuid_project_ids(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)

    with pytest.raises(ValueError, match="invalid_project_id"):
        manager.project_dir("../../escape")
