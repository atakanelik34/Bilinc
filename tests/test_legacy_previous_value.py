"""Legacy ``metadata.previous_value`` text is not copied forward, listed or diffed again (item PREV-VAL).

Hosted runtime on SQLite; the Postgres variants run only when BILINC_TEST_POSTGRES_DSN is set.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid

import pytest

from bilinc.core.models import MemoryEntry, MemoryType, strip_reserved_metadata

DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
KINDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set"))]
LEGACY = "Quartz harbor plan: call Dana Whitfield"
VALUE = "current plan text"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_strip_reserved_metadata_keeps_everything_else_and_never_mutates():
    original = {"previous_value": "x", "keep": 1}
    cleaned = strip_reserved_metadata(original)
    assert cleaned == {"keep": 1} and original == {"previous_value": "x", "keep": 1}
    clean = {"keep": 1}
    assert strip_reserved_metadata(clean) is clean  # nothing to strip: no copy
    assert strip_reserved_metadata(None) == {}


def test_a_memory_entry_never_holds_the_reserved_field():
    entry = MemoryEntry(key="k", value="v", memory_type=MemoryType.SEMANTIC, metadata={"previous_value": "x", "keep": 1})
    assert entry.metadata == {"keep": 1}
    rebuilt = MemoryEntry.from_dict(dict(entry.to_dict(), metadata={"previous_value": "y", "other": 2}))
    assert rebuilt.metadata == {"other": 2}


async def _manager(kind, tmp_path, monkeypatch):
    from bilinc.cloud.runtime import ProjectRuntimeManager

    if kind == "postgres":
        monkeypatch.setenv("BILINC_STORAGE_BACKEND", "postgres")
        monkeypatch.setenv("BILINC_POSTGRES_DSN", DSN)
    return ProjectRuntimeManager(tmp_path)


async def _seed_legacy(kind, plane, key):
    """Write the text into the stored row the way a pre-2.6.0 revision did."""
    marker = json.dumps(LEGACY)
    if kind == "sqlite":
        conn = plane.backend._get_conn()
        conn.execute("UPDATE memories SET metadata = json_set(COALESCE(metadata, '{}'), '$.previous_value', ?) WHERE key = ?",
                     (LEGACY, key))
        conn.commit()
    else:
        await plane.backend.pool.execute(
            "UPDATE bilinc_entries SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('previous_value', $1::text) WHERE key = $2",
            LEGACY, key)
    assert marker  # the seeded text is what the assertions look for


async def _stored_metadata(kind, plane, key):
    if kind == "sqlite":
        row = plane.backend._get_conn().execute("SELECT metadata FROM memories WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0] or "{}")
    raw = await plane.backend.pool.fetchval("SELECT metadata FROM bilinc_entries WHERE key = $1", key)
    return json.loads(raw) if isinstance(raw, str) else dict(raw or {})


async def _everything_written(kind, plane):
    """All text the project now holds in entries, audit and events."""
    parts = []
    if kind == "sqlite":
        conn = plane.backend._get_conn()
        for table in ("memories", "audit_log", "memory_events"):
            parts += [" ".join(map(str, row)) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]
    else:
        for table in ("bilinc_entries", "audit_log", "memory_events"):
            parts += [" ".join(map(str, dict(row).values())) for row in await plane.backend.pool.fetch(f"SELECT * FROM {table}")]
    return "\n".join(parts)


@pytest.mark.parametrize("kind", KINDS)
def test_commit_of_a_new_key_with_the_reserved_field_drops_it(kind, tmp_path, monkeypatch):
    async def go():
        manager = await _manager(kind, tmp_path, monkeypatch)
        project = str(uuid.uuid4())
        await manager.commit(project, key="plan", value=VALUE, importance=1.0,
                             metadata={"previous_value": LEGACY, "keep": "yes"})
        plane = await manager.get_plane(project)
        stored = await _stored_metadata(kind, plane, "plan")
        text = await _everything_written(kind, plane)
        await manager.close()
        return stored, text

    stored, text = _run(go())
    assert "previous_value" not in stored and stored.get("keep") == "yes"
    assert "Dana Whitfield" not in text


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("action", ["confirm", "same_value_revise"])
def test_a_rewrite_of_a_legacy_row_persists_it_clean(kind, action, tmp_path, monkeypatch):
    async def go():
        manager = await _manager(kind, tmp_path, monkeypatch)
        project = str(uuid.uuid4())
        await manager.commit(project, key="plan", value=VALUE, importance=1.0)
        plane = await manager.get_plane(project)
        await _seed_legacy(kind, plane, "plan")
        text_before = await _everything_written(kind, plane)
        if action == "confirm":
            await manager.confirm(project, key="plan", reason="still true")
        else:
            await manager.revise(project, key="plan", value=VALUE, importance=1.0, reason="same")
        stored = await _stored_metadata(kind, plane, "plan")
        text_after = await _everything_written(kind, plane)
        await manager.close()
        return stored, text_before, text_after

    stored, before, after = _run(go())
    assert "Dana Whitfield" in before  # the seed is really there
    assert "previous_value" not in stored
    # nothing the rewrite wrote (row, audit, event) carries the text again
    assert "Dana Whitfield" not in after


def _inject_legacy_into_snapshot(manager, project, snapshot_id, key):
    path = manager.snapshot_dir(project) / f"{snapshot_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    entry = payload["snapshot"]["entries"][key]
    entry["metadata"] = dict(entry.get("metadata") or {}, previous_value=LEGACY)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


async def _row_count(kind, plane, table):
    if kind == "sqlite":
        return plane.backend._get_conn().execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return await plane.backend.pool.fetchval(f"SELECT count(*) FROM {table}")


async def _project_with_legacy_snapshot(kind, tmp_path, monkeypatch):
    manager = await _manager(kind, tmp_path, monkeypatch)
    project = str(uuid.uuid4())
    await manager.commit(project, key="plan", value=VALUE, importance=1.0)
    await manager.commit(project, key="other", value="other value", importance=1.0)
    snapshot = await manager.create_snapshot(project, label="old")
    _inject_legacy_into_snapshot(manager, project, snapshot.id, "plan")
    return manager, project, snapshot.id


@pytest.mark.parametrize("kind", KINDS)
def test_rollback_preview_and_execute_ignore_the_legacy_field(kind, tmp_path, monkeypatch):
    async def go():
        manager, project, snapshot_id = await _project_with_legacy_snapshot(kind, tmp_path, monkeypatch)
        preview = await manager.rollback_preview(project, snapshot_id=snapshot_id)
        plane = await manager.get_plane(project)
        before = (await _row_count(kind, plane, "audit_log"), await _row_count(kind, plane, "memory_events"))
        await manager.rollback_execute(
            project, snapshot_id=snapshot_id, reason="test", expected_current_root=preview["current_root_hash"])
        after = (await _row_count(kind, plane, "audit_log"), await _row_count(kind, plane, "memory_events"))
        text = await _everything_written(kind, plane)
        await manager.close()
        return preview, before, after, text

    preview, before, after, text = _run(go())
    assert preview["counts"] == {"create": 0, "update": 0, "remove": 0} and preview["update_keys"] == []
    # only the rollback's own audit marker is added; no key was rewritten (no UPDATE row, no event)
    assert after == (before[0] + 1, before[1])
    assert "Dana Whitfield" not in text


@pytest.mark.parametrize("kind", KINDS)
def test_hosted_diff_ignores_the_legacy_field_in_every_mode(kind, tmp_path, monkeypatch):
    async def go():
        manager, project, snapshot_id = await _project_with_legacy_snapshot(kind, tmp_path, monkeypatch)
        newer = await manager.create_snapshot(project, label="newer")  # same content, clean
        to_current = await manager.diff(project, from_snapshot_id=snapshot_id)
        to_snapshot = await manager.diff(project, from_snapshot_id=snapshot_id, to_snapshot_id=newer.id)
        await manager.close()
        return to_current, to_snapshot

    to_current, to_snapshot = _run(go())
    assert to_current["counts"]["modified"] == 0 and to_snapshot["counts"]["modified"] == 0


@pytest.mark.parametrize("kind", KINDS)
def test_the_version_token_of_a_legacy_row_changes_once_and_then_holds(kind, tmp_path, monkeypatch):
    from bilinc.cloud.runtime import entry_version

    async def go():
        manager = await _manager(kind, tmp_path, monkeypatch)
        project = str(uuid.uuid4())
        await manager.commit(project, key="plan", value=VALUE, importance=1.0)
        plane = await manager.get_plane(project)
        clean = (await plane.backend.load("plan")).to_dict()
        # the token a client read before the deploy: computed from the legacy stored state
        old_token = entry_version(dict(clean, metadata=dict(clean["metadata"], previous_value=LEGACY)))
        with pytest.raises(ValueError, match="version_conflict"):
            await manager.confirm(project, key="plan", expected_version=old_token)
        fresh = await manager._entry_version(plane, "plan")
        assert fresh == await manager._entry_version(plane, "plan")  # stable across reads
        confirmed = await manager.confirm(project, key="plan", expected_version=fresh)
        await manager.close()
        return confirmed

    assert _run(go())["success"] is True


async def _plane_with_stored_plan(kind, tmp_path, monkeypatch):
    manager = await _manager(kind, tmp_path, monkeypatch)
    project = str(uuid.uuid4())
    await manager.commit(project, key="plan", value=VALUE, importance=1.0)
    plane = await manager.get_plane(project)
    clean = (await plane.backend.load("plan")).to_dict()
    legacy = dict(clean, metadata=dict(clean["metadata"], previous_value=LEGACY))
    return manager, plane, clean, legacy


@pytest.mark.parametrize("kind", KINDS)
def test_local_diff_hides_the_legacy_field_and_drops_a_pure_removal(kind, tmp_path, monkeypatch):
    import time

    from bilinc.core.audit import OpType

    async def go():
        manager, plane, clean, legacy = await _plane_with_stored_plan(kind, tmp_path, monkeypatch)
        ghost_clean = dict(clean, key="ghost")
        ghost_legacy = dict(legacy, key="ghost")
        t0 = time.time()
        time.sleep(0.02)
        plane.audit.log(OpType.CREATE, "ghost", after_value=ghost_legacy)
        time.sleep(0.02)
        t1 = time.time()
        time.sleep(0.02)
        plane.audit.log(OpType.UPDATE, "ghost", before_value=ghost_legacy, after_value=ghost_clean)
        time.sleep(0.02)
        t2 = time.time()
        added = await plane.diff(t0, t1)
        pure_removal = await plane.diff(t1, t2)
        integrity = plane.audit.verify_integrity()
        raw = await _everything_written(kind, plane)
        await manager.close()
        return added, pure_removal, integrity, raw

    added, pure_removal, integrity, raw = _run(go())
    assert any(item["key"] == "ghost" for item in added["added"])
    assert "Dana Whitfield" not in json.dumps(added, default=str)
    assert pure_removal["modified"] == [] and pure_removal["counts"]["modified"] == 0
    assert "Dana Whitfield" in raw  # the audit rows themselves are untouched ...
    assert integrity["valid"] is True  # ... so the chain still verifies


@pytest.mark.parametrize("kind", KINDS)
def test_local_rollback_does_not_rewrite_a_key_that_only_differs_by_the_legacy_field(kind, tmp_path, monkeypatch):
    import time

    from bilinc.core.audit import OpType

    async def go():
        manager, plane, clean, legacy = await _plane_with_stored_plan(kind, tmp_path, monkeypatch)
        time.sleep(0.02)
        plane.audit.log(OpType.UPDATE, "plan", before_value=clean, after_value=legacy)
        time.sleep(0.02)
        target = time.time()
        before = (await _row_count(kind, plane, "audit_log"), await _row_count(kind, plane, "memory_events"))
        result = await plane.rollback(target)
        after = (await _row_count(kind, plane, "audit_log"), await _row_count(kind, plane, "memory_events"))
        stored = await _stored_metadata(kind, plane, "plan")
        await manager.close()
        return result, before, after, stored

    result, before, after, stored = _run(go())
    assert after == (before[0] + 1, before[1])  # only the rollback's own marker; nothing rewritten
    assert "previous_value" not in stored
