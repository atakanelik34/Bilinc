"""SQLite integration tests for Bilinc persistent storage."""
import asyncio
import os
import tempfile
import time
from pathlib import Path
from typing import Generator

import pytest

from bilinc.core.stateplane import StatePlane
from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.storage.sqlite import SQLiteBackend


@pytest.fixture
def tmp_db_path() -> Generator[str, None, None]:
    """Create a temporary database file path (no file created, just name)."""
    with tempfile.TemporaryDirectory() as td:
        yield os.path.join(td, "test.db")


def _run(coro):
    """Helper to run async code in sync tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_backend(path: str) -> SQLiteBackend:
    """Create and initialize a backend (sync)."""
    b = SQLiteBackend(db_path=path)
    _run(b.init())
    return b


# ── Backend Init Tests ─────────────────────────────────


class TestSQLiteBackendInit:
    def test_creates_db_file(self, tmp_db_path: str):
        assert not os.path.exists(tmp_db_path)
        _make_backend(tmp_db_path)
        assert os.path.exists(tmp_db_path)

    def test_init_is_idempotent(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        _run(b.init())  # second call should succeed
        assert b._conn is not None
        _run(b.close())

    def test_creates_schema_version_table(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        row = b._conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        assert row is not None
        assert row["version"] == 1
        _run(b.close())

    def test_schema_version_recorded(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        stats = _run(b.stats())
        assert stats["schema_version"] == 1
        _run(b.close())

    def test_wal_mode_enabled(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        row = b._conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
        _run(b.close())


class TestSQLiteBackendCRUD:
    def test_save_and_load(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        entry = MemoryEntry(key="test_key", value={"hello": "world"}, memory_type=MemoryType.SEMANTIC)
        assert _run(b.save(entry))
        loaded = _run(b.load("test_key"))
        assert loaded is not None
        assert loaded.key == "test_key"
        assert loaded.value == {"hello": "world"}
        _run(b.close())

    def test_load_nonexistent_returns_none(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        assert _run(b.load("nonexistent")) is None
        _run(b.close())

    def test_delete_existing(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        _run(b.save(MemoryEntry(key="del_key", value="val", memory_type=MemoryType.SEMANTIC)))
        assert _run(b.delete("del_key")) is True
        assert _run(b.load("del_key")) is None
        _run(b.close())

    def test_delete_nonexistent_returns_false(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        assert _run(b.delete("nonexistent")) is False
        _run(b.close())

    def test_update_existing_key(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        _run(b.save(MemoryEntry(key="update_key", value="v1", memory_type=MemoryType.SEMANTIC)))
        _run(b.save(MemoryEntry(key="update_key", value="v2", memory_type=MemoryType.SEMANTIC)))
        loaded = _run(b.load("update_key"))
        assert loaded.value == "v2"
        _run(b.close())

    def test_load_by_type(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        _run(b.save(MemoryEntry(key="k1", value="v1", memory_type=MemoryType.EPISODIC)))
        _run(b.save(MemoryEntry(key="k2", value="v2", memory_type=MemoryType.SEMANTIC)))
        _run(b.save(MemoryEntry(key="k3", value="v3", memory_type=MemoryType.EPISODIC)))
        results = _run(b.load_by_type(MemoryType.EPISODIC))
        assert len(results) == 2
        keys = {r.key for r in results}
        assert keys == {"k1", "k3"}
        _run(b.close())

    def test_list_all(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        for i in range(5):
            _run(b.save(MemoryEntry(key=f"key_{i}", value=f"val_{i}", memory_type=MemoryType.SEMANTIC)))
        all_entries = _run(b.list_all())
        assert len(all_entries) == 5
        _run(b.close())

    def test_stats(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        _run(b.save(MemoryEntry(key="s1", value="v1", memory_type=MemoryType.SEMANTIC)))
        _run(b.save(MemoryEntry(key="e1", value="v2", memory_type=MemoryType.EPISODIC)))
        stats = _run(b.stats())
        assert stats["total_entries"] == 2
        assert stats["schema_version"] == 1
        _run(b.close())


class TestSQLitePersistenceAcrossProcesses:
    """Test that data persists across separate CLI invocations."""

    def test_commit_then_recall(self, tmp_db_path: str):
        """Process 1 commits, Process 2 recalls — data must persist."""
        b1 = _make_backend(tmp_db_path)
        _run(b1.save(MemoryEntry(key="cross_process", value="persists", memory_type=MemoryType.SEMANTIC)))
        _run(b1.close())

        b2 = _make_backend(tmp_db_path)
        loaded = _run(b2.load("cross_process"))
        assert loaded is not None
        assert loaded.value == "persists"
        _run(b2.close())

    def test_commit_update_recall(self, tmp_db_path: str):
        """Process 1 commits, Process 2 updates, Process 3 recalls updated value."""
        b1 = _make_backend(tmp_db_path)
        _run(b1.save(MemoryEntry(key="mutable", value="original", memory_type=MemoryType.SEMANTIC)))
        _run(b1.close())

        b2 = _make_backend(tmp_db_path)
        _run(b2.save(MemoryEntry(key="mutable", value="updated", memory_type=MemoryType.SEMANTIC)))
        _run(b2.close())

        b3 = _make_backend(tmp_db_path)
        loaded = _run(b3.load("mutable"))
        assert loaded.value == "updated"
        _run(b3.close())

    def test_delete_persists(self, tmp_db_path: str):
        """Process 1 commits, Process 2 deletes, Process 3 verifies deletion."""
        b1 = _make_backend(tmp_db_path)
        _run(b1.save(MemoryEntry(key="to_delete", value="gone", memory_type=MemoryType.SEMANTIC)))
        _run(b1.close())

        b2 = _make_backend(tmp_db_path)
        _run(b2.delete("to_delete"))
        _run(b2.close())

        b3 = _make_backend(tmp_db_path)
        loaded = _run(b3.load("to_delete"))
        assert loaded is None
        _run(b3.close())


class TestStatePlaneWithSQLite:
    """Integration tests for StatePlane with SQLite backend."""

    def test_commit_and_recall(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        plane = StatePlane(backend=b, enable_verification=False, enable_audit=True)
        _run(plane.init())
        _run(plane.commit(key="sp_key", value="sp_value", memory_type=MemoryType.SEMANTIC))
        results = _run(plane.recall(key="sp_key"))
        assert len(results) > 0
        assert results[0].value == "sp_value"
        _run(b.close())

    def test_forget(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        plane = StatePlane(backend=b, enable_verification=False, enable_audit=True)
        _run(plane.init())
        _run(plane.commit(key="forget_me", value="val", memory_type=MemoryType.SEMANTIC))
        removed = _run(plane.forget("forget_me"))
        assert removed is True
        results = _run(plane.recall(key="forget_me"))
        assert len(results) == 0
        _run(b.close())

    def test_stats_with_backend(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        plane = StatePlane(backend=b, enable_verification=False, enable_audit=True)
        _run(plane.init())
        _run(plane.commit(key="stat1", value="v1", memory_type=MemoryType.SEMANTIC))
        _run(plane.commit(key="stat2", value="v2", memory_type=MemoryType.EPISODIC))
        stats = _run(plane.stats())
        assert "backend" in stats
        assert stats["backend"]["total_entries"] == 2
        _run(b.close())

    def test_snapshot_includes_entries(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        plane = StatePlane(backend=b, enable_verification=False, enable_audit=True)
        _run(plane.init())
        _run(plane.commit(key="snap_key", value={"v": 1}, memory_type=MemoryType.SEMANTIC))
        snap = _run(plane.snapshot())
        assert snap["total_entries"] == 1
        assert "snap_key" in snap["entries"]
        assert snap["entries"]["snap_key"]["value"] == {"v": 1}
        _run(b.close())

    def test_diff_reports_added_modified_removed(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        plane = StatePlane(backend=b, enable_verification=False, enable_audit=True)
        _run(plane.init())

        t0 = time.time()
        _run(plane.commit(key="diff_key", value="v1", memory_type=MemoryType.SEMANTIC))
        _run(plane.commit(key="remove_me", value="bye", memory_type=MemoryType.SEMANTIC))
        t1 = time.time()
        _run(plane.commit(key="diff_key", value="v2", memory_type=MemoryType.SEMANTIC))
        _run(plane.forget("remove_me"))
        _run(plane.commit(key="new_key", value="new", memory_type=MemoryType.SEMANTIC))
        t2 = time.time()

        diff = _run(plane.diff(t1, t2))
        assert diff["counts"] == {"added": 1, "modified": 1, "removed": 1}
        assert diff["added"][0]["key"] == "new_key"
        assert diff["modified"][0]["key"] == "diff_key"
        assert diff["removed"][0]["key"] == "remove_me"
        assert t0 < t1 < t2
        _run(b.close())

    def test_rollback_restores_updated_and_deleted_state(self, tmp_db_path: str):
        b = _make_backend(tmp_db_path)
        plane = StatePlane(backend=b, enable_verification=False, enable_audit=True)
        _run(plane.init())

        _run(plane.commit(key="pref", value="dark", memory_type=MemoryType.SEMANTIC))
        _run(plane.commit(key="delete_later", value="keep", memory_type=MemoryType.SEMANTIC))
        target_ts = time.time()

        _run(plane.commit(key="pref", value="light", memory_type=MemoryType.SEMANTIC))
        _run(plane.forget("delete_later"))
        _run(plane.commit(key="added_later", value="temp", memory_type=MemoryType.SEMANTIC))

        result = _run(plane.rollback(target_ts))
        assert result["counts"] == {"created": 1, "updated": 1, "deleted": 1}

        pref = _run(plane.recall(key="pref"))[0]
        assert pref.value == "dark"
        restored = _run(plane.recall(key="delete_later"))[0]
        assert restored.value == "keep"
        assert _run(plane.recall(key="added_later")) == []
        _run(b.close())
