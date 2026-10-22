"""Persisted vectors and the embedding daemon, with a hashing encoder (no model download)."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from bilinc.core.models import MemoryEntry  # noqa: E402
from bilinc.core.stateplane import StatePlane  # noqa: E402
from bilinc.embeddings import client, store  # noqa: E402
from bilinc.embeddings.daemon import EmbeddingDaemon  # noqa: E402
from bilinc.embeddings.encoder import HashingEncoder  # noqa: E402
from bilinc.embeddings.text import chunk_words, decode_stored_value, memory_text  # noqa: E402
from bilinc.storage.sqlite import SQLiteBackend  # noqa: E402


def test_memory_text_decodes_values_and_keeps_real_letters():
    raw = json.dumps({"user": "Yatırımcılarla görüştü", "n": 3})
    assert memory_text("program:contest-2026", decode_stored_value(raw)) == "program contest 2026\nYatırımcılarla görüştü\n3"
    assert chunk_words("a b c d e", words=2) == ["a b", "c d", "e"]
    assert chunk_words("   ") == []


async def _backend(path) -> SQLiteBackend:
    backend = SQLiteBackend(str(path))
    await backend.init()
    return backend


@pytest.mark.asyncio
async def test_indexer_follows_changes_scope_and_model(tmp_path):
    db = tmp_path / "local.sqlite"
    backend = await _backend(db)
    await backend.save(MemoryEntry(key="note:a", value="harbor launch plan"))
    await backend.save(MemoryEntry(key="session_archive:1", value="long raw transcript"))
    daemon = EmbeddingDaemon(str(db), HashingEncoder(), keys_per_pass=10)

    first = daemon.index_once()
    assert first["embedded"] == 1 and first["pending"] == 0  # the archive key is out of scope
    conn = backend._get_conn()
    assert set(store.indexed_shas(conn, "test-hashing")) == {"note:a"}

    assert daemon.index_once()["embedded"] == 0  # nothing changed
    await backend.save(MemoryEntry(key="note:a", value="harbor launch moved"))
    assert daemon.index_once()["embedded"] == 1  # the text changed

    await backend.delete("note:a")  # forget removes the vectors at once
    assert store.indexed_shas(conn, "test-hashing") == {}

    await backend.save(MemoryEntry(key="note:b", value="other"))
    EmbeddingDaemon(str(db), HashingEncoder(model_id="old-model")).index_once()
    daemon.index_once()  # a different model's vectors are removed
    models = {row[0] for row in conn.execute("SELECT DISTINCT model FROM memory_embeddings")}
    assert models == {"test-hashing"}
    await backend.close()


@pytest.mark.asyncio
async def test_backfill_is_incremental(tmp_path):
    db = tmp_path / "many.sqlite"
    backend = await _backend(db)
    for index in range(5):
        await backend.save(MemoryEntry(key=f"k{index}", value=f"memory number {index}"))
    daemon = EmbeddingDaemon(str(db), HashingEncoder(), keys_per_pass=2)
    assert daemon.index_once()["pending"] == 3
    assert daemon.index_once()["pending"] == 1
    assert daemon.index_once()["pending"] == 0
    await backend.close()


class _RunningDaemon:
    """The daemon on a real unix socket, in a background thread."""

    def __init__(self, db: Path):
        self.dir = Path(tempfile.mkdtemp(prefix="bemb", dir="/tmp"))  # AF_UNIX paths are short on macOS
        self.socket = self.dir / "e.sock"
        self.daemon = EmbeddingDaemon(str(db), HashingEncoder(), socket_path=str(self.socket), poll_seconds=0.05)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.task = self.loop.create_task(self.daemon.serve())
        try:
            self.loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            pass

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if client.request({"op": "health"}, path=self.socket):
                return self
            time.sleep(0.05)
        raise RuntimeError("daemon did not start")

    def __exit__(self, *exc):
        self.loop.call_soon_threadsafe(self.task.cancel)
        self.thread.join(timeout=5)
        shutil.rmtree(self.dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_recall_uses_persisted_vectors_when_the_daemon_answers(tmp_path, monkeypatch):
    db = tmp_path / "recall.sqlite"
    plane = StatePlane(backend=await _backend(db), enable_verification=False, enable_audit=False)
    await plane.init()
    await plane.backend.save(MemoryEntry(key="trip", value="We booked flights to Lisbon for the conference"))
    await plane.backend.save(MemoryEntry(key="food", value="Dinner was pasta with friends"))

    with _RunningDaemon(db) as running:
        monkeypatch.setenv("BILINC_EMBED_SOCKET", str(running.socket))
        running.daemon.index_once()
        assert client.encode_query("lisbon", path=running.socket)[0] == "test-hashing"
        keys, indexed = plane._rank_semantic_signal("Lisbon conference flights", top_k=5)
        assert indexed is True and keys[0] == "trip"
        results = await plane.recall_intelligent("Lisbon conference flights", limit=2)
        assert results[0]["key"] == "trip" and results[0]["signals"]["semantic"] > 0
        assert plane._semantic_recall_rrf_weight(indexed=True) == plane.INTELLIGENT_RECALL_INDEXED_SEMANTIC_WEIGHT
        assert plane.INTELLIGENT_RECALL_INDEXED_SEMANTIC_WEIGHT == 0.35
        assert plane._semantic_recall_rrf_weight(indexed=False) == plane.INTELLIGENT_RECALL_SEMANTIC_WEIGHT

    # Daemon gone: no semantic signal, recall still works.
    keys, indexed = plane._rank_semantic_signal("Lisbon conference flights", top_k=5)
    assert indexed is False and keys == []
    assert (await plane.recall_intelligent("Lisbon conference flights", limit=2))[0]["key"] == "trip"


def test_socket_is_private_to_the_user(tmp_path):
    with _RunningDaemon(tmp_path / "perm.sqlite") as running:
        assert oct(os.stat(running.socket).st_mode & 0o777) == "0o600"
        assert oct(os.stat(running.socket.parent).st_mode & 0o777) == "0o700"


@pytest.mark.asyncio
async def test_recall_falls_back_quickly_when_the_daemon_hangs(tmp_path, monkeypatch):
    import socket as socket_module

    db = tmp_path / "hung.sqlite"
    plane = StatePlane(backend=await _backend(db), enable_verification=False, enable_audit=False)
    await plane.init()
    await plane.backend.save(MemoryEntry(key="trip", value="We booked flights to Lisbon"))
    EmbeddingDaemon(str(db), HashingEncoder()).index_once()  # vectors exist, so recall will ask the socket

    directory = Path(tempfile.mkdtemp(prefix="bhung", dir="/tmp"))
    path = directory / "h.sock"
    server = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)  # accepts connections, never replies
    monkeypatch.setenv("BILINC_EMBED_SOCKET", str(path))
    try:
        started = time.monotonic()
        results = await plane.recall_intelligent("Lisbon flights", limit=2)
        elapsed = time.monotonic() - started
    finally:
        server.close()
        shutil.rmtree(directory, ignore_errors=True)
    assert results[0]["key"] == "trip" and results[0]["signals"]["semantic"] == 0
    assert elapsed < client.QUERY_TIMEOUT_SECONDS + 1.0


def test_daemon_leaves_existing_directories_and_files_alone(tmp_path):
    directory = Path(tempfile.mkdtemp(prefix="bperm", dir="/tmp"))
    try:
        os.chmod(directory, 0o755)
        not_a_socket = directory / "e.sock"
        not_a_socket.write_text("keep me")
        daemon = EmbeddingDaemon(str(tmp_path / "x.sqlite"), HashingEncoder(), socket_path=str(not_a_socket))
        with pytest.raises(FileExistsError):
            asyncio.new_event_loop().run_until_complete(daemon.serve())
        assert not_a_socket.read_text() == "keep me"
        assert oct(os.stat(directory).st_mode & 0o777) == "0o755"
    finally:
        shutil.rmtree(directory, ignore_errors=True)



def test_a_second_daemon_does_not_take_over(tmp_path):
    db = tmp_path / "one.sqlite"
    with _RunningDaemon(db) as running:
        same_socket = EmbeddingDaemon(str(tmp_path / "other.sqlite"), HashingEncoder(), socket_path=str(running.socket))
        with pytest.raises(RuntimeError, match="already listening"):
            asyncio.new_event_loop().run_until_complete(same_socket.serve())
        other_dir = Path(tempfile.mkdtemp(prefix="bsec", dir="/tmp"))
        try:
            same_db = EmbeddingDaemon(str(db), HashingEncoder(), socket_path=str(other_dir / "s.sock"))
            with pytest.raises(RuntimeError, match="already indexing"):
                asyncio.new_event_loop().run_until_complete(same_db.serve())
        finally:
            shutil.rmtree(other_dir, ignore_errors=True)
        assert client.request({"op": "health"}, path=running.socket)["db"] == str(db)



@pytest.mark.asyncio
async def test_a_memory_forgotten_or_edited_while_it_is_embedded_gets_no_stale_vectors(tmp_path):
    import sqlite3 as stdlib_sqlite3

    db = tmp_path / "race.sqlite"
    backend = await _backend(db)
    await backend.save(MemoryEntry(key="gone", value="soon forgotten"))
    await backend.save(MemoryEntry(key="edited", value="first text"))
    daemon = EmbeddingDaemon(str(db), HashingEncoder())
    real_embed = daemon._embed

    def embed_then_change(text):
        vectors = real_embed(text)
        other = stdlib_sqlite3.connect(str(db))  # another process acts mid-pass
        other.execute("DELETE FROM memories WHERE key = 'gone'")
        other.execute("UPDATE memories SET value = ? WHERE key = 'edited'", (json.dumps("second text"),))
        other.commit()
        other.close()
        return vectors

    daemon._embed = embed_then_change
    result = daemon.index_once()
    assert result["embedded"] == 0
    conn = backend._get_conn()
    assert store.indexed_shas(conn, "test-hashing") == {}

    daemon._embed = real_embed
    assert daemon.index_once()["embedded"] == 1  # the edited memory, from its new text
    assert set(store.indexed_shas(conn, "test-hashing")) == {"edited"}
    await backend.close()



def test_a_client_that_leaves_before_the_reply_does_not_break_the_daemon(tmp_path, caplog):
    import logging
    import socket as socket_module

    with caplog.at_level(logging.ERROR, logger="asyncio"), _RunningDaemon(tmp_path / "leave.sqlite") as running:
        for _ in range(5):
            conn = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
            conn.setsockopt(socket_module.SOL_SOCKET, socket_module.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
            conn.connect(str(running.socket))
            conn.sendall(b'{"op": "encode_query", "text": "hello"}\n')
            conn.close()  # gone before the reply
        time.sleep(0.3)
        assert client.request({"op": "health"}, path=running.socket)["model"] == "test-hashing"
    assert not [record for record in caplog.records if "client_connected_cb" in record.getMessage()]


class _Picky(HashingEncoder):
    """Rejects any text containing "poison"; counts calls."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        if any("poison" in text for text in texts):
            raise RuntimeError("rejected")
        return super().encode(texts)


@pytest.mark.asyncio
async def test_a_rejected_memory_waits_and_does_not_block_the_rest(tmp_path):
    db = tmp_path / "local.sqlite"
    backend = await _backend(db)
    await backend.save(MemoryEntry(key="a:bad", value="poison text"))
    await backend.save(MemoryEntry(key="b:good", value="harbor launch plan"))
    encoder = _Picky()
    daemon = EmbeddingDaemon(str(db), encoder, keys_per_pass=10)

    first = daemon.index_once()
    assert first["embedded"] == 1 and first["failed"] == 1 and first["pending"] == 0
    assert set(store.indexed_shas(backend._get_conn(), encoder.model_id)) == {"b:good"}
    calls = encoder.calls
    assert daemon.index_once()["embedded"] == 0
    assert encoder.calls == calls  # still backing off: no new call for the rejected memory

    await backend.save(MemoryEntry(key="a:bad", value="fixed text"))  # changed text is tried at once
    assert daemon.index_once()["embedded"] == 1


@pytest.mark.asyncio
async def test_a_failing_encoder_is_not_called_for_every_memory(tmp_path):
    db = tmp_path / "local.sqlite"
    backend = await _backend(db)
    for i in range(10):
        await backend.save(MemoryEntry(key=f"k:{i}", value=f"poison {i}"))
    encoder = _Picky()
    result = EmbeddingDaemon(str(db), encoder, keys_per_pass=10).index_once()
    assert encoder.calls == EmbeddingDaemon.MAX_FAILURES_PER_PASS
    assert result["pending"] == 0  # no progress: wait for the next poll, do not spin


@pytest.mark.asyncio
async def test_an_outage_stops_the_pass_without_blaming_memories(tmp_path):
    from bilinc.embeddings.encoder import WorkersAIError

    class Down(HashingEncoder):
        def __init__(self):
            super().__init__()
            self.calls = 0
            self.up = False

        def encode(self, texts):
            self.calls += 1
            if not self.up:
                raise WorkersAIError("Workers AI request failed: URLError", None)
            return super().encode(texts)

    db = tmp_path / "local.sqlite"
    backend = await _backend(db)
    for i in range(5):
        await backend.save(MemoryEntry(key=f"k:{i}", value=f"note {i}"))
    encoder = Down()
    daemon = EmbeddingDaemon(str(db), encoder, keys_per_pass=10)
    down = daemon.index_once()
    assert encoder.calls == 1 and down["failed"] == 0 and down["pending"] == 0 and down["indexed"] == 0
    encoder.up = True
    up = daemon.index_once()  # back online: everything is embedded at once
    assert up["embedded"] == 5 and up["indexed"] == 5
