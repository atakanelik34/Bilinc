import json
import time

import pytest

from bilinc.core.stateplane import StatePlane
from bilinc.core.models import MemoryType
from bilinc.eval.capture import (
    EvalCaptureRow,
    capture_enabled,
    row_from_jsonl,
    row_from_results,
    row_to_jsonl,
    scrub_detail,
    scrub_query,
)
from bilinc.mcp_server.server_v2 import _handle_bilinc_recall_smart
from bilinc.storage.sqlite import SQLiteBackend


async def make_temp_plane(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "test.db"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()
    return plane


def test_eval_capture_disabled_by_default(monkeypatch):
    monkeypatch.delenv("BILINC_EVAL_CAPTURE", raising=False)

    assert capture_enabled() is False


def test_eval_capture_enabled_by_env(monkeypatch):
    monkeypatch.setenv("BILINC_EVAL_CAPTURE", "1")

    assert capture_enabled() is True


def test_eval_capture_scrubs_secret_like_values():
    query = "use sk-live-secret tp-provider-token ghp_abcd1234abcd1234abcd1234abcd1234abcd1234 bearer abcdef0123456789abcdef0123456789"

    scrubbed = scrub_query(query)

    assert "sk-live-secret" not in scrubbed
    assert "tp-provider-token" not in scrubbed
    assert "ghp_" not in scrubbed
    assert "abcdef0123456789abcdef0123456789" not in scrubbed
    assert scrubbed.count("[REDACTED]") >= 4


def test_eval_capture_scrubs_nested_detail_values():
    detail = scrub_detail({"queries_tried": ["ask tp-secret-token", {"bearer": "Bearer abcdef0123456789abcdef0123456789"}]})

    assert "tp-secret-token" not in json.dumps(detail)
    assert "abcdef0123456789abcdef0123456789" not in json.dumps(detail)
    assert json.dumps(detail).count("[REDACTED]") >= 2


def test_row_from_results_scrubs_detail_before_persisting():
    row = row_from_results(
        tool_name="bilinc_recall_smart",
        query="sk-query-secret",
        results=[],
        latency_ms=1,
        detail={"queries_tried": ["sk-detail-secret", "ghp_abcdefghijklmnopqrstuvwxyz123456"]},
    )

    assert "sk-query-secret" not in row.query
    assert "sk-detail-secret" not in json.dumps(row.detail)
    assert "ghp_" not in json.dumps(row.detail)


def test_row_from_results_scrubs_secret_like_retrieved_keys():
    class Result:
        key = "account:tp-secret-token"
        score = 1.0
        memory_type = MemoryType.SEMANTIC

    row = row_from_results(
        tool_name="recall",
        query="safe",
        results=[Result(), {"key": "ghp_abcdefghijklmnopqrstuvwxyz123456", "score": 0.5, "memory_type": "semantic"}],
        latency_ms=1,
    )

    dumped = json.dumps(row.retrieved_keys)
    assert "tp-secret-token" not in dumped
    assert "ghp_" not in dumped
    assert dumped.count("[REDACTED]") >= 2


def test_eval_capture_serializes_jsonl_row():
    row = EvalCaptureRow(
        schema_version=1,
        tool_name="recall",
        query="where is memory?",
        retrieved_keys=["a", "b"],
        retrieved_scores=[0.9, 0.5],
        memory_types=["semantic"],
        latency_ms=12,
        created_at=123.0,
        detail={"limit": 2},
    )

    line = row_to_jsonl(row)
    parsed = row_from_jsonl(line)

    assert line.endswith("\n")
    assert parsed == row


@pytest.mark.asyncio
async def test_eval_candidates_table_exists(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "test.db"))
    await backend.init()

    row = backend._get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='eval_candidates'"
    ).fetchone()

    assert row is not None


@pytest.mark.asyncio
async def test_eval_capture_insert_and_export(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "test.db"))
    await backend.init()
    now = time.time()
    older = EvalCaptureRow(1, "recall", "old", ["old"], [0.1], ["semantic"], 3, now - 100, {})
    newer = EvalCaptureRow(1, "recall", "new", ["new", "new"], [0.9, 0.8], ["semantic"], 5, now, {"limit": 2})

    await backend.record_eval_candidate(older)
    await backend.record_eval_candidate(newer)

    rows = await backend.list_eval_candidates(since=now - 1)

    assert len(rows) == 1
    assert rows[0].query == "new"
    assert rows[0].retrieved_keys == ["new"]
    assert row_from_jsonl(row_to_jsonl(rows[0])).detail == {"limit": 2}


@pytest.mark.asyncio
async def test_recall_capture_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("BILINC_EVAL_CAPTURE", raising=False)
    plane = await make_temp_plane(tmp_path)
    await plane.commit("alpha", "first value", MemoryType.SEMANTIC)

    await plane.recall(key="alpha")

    rows = await plane.backend.list_eval_candidates()
    assert rows == []


@pytest.mark.asyncio
async def test_recall_capture_records_retrieved_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_EVAL_CAPTURE", "1")
    plane = await make_temp_plane(tmp_path)
    await plane.commit("alpha", "first value", MemoryType.SEMANTIC)
    await plane.commit("beta", "second value", MemoryType.SEMANTIC)

    entries = await plane.recall(memory_type=MemoryType.SEMANTIC, limit=10)

    rows = await plane.backend.list_eval_candidates()
    assert [entry.key for entry in entries] == ["alpha", "beta"]
    assert len(rows) == 1
    assert rows[0].tool_name == "recall"
    assert rows[0].retrieved_keys == ["alpha", "beta"]
    assert rows[0].memory_types == ["semantic", "semantic"]
    assert rows[0].latency_ms >= 0


@pytest.mark.asyncio
async def test_smart_recall_capture_includes_reflection_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_EVAL_CAPTURE", "1")
    plane = await make_temp_plane(tmp_path)
    await plane.commit("alpha", "Bilinc recall evidence harness", MemoryType.SEMANTIC)

    result = await _handle_bilinc_recall_smart(plane, {"query": "Bilinc evidence", "limit": 3, "max_reflections": 1})
    payload = json.loads(result[0].text)
    rows = await plane.backend.list_eval_candidates()

    assert payload["success"] is True
    assert any(row.tool_name == "bilinc_recall_smart" for row in rows)
    smart_row = next(row for row in rows if row.tool_name == "bilinc_recall_smart")
    assert "reflections_used" in smart_row.detail
    assert "adequacy" in smart_row.detail
