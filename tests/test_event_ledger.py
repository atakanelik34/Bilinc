import json
import sqlite3

import pytest

from bilinc.core import MemoryType, StatePlane
from bilinc.core.event_ledger import EventOperation, export_events_jsonl, replay_events_summary
from bilinc.storage.sqlite import SQLiteBackend


async def _plane(tmp_path):
    db_path = tmp_path / "ledger.db"
    backend = SQLiteBackend(str(db_path))
    await backend.init()
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    return plane, backend, db_path


@pytest.mark.asyncio
async def test_sqlite_event_table_is_idempotent_and_commit_emits_scrubbed_event(tmp_path):
    plane, backend, db_path = await _plane(tmp_path)
    await backend.init()  # idempotent schema creation must be safe

    entry = await plane.commit(
        "ledger:commit",
        {"safe": "keep", "token": "TOKEN_SAMPLE"},
        memory_type=MemoryType.SEMANTIC,
        metadata={"request_id": "req-1", "api_key": "API_KEY_SAMPLE"},
    )

    await plane.commit(
        "ledger:commit",
        {"safe": "keep-updated"},
        memory_type=MemoryType.SEMANTIC,
        metadata={"request_id": "req-2"},
    )

    events = await backend.list_memory_events()
    assert len(events) == 2
    event = events[0]
    revised = events[1]
    assert event.operation == EventOperation.COMMIT.value
    assert event.type == "bilinc.memory.committed"
    assert event.memory_key == entry.key
    assert event.memory_type == "semantic"
    assert event.subject == "ledger:commit"
    dumped = json.dumps(event.to_dict(), sort_keys=True)
    assert "TOKEN_SAMPLE" not in dumped
    assert "API_KEY_SAMPLE" not in dumped
    assert "[REDACTED]" in dumped
    assert event.event_hash
    assert revised.operation == EventOperation.REVISE.value
    assert revised.type == "bilinc.memory.revised"
    assert revised.before_hash
    assert revised.after_hash
    assert revised.prev_event_hash == event.event_hash

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0]
    assert count == 2


@pytest.mark.asyncio
async def test_forget_snapshot_and_replay_summary_are_read_only_and_deterministic(tmp_path):
    plane, backend, _ = await _plane(tmp_path)
    await plane.commit("ledger:forget", "temporary", memory_type=MemoryType.WORKING)
    await plane.forget("ledger:forget")
    before_snapshot_event_count = len(await backend.list_memory_events())

    snapshot = await plane.snapshot()
    events = await backend.list_memory_events()
    after_snapshot_event_count = len(events)

    assert [event.operation for event in events] == [
        EventOperation.COMMIT.value,
        EventOperation.FORGET.value,
        EventOperation.SNAPSHOT.value,
    ]
    tombstone = events[1]
    assert tombstone.type == "bilinc.memory.forgotten"
    assert tombstone.payload_json["deleted"] is True
    checkpoint = events[2]
    assert checkpoint.checkpoint_root == snapshot.get("root_hash")
    assert after_snapshot_event_count == before_snapshot_event_count + 1

    exported = export_events_jsonl(events)
    summary_a = replay_events_summary(exported)
    summary_b = replay_events_summary(exported)
    assert summary_a == summary_b
    assert summary_a["event_count"] == 3
    assert summary_a["operation_counts"]["commit"] == 1
    assert summary_a["operation_counts"]["forget"] == 1
    assert summary_a["operation_counts"]["snapshot"] == 1

    assert len(await backend.list_memory_events()) == after_snapshot_event_count


@pytest.mark.asyncio
async def test_manual_append_rejects_missing_operation_subject_and_preserves_hash_chain(tmp_path):
    _plane_obj, backend, _ = await _plane(tmp_path)

    with pytest.raises(ValueError):
        await backend.append_memory_event(operation="", subject="", payload_json={})

    first = await backend.append_memory_event(
        operation=EventOperation.EVAL_RECEIPT.value,
        subject="receipt-1",
        payload_json={"note": "first"},
    )
    # Simulate wall-clock skew after append. The next event must still chain to append order, not max(time).
    backend._get_conn().execute("UPDATE memory_events SET time = time + 100000 WHERE id = ?", (first.id,))
    backend._get_conn().commit()
    second = await backend.append_memory_event(
        operation=EventOperation.EVAL_RECEIPT.value,
        subject="receipt-2",
        payload_json={"note": "second"},
    )

    assert second.prev_event_hash == first.event_hash
    assert second.event_hash != first.event_hash
    events = await backend.list_memory_events()
    assert [event.subject for event in events] == ["receipt-1", "receipt-2"]


@pytest.mark.asyncio
async def test_commit_with_agm_fallback_overwrite_emits_revise_event(tmp_path):
    _plane_obj, backend, _ = await _plane(tmp_path)
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()

    first = await plane.commit_with_agm_async("ledger:agm", "v1", memory_type="semantic")
    second = await plane.commit_with_agm_async("ledger:agm", "v2", memory_type="semantic")

    assert first.key == "ledger:agm"
    assert second.key == "ledger:agm"
    events = await backend.list_memory_events(memory_key="ledger:agm")
    assert [event.operation for event in events] == [EventOperation.COMMIT.value, EventOperation.REVISE.value]
    assert events[1].before_hash
    assert events[1].after_hash
