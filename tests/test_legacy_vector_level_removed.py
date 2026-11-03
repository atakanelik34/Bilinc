"""The legacy vector level (Ollama + the vec_bilinc table) is gone and nothing depends on it (item C2)."""
from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.storage.sqlite import SQLiteBackend

MEMORIES = [
    ("plan", "The quarterly harbor plan covers shipping routes and port fees."),
    ("budget", "Budget for the quarter: port fees are the largest cost."),
    ("note", "Remember to renew the harbor insurance before March."),
    ("team", "Alice leads the logistics team and reports to Bob."),
    ("tr", "İstanbul limanı için üç aylık plan hazırlandı."),
    ("misc", "Unrelated note about lunch options near the office."),
]
# Recorded from origin/main (5578d27) with no Ollama running: the order and the hybrid scores before the change.
BASELINE = {
    "harbor plan": {"hybrid": [["plan", 0.008197], ["tr", 0.008065], ["note", 0.007937]], "rerank": ["plan", "tr", "note"]},
    "port fees": {"hybrid": [["plan", 0.008197], ["budget", 0.008065]], "rerank": ["plan", "budget"]},
    "who leads logistics": {"hybrid": [["team", 0.004918]], "rerank": ["team"]},
    "istanbul limanı": {"hybrid": [["tr", 0.008197]], "rerank": ["tr"]},
    "insurance renewal": {"hybrid": [["note", 0.008197]], "rerank": ["note"]},
    "lunch": {"hybrid": [["misc", 0.008197]], "rerank": ["misc"]},
}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _backend(path):
    backend = SQLiteBackend(str(path))
    await backend.init()
    for key, value in MEMORIES:
        await backend.save(MemoryEntry(key=key, value=value, memory_type=MemoryType.SEMANTIC))
    return backend


def _rank(backend):
    from bilinc.core.vector_search import HybridSearch

    conn = backend._get_conn()
    keys = {row[0]: row[1] for row in conn.execute("SELECT rowid, key FROM memories")}
    search = HybridSearch(conn)
    out = {}
    for query in BASELINE:
        out[query] = {
            "hybrid": [[keys[rowid], round(score, 6)] for rowid, score in search.hybrid_search(query, 5)],
            "rerank": [meta.get("key") for _, _, meta in search.search_with_reranking(query, top_k=5, now=1_800_000_000.0)],
        }
    return out


def test_the_ranking_is_the_one_recorded_before_the_change(tmp_path):
    backend = _run(_backend(tmp_path / "a.db"))
    assert _rank(backend) == BASELINE


def test_a_search_makes_no_network_request(tmp_path, monkeypatch):
    import urllib.request

    def refuse(*args, **kwargs):
        raise AssertionError("a search must not make an HTTP request")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    backend = _run(_backend(tmp_path / "a.db"))
    assert _rank(backend) == BASELINE


def _add_stand_in(path: Path, *, rows: int = 3) -> None:
    """A database that looks like an old one: a vec_bilinc entry and its shadow tables, built without the module."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE vec_bilinc_rowids (rowid INTEGER PRIMARY KEY AUTOINCREMENT, id, chunk_id INTEGER, chunk_offset INTEGER)")
        conn.execute("CREATE TABLE vec_bilinc_chunks (chunk_id INTEGER PRIMARY KEY AUTOINCREMENT, size INTEGER NOT NULL, validity BLOB NOT NULL, rowids BLOB NOT NULL)")
        conn.execute("CREATE TABLE vec_bilinc_info (key TEXT PRIMARY KEY, value ANY)")
        conn.execute("CREATE TABLE vec_bilinc_vector_chunks00 (rowid PRIMARY KEY, vectors BLOB NOT NULL)")
        for n in range(1, rows + 1):
            conn.execute("INSERT INTO vec_bilinc_rowids (id, chunk_id, chunk_offset) VALUES (?, 1, ?)", (n, n - 1))
        conn.execute("INSERT INTO vec_bilinc_vector_chunks00 VALUES (1, ?)", (b"OLDVECTORBYTES" * 8,))
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute(
            "INSERT INTO sqlite_master (type, name, tbl_name, rootpage, sql) VALUES "
            "('table', 'vec_bilinc', 'vec_bilinc', 0, 'CREATE VIRTUAL TABLE vec_bilinc USING vec0(embedding float[768])')")
        conn.execute("PRAGMA writable_schema=OFF")
        conn.commit()
    finally:
        conn.close()


def test_the_stand_in_is_built_without_the_module(tmp_path):
    path = tmp_path / "old.db"
    _run(_backend(path))
    _add_stand_in(path)
    conn = sqlite3.connect(path)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'vec_bilinc%'")}
    finally:
        conn.close()
    assert "vec_bilinc" in names and "vec_bilinc_rowids" in names  # fails loudly if this SQLite refuses the edit


def test_an_old_vec_bilinc_table_is_never_read(tmp_path):
    path = tmp_path / "old.db"
    _run(_backend(path))
    _add_stand_in(path)
    backend = SQLiteBackend(str(path))
    _run(backend.init())
    assert _rank(backend) == BASELINE


def test_a_database_with_an_old_vec_bilinc_works_without_the_module(tmp_path):
    from bilinc.core.stateplane import StatePlane

    path = tmp_path / "old.db"
    _run(_backend(path))
    _add_stand_in(path)

    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(path)), enable_verification=False, enable_audit=True)
        await plane.init()
        await plane.commit("fresh", "A fresh memory written after the upgrade.", MemoryType.SEMANTIC)
        assert await plane.forget("misc")
        await plane.commit("purged", "This one is purged.", MemoryType.SEMANTIC)
        plane.audit.purge_key("purged")
        compact = getattr(plane.backend, "compact_search_index", None)
        assert await compact() in (True, False)  # the secure-delete / WAL-checkpoint step of a purge
        plane.backend.fts_rebuild()
        keys = {e.key for e in await plane.backend.list_all()}
        await plane.backend.close()
        return keys

    keys = _run(go())
    assert "fresh" in keys and "misc" not in keys


def test_a_new_database_has_no_vec_table_and_no_extension_loading(tmp_path):
    from bilinc.core.stateplane import StatePlane

    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "new.db")), enable_verification=False, enable_audit=False)
        await plane.init()
        await plane.commit("k", "some value to search for", MemoryType.SEMANTIC)
        await plane.recall_intelligent("value") if hasattr(plane, "recall_intelligent") else None
        plane._get_hybrid_search()
        conn = plane.backend._get_conn()
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'vec_bilinc%'")]
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("SELECT load_extension('nothing')")  # extension loading is off on this connection
        await plane.backend.close()
        return names

    assert _run(go()) == []


def test_the_core_package_imports_without_the_vector_store():
    code = (
        "import bilinc.core\n"
        "from bilinc.core import *\n"
        "import bilinc.core as c\n"
        "assert not hasattr(c, 'VectorStore'), 'VectorStore is still exposed'\n"
        "assert 'VectorStore' not in c.__all__\n"
        "assert hasattr(c, 'HybridSearch')\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                            env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
    assert result.returncode == 0, result.stderr


def _script():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "count_legacy_vec_table.py"
    spec = importlib.util.spec_from_file_location("count_legacy_vec_table", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_count_script_reports_and_changes_nothing(tmp_path):
    script = _script()
    path = tmp_path / "old.db"
    _run(_backend(path))
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")  # the owner's file is in WAL mode
    conn.close()
    _add_stand_in(path, rows=4)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    report = script.count_legacy_vec_table(path)
    assert report["present"] is True and report["vectors"] == 4
    assert "vec_bilinc" in report["objects"] and "vec_bilinc_rowids" in report["objects"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before  # the main file is unchanged


def test_the_count_script_on_a_file_without_the_table_and_on_a_missing_file(tmp_path):
    script = _script()
    path = tmp_path / "new.db"
    _run(_backend(path))
    report = script.count_legacy_vec_table(path)
    assert report["present"] is False and report["vectors"] == 0 and report["objects"] == []
    with pytest.raises(script.CountError):
        script.count_legacy_vec_table(tmp_path / "missing.db")
    assert script.main([str(tmp_path / "missing.db")]) == 1
