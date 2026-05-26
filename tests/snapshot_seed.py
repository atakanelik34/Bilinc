"""Helpers to provide snapshot-like SQLite DB for tests.

If a committed snapshot fixture exists, tests copy it.
If not (e.g. CI), this module creates a deterministic fallback DB.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.storage.sqlite import SQLiteBackend

SNAPSHOT_DB = Path(__file__).parent / "fixtures" / "bilinc.live.snapshot.db"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _seed_fallback_db(db_path: str) -> None:
    backend = SQLiteBackend(db_path=db_path)
    _run(backend.init())
    try:
        seed_entries = [
            MemoryEntry(key="seed_semantic_1", value="Bilinc deployment guide", memory_type=MemoryType.SEMANTIC, importance=0.9),
            MemoryEntry(key="seed_semantic_2", value="ReARC Labs product notes", memory_type=MemoryType.SEMANTIC, importance=0.8),
            MemoryEntry(key="seed_episodic_1", value="Session summary draft", memory_type=MemoryType.EPISODIC, metadata={"session_id": "seed-session"}),
            MemoryEntry(key="seed_procedural_1", value="Run tests with pytest -v", memory_type=MemoryType.PROCEDURAL),
            MemoryEntry(key="wm_user_profile", value="Atakan profile context", memory_type=MemoryType.WORKING, importance=1.0),
            MemoryEntry(key="wm_hermes_prefs", value="Turkish concise responses", memory_type=MemoryType.WORKING, importance=1.0),
        ]
        for entry in seed_entries:
            _run(backend.save(entry))
    finally:
        _run(backend.close())


def copy_or_seed_snapshot_db(target_dir: Path, filename: str = "phase.runtime.db") -> str:
    """Return path to DB copy from fixture, or generated fallback DB when fixture missing."""
    target = target_dir / filename
    if SNAPSHOT_DB.exists():
        shutil.copy2(SNAPSHOT_DB, target)
        return str(target)

    _seed_fallback_db(str(target))
    return str(target)

