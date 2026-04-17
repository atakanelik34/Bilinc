"""Full phase regression on snapshot database copy (Phase 1-8)."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from bilinc.core.models import MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.mcp_server.server_v2 import (
    _handle_bilinc_benchmark,
    _handle_bilinc_health,
    _handle_bilinc_import,
    _handle_bilinc_query_analysis,
    _handle_bilinc_recall_smart,
    _handle_bilinc_summarize,
)
from bilinc.scheduler import BackgroundScheduler
from bilinc.storage.sqlite import SQLiteBackend
from tests.snapshot_seed import copy_or_seed_snapshot_db


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _call(handler, plane, args=None):
    result = handler(plane, args or {})
    if asyncio.iscoroutine(result):
        result = _run(result)
    return json.loads(result[0].text)


def _copy_snapshot_db(tmp_path: Path) -> str:
    return copy_or_seed_snapshot_db(tmp_path, filename="phase_all.runtime.db")


def test_all_phases_on_snapshot_copy():
    with tempfile.TemporaryDirectory() as td:
        db_path = _copy_snapshot_db(Path(td))
        backend = SQLiteBackend(db_path=db_path)
        _run(backend.init())

        plane = StatePlane(backend=backend, enable_verification=True, enable_audit=True)
        _run(plane.init())
        plane.init_agm()
        plane.init_knowledge_graph()

        # Restore AGM from backend snapshot (Phase 3 expectation).
        entries = _run(backend.list_all())
        loaded = plane.agm_engine.load_beliefs_from_entries(entries)
        assert loaded > 0

        # Phase 1: persistent working memory loaded from snapshot.
        assert plane.working_memory.count >= 1

        # Phase 2: verification pipeline on commit.
        committed = _run(plane.commit(
            key="phase_all_verify",
            value={"service": "bilinc", "ok": True},
            memory_type=MemoryType.SEMANTIC,
            importance=0.8,
        ))
        assert committed.is_verified is True

        # Phase 4+6: intelligent + reflective recall.
        smart = _call(_handle_bilinc_recall_smart, plane, {"query": "bilinc deployment", "limit": 5})
        assert smart["success"] is True
        assert len(smart["results"]) >= 1

        qa = _call(_handle_bilinc_query_analysis, plane, {"query": "k8s deploy bilinc"})
        assert qa["success"] is True
        assert qa["token_count"] >= 1

        # Phase 5: summarize episodic memories.
        for i in range(6):
            _run(plane.commit(
                key=f"phase_all_ep_{i}",
                value=f"Session note {i} for release flow.",
                memory_type=MemoryType.EPISODIC,
                metadata={"session_id": "phase-all-session"},
            ))
        summed = _call(_handle_bilinc_summarize, plane, {"session_id": "phase-all-session"})
        assert summed["success"] is True
        assert summed["count"] >= 1

        # Phase 7: scheduler jobs.
        scheduler = BackgroundScheduler(plane)
        scheduler.register_phase7_jobs()
        phase7 = _run(scheduler.run_due_jobs(force=True))
        assert "decay_pass" in phase7
        assert "health_metrics_report" in phase7
        trigger = _run(scheduler.run_trigger_checks())
        assert "triggered" in trigger

        # Phase 8: health + benchmark + import.
        health = _call(_handle_bilinc_health, plane, {})
        assert health["success"] is True
        bench = _call(_handle_bilinc_benchmark, plane, {"iterations": 2})
        assert bench["success"] is True
        imported = _call(_handle_bilinc_import, plane, {
            "format": "json",
            "data": [{"key": "phase_all_import", "value": "ok", "memory_type": "semantic"}],
        })
        assert imported["imported"] >= 1

        # Basic end-state check
        stats = _run(backend.stats())
        assert stats["total_entries"] >= len(entries)
        _run(backend.close())
