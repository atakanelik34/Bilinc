import asyncio
import json
import os
import subprocess
import sys

import pytest

from bilinc import StatePlane
from bilinc.core.models import MemoryType
from bilinc.eval.capture import EvalCaptureRow, row_from_jsonl
from bilinc.eval.replay import jaccard, replay_rows, top1_same
from bilinc.storage.sqlite import SQLiteBackend


async def make_temp_plane(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "test.db"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()
    return plane


def cli_env():
    src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    env = os.environ.copy()
    env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")
    return env


def test_replay_metrics_jaccard_and_top1():
    assert jaccard(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)
    assert jaccard([], []) == 1.0
    assert top1_same(["a", "b"], ["a", "c"]) is True
    assert top1_same(["a", "b"], ["b", "a"]) is False


@pytest.mark.asyncio
async def test_replay_rows_replays_captured_key_lookup(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit("alpha", "Alpha value", memory_type=MemoryType.SEMANTIC)
    row = EvalCaptureRow(
        schema_version=1,
        tool_name="recall",
        query="alpha",
        retrieved_keys=["alpha"],
        retrieved_scores=[0.0],
        memory_types=["semantic"],
        latency_ms=1,
        created_at=123.0,
        detail={"key": "alpha"},
    )

    report = await replay_rows(plane, [row])

    assert report.summary["top1_stability_rate"] == 1.0
    assert report.regressions == []


@pytest.mark.asyncio
async def test_replay_rows_replays_captured_memory_type_lookup(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit("alpha", "Alpha value", memory_type=MemoryType.SEMANTIC)
    row = EvalCaptureRow(
        schema_version=1,
        tool_name="recall",
        query="semantic",
        retrieved_keys=["alpha"],
        retrieved_scores=[0.0],
        memory_types=["semantic"],
        latency_ms=1,
        created_at=123.0,
        detail={"key": None, "memory_type": "semantic"},
    )

    report = await replay_rows(plane, [row])

    assert report.summary["mean_jaccard"] == 1.0
    assert report.summary["top1_stability_rate"] == 1.0
    assert report.regressions == []


@pytest.mark.asyncio
async def test_replay_rows_suppresses_eval_capture_side_effects(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_EVAL_CAPTURE", "1")
    plane = await make_temp_plane(tmp_path)
    await plane.commit("alpha", "Alpha value", memory_type=MemoryType.SEMANTIC)
    row = EvalCaptureRow(
        schema_version=1,
        tool_name="recall",
        query="alpha",
        retrieved_keys=["alpha"],
        retrieved_scores=[0.0],
        memory_types=["semantic"],
        latency_ms=1,
        created_at=123.0,
        detail={"key": "alpha"},
    )

    await replay_rows(plane, [row])

    assert await plane.backend.list_eval_candidates() == []


@pytest.mark.asyncio
async def test_replay_rows_detects_order_regression(tmp_path, monkeypatch):
    plane = await make_temp_plane(tmp_path)
    row = EvalCaptureRow(
        schema_version=1,
        tool_name="bilinc_recall_smart",
        query="anything",
        retrieved_keys=["expected-first", "second"],
        retrieved_scores=[1.0, 0.5],
        memory_types=["semantic", "semantic"],
        latency_ms=10,
        created_at=123.0,
        detail={},
    )

    async def fake_recall_reflective(*args, **kwargs):
        return {
            "results": [
                {"key": "second", "score": 0.9, "memory_type": "semantic"},
                {"key": "expected-first", "score": 0.8, "memory_type": "semantic"},
            ],
            "reflections_used": 0,
            "adequacy": 1.0,
        }

    monkeypatch.setattr(plane, "recall_reflective", fake_recall_reflective)

    report = await replay_rows(plane, [row])

    assert report.summary["rows_total"] == 1
    assert report.summary["rows_replayed"] == 1
    assert report.summary["top1_stability_rate"] == 0.0
    assert report.regressions[0]["query"] == "anything"


def test_eval_export_cli_prints_jsonl(tmp_path, monkeypatch):
    db_path = tmp_path / "cli.db"

    async def seed():
        backend = SQLiteBackend(str(db_path))
        await backend.init()
        await backend.record_eval_candidate(
            EvalCaptureRow(1, "recall", "cli query", ["alpha"], [1.0], ["semantic"], 4, 123.0, {})
        )

    asyncio.run(seed())

    result = subprocess.run(
        [sys.executable, "-m", "bilinc.cli.main", "--db", str(db_path), "eval", "export"],
        check=True,
        text=True,
        capture_output=True,
        env=cli_env(),
    )

    rows = [row_from_jsonl(line) for line in result.stdout.splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0].query == "cli query"


def test_eval_replay_cli_prints_json_summary(tmp_path):
    baseline = tmp_path / "baseline.jsonl"
    baseline.write_text(
        json.dumps({
            "schema_version": 1,
            "tool_name": "bilinc_recall_smart",
            "query": "missing",
            "retrieved_keys": [],
            "retrieved_scores": [],
            "memory_types": [],
            "latency_ms": 0,
            "created_at": 123.0,
            "detail": {},
        }) + "\n"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bilinc.cli.main",
            "--db",
            str(tmp_path / "cli.db"),
            "eval",
            "replay",
            "--against",
            str(baseline),
        ],
        check=True,
        text=True,
        capture_output=True,
        env=cli_env(),
    )

    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["summary"]["rows_total"] == 1
    assert "regressions" in payload
