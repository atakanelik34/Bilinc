"""The embedding daemon: owns the model, keeps ``memory_embeddings`` current, encodes queries.

Indexing reads ``memories`` with a short-lived connection, embeds memories
whose text changed since they were embedded, and removes vectors of keys
that are gone or out of scope. A pass handles a bounded number of keys and
writes as it goes, so the first backfill is incremental and never holds a
long transaction. Queries share the encoder with indexing and wait for at
most one batch, so indexing batches are kept small.
"""
from __future__ import annotations

import asyncio
import base64
import fcntl
import json
import logging
import os
import socket
import stat
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import pysqlite3 as sqlite3  # same build the local backend uses
except ImportError:  # pragma: no cover - depends on the interpreter
    import sqlite3

from bilinc.embeddings import store
from bilinc.embeddings.encoder import Encoder
from bilinc.embeddings.text import (
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    chunk_words,
    decode_stored_value,
    memory_text,
    text_sha,
)

logger = logging.getLogger(__name__)

# Recommended scope: raw session transcripts and chat turns are long, noisy
# and duplicated by their summaries. They stay in full-text search.
RECOMMENDED_EXCLUDE_PREFIXES = ("session_archive:", "hermes_turn_")


class EmbeddingDaemon:
    FAILURE_BACKOFF = 60.0
    FAILURE_BACKOFF_MAX = 3600.0
    MAX_FAILURES_PER_PASS = 3

    def __init__(
        self,
        db_path: str,
        encoder: Encoder,
        *,
        socket_path: Optional[str] = None,
        exclude_prefixes: Iterable[str] = RECOMMENDED_EXCLUDE_PREFIXES,
        batch_size: int = 4,
        keys_per_pass: int = 200,
        poll_seconds: float = 10.0,
    ):
        self.db_path = str(Path(db_path).expanduser())
        self.encoder = encoder
        self.socket_path = Path(socket_path).expanduser() if socket_path else None
        self.exclude_prefixes = tuple(prefix for prefix in exclude_prefixes if prefix)
        self.batch_size = max(1, int(batch_size))
        self.keys_per_pass = max(1, int(keys_per_pass))
        self.poll_seconds = float(poll_seconds)
        self.last_pass: Dict[str, int] = {}
        # key -> (text sha, retry not before, backoff seconds)
        self._failed: Dict[str, Tuple[str, float, float]] = {}

    # ------------------------------------------------------------------ indexing
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA secure_delete=ON")
        return conn

    def _in_scope(self, key: str) -> bool:
        return not any(str(key).startswith(prefix) for prefix in self.exclude_prefixes)

    def _wanted(self) -> Tuple[Dict[str, Tuple[str, str]], Dict[str, str]]:
        conn = self._connect()
        try:
            store.ensure_table(conn)
            rows = conn.execute("SELECT key, value FROM memories").fetchall()
            indexed = store.indexed_shas(conn, self.encoder.model_id)
        finally:
            conn.close()
        wanted: Dict[str, Tuple[str, str]] = {}
        for key, raw in rows:
            if not self._in_scope(key):
                continue
            text = memory_text(key, decode_stored_value(raw))
            if text:
                wanted[str(key)] = (text_sha(text), text)
        return wanted, indexed

    def _current_shas(self, conn, keys: List[str]) -> Dict[str, str]:
        """Text fingerprints of the given keys as stored right now."""
        shas: Dict[str, str] = {}
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            placeholders = ",".join("?" for _ in chunk)
            for key, raw in conn.execute(f"SELECT key, value FROM memories WHERE key IN ({placeholders})", chunk):
                shas[str(key)] = text_sha(memory_text(key, decode_stored_value(raw)))
        return shas

    def _embed(self, text: str):
        chunks = [PASSAGE_PREFIX + chunk for chunk in chunk_words(text)]
        parts = [self.encoder.encode(chunks[i:i + self.batch_size]) for i in range(0, len(chunks), self.batch_size)]
        import numpy as np

        return np.vstack(parts)

    def index_once(self) -> Dict[str, int]:
        """One bounded pass. Returns counts; ``pending`` > 0 means another pass is due now."""
        wanted, indexed = self._wanted()
        model = self.encoder.model_id
        stale = [key for key in indexed if key not in wanted]
        now = time.time()
        # A memory the encoder rejected waits before it is tried again, unless its text changed.
        self._failed = {key: item for key, item in self._failed.items() if key in wanted and wanted[key][0] == item[0]}
        todo = [
            key for key, (sha, _) in wanted.items()
            if indexed.get(key) != sha and not (key in self._failed and self._failed[key][1] > now)
        ]
        batch = todo[: self.keys_per_pass]
        embedded: List[Tuple[str, str, object]] = []
        failures_in_a_row = 0
        tried = 0
        for key in batch:
            sha, text = wanted[key]
            tried += 1
            try:
                embedded.append((key, sha, self._embed(text)))
                self._failed.pop(key, None)
                failures_in_a_row = 0
            except Exception as exc:
                delay = min(self.FAILURE_BACKOFF_MAX, 2 * self._failed.get(key, (None, 0, self.FAILURE_BACKOFF / 2))[2])
                self._failed[key] = (sha, time.time() + delay, delay)
                failures_in_a_row += 1
                logger.warning("embedding failed for one memory (%s); retry in %.0f s", exc, delay)
                if failures_in_a_row >= self.MAX_FAILURES_PER_PASS:
                    break  # the encoder is down or rejects everything: stop calling it this pass
        conn = self._connect()
        written = 0
        try:
            # The write lock is taken before the re-check, so a forget or an
            # edit made while this batch was being embedded cannot be undone
            # by writing vectors of a value that is gone or has changed.
            conn.execute("BEGIN IMMEDIATE")
            current = self._current_shas(conn, [key for key, _, _ in embedded])
            now = time.time()
            for key, sha, vectors in embedded:
                if current.get(key) == sha:
                    store.replace(conn, key, model, sha, vectors, now)
                    written += 1
            removed = store.delete_keys(conn, stale, model)
            # Vectors of an older model or revision are never read again.
            removed += int(conn.execute(f"DELETE FROM {store.TABLE} WHERE model != ?", (model,)).rowcount or 0)
            conn.commit()
        finally:
            conn.close()
        remaining = len(todo) - tried
        self.last_pass = {
            "embedded": written,
            "removed": removed,
            # Only a pass that made progress asks for another right away.
            "pending": remaining if written else 0,
            "failed": len(self._failed),
            "indexed": len(wanted) - remaining - len(self._failed),
        }
        return self.last_pass

    async def run_indexer(self) -> None:
        while True:
            try:
                result = await asyncio.to_thread(self.index_once)
                if result["embedded"] or result["removed"]:
                    logger.info("embedding pass: %s", result)
                if result["pending"]:
                    continue
            except Exception:
                logger.exception("embedding pass failed; retrying")
            await asyncio.sleep(self.poll_seconds)

    # ------------------------------------------------------------------ socket
    def _lock_database(self) -> None:
        """Hold an exclusive lock for this database: one daemon writes its vectors."""
        handle = open(self.db_path + ".embed.lock", "w")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise RuntimeError(f"another embedding daemon is already indexing {self.db_path}")
        self._lock_handle = handle  # released when the process exits

    def _socket_answers(self) -> bool:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(1.0)
        try:
            probe.connect(str(self.socket_path))
            return True
        except OSError:  # refused or gone: nobody is listening
            return False
        finally:
            probe.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            request = json.loads(line.decode("utf-8") or "{}")
            if request.get("op") == "encode_query":
                text = QUERY_PREFIX + str(request.get("text", ""))
                encode_query = getattr(self.encoder, "encode_query", None)
                if encode_query is not None:  # a remote encoder: short timeout, no retries
                    vector = await asyncio.to_thread(encode_query, text)
                else:
                    vector = (await asyncio.to_thread(self.encoder.encode, [text]))[0]
                reply = {"model": self.encoder.model_id, "vector": base64.b64encode(vector.tobytes()).decode("ascii")}
            elif request.get("op") == "health":
                reply = {"model": self.encoder.model_id, "db": self.db_path, **self.last_pass}
            else:
                reply = {"error": "unknown_op"}
        except Exception as exc:  # a bad request must not stop the daemon
            reply = {"error": type(exc).__name__}
        try:
            writer.write((json.dumps(reply) + "\n").encode("utf-8"))
            await writer.drain()
        except ConnectionError:
            pass  # the client gave up (its timeout passed) before the reply; nothing to do
        finally:
            writer.close()

    async def serve(self) -> None:
        if self.socket_path is None:
            raise ValueError("socket_path is required to serve")
        self._lock_database()
        parent = self.socket_path.parent
        if not parent.exists():
            # Only a directory the daemon creates is made private; an existing
            # one (a shared /tmp, the home directory) keeps its permissions.
            parent.mkdir(parents=True, mode=0o700)
        try:
            mode = self.socket_path.lstat().st_mode
        except FileNotFoundError:
            mode = None
        if mode is not None:
            if not stat.S_ISSOCK(mode):
                raise FileExistsError(f"{self.socket_path} exists and is not a socket")
            if self._socket_answers():
                raise RuntimeError(f"an embedding daemon is already listening on {self.socket_path}")
            self.socket_path.unlink()  # a stale socket from an earlier run
        previous_umask = os.umask(0o177)  # the socket is created 0600: no window before a chmod
        try:
            server = await asyncio.start_unix_server(self._handle, path=str(self.socket_path))
        finally:
            os.umask(previous_umask)
        logger.info("embedding daemon on %s, model %s, db %s", self.socket_path, self.encoder.model_id, self.db_path)
        async with server:
            await asyncio.gather(server.serve_forever(), self.run_indexer())
