import json
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


@pytest.mark.asyncio
async def test_snapshot_ids_are_collision_resistant(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project_id = str(uuid4())
    await manager.commit(project_id, key="k", value=1)

    ids = {(await manager.create_snapshot(project_id)).id for _ in range(5)}

    assert len(ids) == 5, "timestamp-derived ids let same-instant snapshots overwrite each other"
    assert all(snapshot_id.startswith("snap_") for snapshot_id in ids)
    assert len(await manager.list_snapshots(project_id, limit=10)) == 5

    await manager.close()


@pytest.mark.asyncio
async def test_snapshots_carry_label_and_metadata(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project_id = str(uuid4())
    await manager.commit(project_id, key="k", value=1)

    created = await manager.create_snapshot(
        project_id, label="before-refactor", metadata={"agent": "planner"}
    )
    listed = await manager.list_snapshots(project_id)

    assert created.label == "before-refactor"
    assert listed[0].metadata == {"agent": "planner"}

    await manager.close()


@pytest.mark.asyncio
async def test_legacy_timestamp_named_snapshots_stay_listable(tmp_path):
    """Snapshots written before the id change must not disappear from listings."""
    manager = ProjectRuntimeManager(tmp_path)
    project_id = str(uuid4())
    await manager.commit(project_id, key="k", value=1)
    await manager.create_snapshot(project_id)

    directory = manager.snapshot_dir(project_id)
    legacy_id = "1753000000.123456"
    (directory / f"{legacy_id}.json").write_text(
        json.dumps(
            {
                "id": legacy_id,
                "created_at": 1753000000.123456,
                "total_entries": 1,
                "by_type": {"semantic": 1},
                "root_hash": "legacy_root",
                "snapshot": {"entries": {}},
            }
        ),
        encoding="utf-8",
    )

    listed = await manager.list_snapshots(project_id, limit=10)

    assert legacy_id in {snapshot.id for snapshot in listed}
    # Newest first, regardless of naming scheme.
    assert listed[0].created_at >= listed[-1].created_at
    assert (await manager.load_snapshot(project_id, legacy_id))["root_hash"] == "legacy_root"

    await manager.close()


@pytest.mark.asyncio
async def test_a_corrupted_snapshot_file_does_not_break_listing(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project_id = str(uuid4())
    await manager.commit(project_id, key="k", value=1)
    good = await manager.create_snapshot(project_id)
    (manager.snapshot_dir(project_id) / "broken.json").write_text("{not json", encoding="utf-8")

    listed = await manager.list_snapshots(project_id, limit=10)

    assert [snapshot.id for snapshot in listed] == [good.id]
    with pytest.raises(ValueError, match="snapshot_unreadable"):
        await manager.load_snapshot(project_id, "broken")

    await manager.close()


@pytest.mark.asyncio
async def test_a_snapshot_from_another_project_is_simply_not_found(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project_a = str(uuid4())
    project_b = str(uuid4())
    await manager.commit(project_a, key="k", value=1)
    snapshot = await manager.create_snapshot(project_a)

    await manager.commit(project_b, key="k", value=1)

    with pytest.raises(ValueError, match="snapshot_not_found"):
        await manager.load_snapshot(project_b, snapshot.id)

    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile_id",
    ["../../../etc/passwd", "..", "a/b", "", "x" * 200],
)
async def test_snapshot_ids_cannot_escape_the_project_directory(tmp_path, hostile_id):
    manager = ProjectRuntimeManager(tmp_path)
    project_id = str(uuid4())

    with pytest.raises(ValueError, match="snapshot_not_found"):
        await manager.load_snapshot(project_id, hostile_id)

    await manager.close()


def test_project_runtime_rejects_non_uuid_project_ids(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)

    with pytest.raises(ValueError, match="invalid_project_id"):
        manager.project_dir("../../escape")
