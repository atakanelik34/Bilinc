"""Tests for snapshot fallback DB provisioning."""

from __future__ import annotations

import tempfile
from pathlib import Path

from bilinc.storage.sqlite import SQLiteBackend
from tests import snapshot_seed


def _run(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_copy_or_seed_snapshot_db_fallback_when_snapshot_missing(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        target_dir = Path(td)
        # Force fallback path regardless of local fixture availability.
        monkeypatch.setattr(snapshot_seed, "SNAPSHOT_DB", target_dir / "nonexistent.db")
        db_path = snapshot_seed.copy_or_seed_snapshot_db(target_dir, filename="seeded.db")
        backend = SQLiteBackend(db_path=db_path)
        _run(backend.init())
        try:
            stats = _run(backend.stats())
            assert stats["total_entries"] >= 1
            by_type = stats.get("by_type", {})
            assert "working" in by_type
            assert "semantic" in by_type
        finally:
            _run(backend.close())

