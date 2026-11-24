"""IMP-006: guarantees a task board built on memory entries relies on (hosted runtime, one process).

Characterization tests: each pins one behaviour of the existing write and list calls on 29ed56d; none adds a
feature. Every test runs on SQLite and on Postgres. A failure is a finding about the recipe in
docs/superpowers/specs/2026-11-24-imp-006-task-claim-announce-design.md, not a test to loosen.
"""

from __future__ import annotations

import asyncio
import os
import time
from uuid import uuid4

import pytest

from bilinc.cloud.runtime import ProjectRuntimeManager
from bilinc.core.models import MemoryEntry, MemoryType

TASK = "coord:demo:task:t1"
ANNOUNCE = "coord:demo:announce:"

_DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
BACKENDS = [
    "sqlite",
    pytest.param("postgres", marks=pytest.mark.skipif(not _DSN, reason="BILINC_TEST_POSTGRES_DSN not set")),
]


@pytest.fixture(params=BACKENDS)
def manager(request, tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_STORAGE_BACKEND", request.param)
    monkeypatch.delenv("BILINC_CLOUD_EMBEDDINGS", raising=False)
    if request.param == "postgres":
        monkeypatch.setenv("BILINC_POSTGRES_DSN", _DSN)
    return ProjectRuntimeManager(tmp_path)


async def _outcome(call):
    """"won", "refused" (accepted call, success False) or the runtime's error code."""
    try:
        result = await call
    except ValueError as exc:
        return str(exc), None
    return ("won" if result["success"] else "refused"), result


async def _listed(manager, project_id, prefix, **kwargs):
    return (await manager.list_memories(project_id, prefix=prefix, **kwargs))["entries"]


# E1 ---------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_one_of_many_concurrent_create_only_commits_wins(manager):
    project_id = str(uuid4())
    try:
        outcomes = await asyncio.gather(*[
            _outcome(manager.commit(project_id, key=TASK, value={"owner": f"agent-{n}"}, if_absent=True))
            for n in range(25)
        ])
        assert sorted(code for code, _ in outcomes) == ["memory_exists"] * 24 + ["won"]
        stored = (await _listed(manager, project_id, TASK, values="full"))[0]
        winner_index = [code for code, _ in outcomes].index("won")
        assert stored["value"] == {"owner": f"agent-{winner_index}"}
    finally:
        await manager.close()


# E2 + E3 ----------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_one_of_many_concurrent_version_checked_revisions_wins(manager):
    project_id = str(uuid4())
    try:
        created = await manager.commit(project_id, key=TASK, value={"state": "open", "owner": None}, if_absent=True)
        outcomes = await asyncio.gather(*[
            _outcome(manager.revise(
                project_id, key=TASK, value={"state": "claimed", "owner": f"agent-{n}"},
                expected_version=created["entry_version"], strategy="recency", reason=f"claim by agent-{n}",
            ))
            for n in range(25)
        ])
        assert sorted(code for code, _ in outcomes) == ["version_conflict"] * 24 + ["won"]
        winner = next(result for code, result in outcomes if code == "won")
        listed = (await _listed(manager, project_id, TASK, values="full"))[0]
        assert listed["entry_version"] == winner["entry_version"]       # both taken after the save
        assert listed["value"]["state"] == "claimed"
    finally:
        await manager.close()


# E7 ---------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_heartbeat_moves_the_version_so_an_older_read_cannot_take_over(manager):
    project_id = str(uuid4())
    try:
        created = await manager.commit(project_id, key=TASK, value={"state": "claimed", "owner": "agent-1"},
                                       if_absent=True)
        before = (await _listed(manager, project_id, TASK))[0]
        beat = await manager.confirm(project_id, key=TASK, expected_version=created["entry_version"],
                                     reason="heartbeat")
        assert beat["entry_version"] != created["entry_version"]
        assert beat["updated_at"] >= before["updated_at"]
        with pytest.raises(ValueError, match="version_conflict"):
            await manager.revise(project_id, key=TASK, value={"state": "claimed", "owner": "agent-2"},
                                 expected_version=created["entry_version"], strategy="recency")
        after = (await _listed(manager, project_id, TASK, values="full"))[0]
        assert after["value"]["owner"] == "agent-1"
        assert after["entry_version"] == beat["entry_version"]
    finally:
        await manager.close()


# E3 ---------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reads_do_not_move_the_version(manager):
    project_id = str(uuid4())
    try:
        created = await manager.commit(project_id, key=TASK, value={"state": "open", "note": "pick me"},
                                       if_absent=True)
        await manager.recall(project_id, query="pick me", profile="balanced")
        await manager.history(project_id, key=TASK)
        listed = (await _listed(manager, project_id, TASK))[0]
        assert listed["entry_version"] == created["entry_version"]
    finally:
        await manager.close()


# G2 ---------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_state_change_needs_the_recency_strategy_when_importance_drops(manager):
    project_id = str(uuid4())
    try:
        await manager.commit(project_id, key=TASK, value={"state": "open"}, importance=1.0, if_absent=True)
        refused = await manager.revise(project_id, key=TASK, value={"state": "done"}, importance=0.5)
        accepted = await manager.revise(project_id, key=TASK, value={"state": "done"}, importance=0.5,
                                        strategy="recency")
        # The default strategy answers without an error; a caller has to read ``success``.
        assert refused["success"] is False
        assert accepted["success"] is True
    finally:
        await manager.close()


# E5 ---------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_an_announcement_feed_reads_newest_first_and_pages_by_cursor(manager):
    project_id = str(uuid4())
    try:
        await manager.commit(project_id, key="coord:demo:task:t9", value={"state": "open"}, if_absent=True)
        for n in range(5):
            await manager.commit(project_id, key=f"{ANNOUNCE}{n:03d}", value=f"note {n}", if_absent=True)
        first = await manager.list_memories(project_id, prefix=ANNOUNCE, order="newest", limit=2, values="full")
        await manager.commit(project_id, key="coord:demo:note:t9:x", value="lands meanwhile", if_absent=True)
        second = await manager.list_memories(project_id, prefix=ANNOUNCE, order="newest", limit=2,
                                             cursor=first["next_cursor"])
        seen = first["entries"][-1]["updated_at"]
        newer = await manager.list_memories(project_id, prefix=ANNOUNCE, order="newest", updated_after=seen)
        assert [entry["key"] for entry in first["entries"]] == [f"{ANNOUNCE}004", f"{ANNOUNCE}003"]
        assert [entry["key"] for entry in second["entries"]] == [f"{ANNOUNCE}002", f"{ANNOUNCE}001"]
        assert first["total"] == 5
        assert [entry["key"] for entry in newer["entries"]] == [f"{ANNOUNCE}004"]
    finally:
        await manager.close()


# E6 ---------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_history_records_create_claim_and_heartbeat_in_order(manager):
    project_id = str(uuid4())
    try:
        created = await manager.commit(project_id, key=TASK, value={"state": "open"}, if_absent=True)
        claimed = await manager.revise(project_id, key=TASK, value={"state": "claimed", "owner": "a"},
                                       expected_version=created["entry_version"], strategy="recency",
                                       reason="claim by a")
        await manager.confirm(project_id, key=TASK, expected_version=claimed["entry_version"], reason="heartbeat")
        rows = list(reversed((await manager.history(project_id, key=TASK))["entries"]))   # oldest first
        assert [(row["op"], row.get("reason")) for row in rows] == [
            ("create", None), ("update", "claim by a"), ("confirm", "heartbeat"),
        ]
    finally:
        await manager.close()


# Task ids are never reused ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_forgotten_task_key_can_be_created_again(manager):
    project_id = str(uuid4())
    try:
        await manager.commit(project_id, key=TASK, value={"state": "done"}, if_absent=True)
        await manager.forget(project_id, key=TASK, reason="cleanup")
        again = await manager.commit(project_id, key=TASK, value={"state": "open"}, if_absent=True)
        assert again["success"] is True                                # why the recipe never reuses an id
    finally:
        await manager.close()


# G13 --------------------------------------------------------------------------------------------
async def _same_stamp_announcements(manager, project_id, stamp):
    await manager.commit(project_id, key="coord:demo:task:t0", value={"state": "open"}, if_absent=True)
    plane = await manager.get_plane(project_id)
    for name in ("a", "b"):
        await plane.backend.restore(MemoryEntry(
            key=f"{ANNOUNCE}{name}", value=f"announce {name}", memory_type=MemoryType.SEMANTIC,
            importance=1.0, created_at=stamp, updated_at=stamp,
        ))
    return plane


@pytest.mark.asyncio
async def test_updated_after_is_a_strict_bound(manager):
    project_id = str(uuid4())
    stamp = time.time() - 60
    try:
        await _same_stamp_announcements(manager, project_id, stamp)
        listed = await _listed(manager, project_id, ANNOUNCE, order="newest", updated_after=stamp)
        assert listed == []                                             # neither record is after the bound
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_the_tie_safe_feed_rule_finds_a_same_stamp_record(manager):
    project_id = str(uuid4())
    earlier, stamp = time.time() - 120, time.time() - 60
    try:
        plane = await _same_stamp_announcements(manager, project_id, stamp)
        await plane.backend.restore(MemoryEntry(
            key=f"{ANNOUNCE}0", value="earliest", memory_type=MemoryType.SEMANTIC, importance=1.0,
            created_at=earlier, updated_at=earlier,
        ))
        # A reader saw "0" and "a" (two distinct stamps, earlier and stamp), not yet "b".
        seen = {f"{ANNOUNCE}0", f"{ANNOUNCE}a"}
        naive = await _listed(manager, project_id, ANNOUNCE, order="newest", updated_after=stamp)
        tie_safe = await _listed(manager, project_id, ANNOUNCE, order="newest", updated_after=earlier)
        assert [entry["key"] for entry in naive] == []                  # the naive rule loses "b"
        assert [entry["key"] for entry in tie_safe if entry["key"] not in seen] == [f"{ANNOUNCE}b"]
    finally:
        await manager.close()
