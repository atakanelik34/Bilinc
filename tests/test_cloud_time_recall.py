"""Cloud recall routes time questions through the time-window path."""

import os
from uuid import uuid4

import pytest

from bilinc.cloud.project_settings import SETTINGS_FILE, ProjectSettings, save_project_settings
from bilinc.cloud.runtime import ProjectRuntimeManager

LOW = "sample-chat-transcript"


def _settings(manager, project, **kwargs):
    save_project_settings(manager.project_dir(project), ProjectSettings(**kwargs))


async def _seed(manager, project):
    await manager.commit(project, key="decision.today", value="ship 2.6.2", source="agent")
    await manager.commit(project, key="chat.today", value="small talk", source=LOW)


@pytest.mark.asyncio
async def test_cloud_recall_routes_today_and_skips_low_signal(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid4())
    _settings(manager, project, timezone="UTC", low_signal_sources=(LOW,))
    await _seed(manager, project)
    payload = await manager.recall(project, query="what changed today", profile="balanced", limit=10)
    assert [r["key"] for r in payload["results"]] == ["decision.today"]
    assert payload["routed"] == "time_window"
    assert payload["results"][0]["entry_version"]
    assert "state_version" in payload
    assert payload["time_window"]["timezone"] == "UTC"
    await manager.close()


@pytest.mark.asyncio
async def test_cloud_recall_non_time_query_is_unchanged(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid4())
    await manager.commit(project, key="pricing.plan", value="Pro is 15 dollars", source="agent")
    payload = await manager.recall(project, query="pricing plan", profile="balanced", limit=5)
    assert "routed" not in payload
    assert "time_window" not in payload
    assert payload["results"][0]["key"] == "pricing.plan"
    await manager.close()


@pytest.mark.asyncio
async def test_query_timestamp_is_never_routed(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid4())
    await manager.commit(project, key="k", value="v")
    payload = await manager.recall(project, query="today", profile="balanced", query_timestamp="2030-01-01T00:00:00Z")
    assert "routed" not in payload
    await manager.close()


@pytest.mark.asyncio
async def test_invalid_zone_in_settings_falls_back_to_utc(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid4())
    await _seed(manager, project)
    directory = manager.project_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / SETTINGS_FILE).write_text('{"timezone": "Mars/Olympus", "low_signal_sources": []}')
    payload = await manager.recall(project, query="what changed today", profile="balanced", limit=10)
    assert payload["routed"] == "time_window"
    assert payload["time_window"]["timezone"] == "UTC"
    await manager.close()


@pytest.mark.asyncio
async def test_corrupt_settings_do_not_break_recall(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid4())
    await _seed(manager, project)
    directory = manager.project_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / SETTINGS_FILE).write_text("{not json")
    payload = await manager.recall(project, query="what changed today", profile="balanced", limit=10)
    assert payload["routed"] == "time_window"
    assert payload["time_window"]["timezone"] == "UTC"
    await manager.close()


@pytest.mark.asyncio
async def test_verified_profile_routed_has_evidence(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid4())
    await _seed(manager, project)
    payload = await manager.recall(project, query="what changed today", profile="verified", limit=10)
    assert payload["routed"] == "time_window"
    assert "evidence" in payload
    await manager.close()


@pytest.mark.asyncio
async def test_explain_on_routed_query_reports_unsupported(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid4())
    await _seed(manager, project)
    payload = await manager.recall(project, query="what changed today", profile="balanced", limit=10, explain=True)
    assert payload["routed"] == "time_window"
    assert payload["explain_supported"] is False
    await manager.close()


@pytest.mark.asyncio
async def test_memory_types_filter_applies_when_routed(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid4())
    await manager.commit(project, key="sem.k", value="semantic fact", memory_type="semantic", source="agent")
    await manager.commit(project, key="epi.k", value="episodic event", memory_type="episodic", source="agent")
    await manager.commit(project, key="proc.k", value="procedural step", memory_type="procedural", source="agent")
    payload = await manager.recall(
        project, query="what changed today", profile="balanced", limit=10, memory_types=["semantic", "episodic"]
    )
    assert payload["routed"] == "time_window"
    assert {r["key"] for r in payload["results"]} == {"sem.k", "epi.k"}
    await manager.close()


@pytest.mark.asyncio
async def test_query_naming_low_signal_includes_it(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid4())
    _settings(manager, project, timezone="UTC", low_signal_sources=(LOW,))
    await _seed(manager, project)
    payload = await manager.recall(project, query="chat transcripts today", profile="balanced", limit=10)
    assert payload["routed"] == "time_window"
    assert "chat.today" in {r["key"] for r in payload["results"]}
    await manager.close()


@pytest.mark.asyncio
async def test_implicit_query_with_topic_outside_window_falls_back(tmp_path):
    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid4())
    plane = await manager.get_plane(project)
    from bilinc.core.models import MemoryEntry, MemoryType
    import time

    await plane.backend.restore(
        MemoryEntry(
            key="zebrafish.note",
            value="zebrafish migration finished",
            memory_type=MemoryType.SEMANTIC,
            created_at=time.time() - 30 * 86400,
            updated_at=time.time() - 30 * 86400,
        )
    )
    payload = await manager.recall(project, query="what changed in zebrafish", profile="balanced", limit=10)
    assert "routed" not in payload
    assert "zebrafish.note" in {r["key"] for r in payload["results"]}
    await manager.close()


_DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")


@pytest.mark.skipif(not _DSN, reason="BILINC_TEST_POSTGRES_DSN not set")
@pytest.mark.asyncio
async def test_cloud_recall_routes_today_on_postgres(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("BILINC_POSTGRES_DSN", _DSN)
    monkeypatch.delenv("BILINC_CLOUD_EMBEDDINGS", raising=False)
    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid4())
    try:
        _settings(manager, project, timezone="UTC", low_signal_sources=(LOW,))
        await _seed(manager, project)
        payload = await manager.recall(project, query="what changed today", profile="balanced", limit=10)
        assert [r["key"] for r in payload["results"]] == ["decision.today"]
        assert payload["routed"] == "time_window"
        assert payload["results"][0]["entry_version"]
        assert "state_version" in payload
    finally:
        await manager.close()
