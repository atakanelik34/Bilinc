"""Phase 7 scheduler + background job tests."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from bilinc.core.models import MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend


SNAPSHOT_DB = Path(__file__).parent / "fixtures" / "bilinc.live.snapshot.db"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _copy_snapshot_db(tmp_path: Path) -> str:
    assert SNAPSHOT_DB.exists(), f"Snapshot db not found: {SNAPSHOT_DB}"
    target = tmp_path / "phase7.runtime.db"
    shutil.copy2(SNAPSHOT_DB, target)
    return str(target)


class TestPhase7Scheduler:
    def test_registers_default_phase7_jobs(self):
        from bilinc.scheduler import BackgroundScheduler

        plane = StatePlane(enable_verification=False, enable_audit=False)
        scheduler = BackgroundScheduler(plane)
        scheduler.register_phase7_jobs()

        names = set(scheduler.job_names())
        assert {
            "background_consolidation",
            "decay_pass",
            "kg_maintenance",
            "entity_linking_backlog",
            "health_metrics_report",
        }.issubset(names)

    def test_decay_pass_operates_on_snapshot_copy(self):
        from bilinc.scheduler import BackgroundScheduler

        with tempfile.TemporaryDirectory() as td:
            db_path = _copy_snapshot_db(Path(td))
            backend = SQLiteBackend(db_path=db_path)
            _run(backend.init())

            plane = StatePlane(backend=backend, enable_verification=False, enable_audit=True)
            _run(plane.init())

            semantic = _run(backend.load_by_type(MemoryType.SEMANTIC, limit=1))[0]
            semantic.current_strength = 1.0
            semantic.last_accessed = time.time() - (86400 * 180)
            semantic.updated_at = time.time()
            _run(backend.restore(semantic))

            scheduler = BackgroundScheduler(plane)
            scheduler.register_phase7_jobs()
            report = _run(scheduler.run_job_once("decay_pass"))
            assert report["scanned"] > 0

            refreshed = _run(backend.load(semantic.key))
            assert refreshed is not None
            assert refreshed.current_strength < 1.0
            _run(backend.close())

    def test_triggered_consolidation_when_working_memory_high(self):
        from bilinc.scheduler import BackgroundScheduler

        with tempfile.TemporaryDirectory() as td:
            db_path = _copy_snapshot_db(Path(td))
            backend = SQLiteBackend(db_path=db_path)
            _run(backend.init())

            plane = StatePlane(backend=backend, enable_verification=False, enable_audit=True)
            _run(plane.init())

            for idx in range(7):
                _run(
                    plane.commit(
                        key=f"phase7_wm_{idx}",
                        value=f"phase7 note {idx}",
                        memory_type=MemoryType.WORKING,
                        importance=1.0,
                    )
                )

            scheduler = BackgroundScheduler(plane)
            result = _run(scheduler.run_trigger_checks())

            assert result["triggered"] is True
            assert result["consolidated"] >= 1
            _run(backend.close())
