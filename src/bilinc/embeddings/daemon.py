"""The embedding daemon: owns the model, keeps ``memory_embeddings`` current, encodes queries.

Indexing reads ``memories`` with a short-lived connection, embeds memories
whose text changed since they were embedded, and removes vectors of keys
that are gone or out of scope. A pass handles a bounded number of keys and
writes as it goes, so the first backfill is incremental and never holds a
long transaction. Queries share the encoder with indexing and wait for at
most one batch.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
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
    def __init__(
        self,
        db_path: str,
        encoder: Encoder,
        *,
        socket_path: Optional[str] = None,
        exclude_prefixes: Iterable[str] = RECOMMENDED_EXCLUDE_PREFIXES,
        batch_size: int = 16,
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
        todo = [key for key, (sha, _) in wanted.items() if indexed.get(key) != sha]
        batch = todo[: self.keys_per_pass]
        embedded: List[Tuple[str, str, object]] = []
        for key in batch:
            sha, text = wanted[key]
            embedded.append((key, sha, self._embed(text)))
        conn = self._connect()
        try:
            now = time.time()
            for key, sha, vectors in embedded:
                store.replace(conn, key, model, sha, vectors, now)
            removed = store.delete_keys(conn, stale, model)
            # Vectors of an older model or revision are never read again.
            removed += int(conn.execute(f"DELETE FROM {store.TABLE} WHERE model != ?", (model,)).rowcount or 0)
            conn.commit()
        finally:
            conn.close()
        self.last_pass = {
            "embedded": len(embedded),
            "removed": removed,
            "pending": len(todo) - len(batch),
            "indexed": len(wanted) - (len(todo) - len(batch)),
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
    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            request = json.loads(line.decode("utf-8") or "{}")
            if request.get("op") == "encode_query":
                vector = (await asyncio.to_thread(self.encoder.encode, [QUERY_PREFIX + str(request.get("text", ""))]))[0]
                reply = {"model": self.encoder.model_id, "vector": base64.b64encode(vector.tobytes()).decode("ascii")}
            elif request.get("op") == "health":
                reply = {"model": self.encoder.model_id, "db": self.db_path, **self.last_pass}
            else:
                reply = {"error": "unknown_op"}
        except Exception as exc:  # a bad request must not stop the daemon
            reply = {"error": type(exc).__name__}
        writer.write((json.dumps(reply) + "\n").encode("utf-8"))
        try:
            await writer.drain()
        finally:
            writer.close()

    async def serve(self) -> None:
        if self.socket_path is None:
            raise ValueError("socket_path is required to serve")
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.socket_path.parent, 0o700)
        if self.socket_path.exists():
            self.socket_path.unlink()
        server = await asyncio.start_unix_server(self._handle, path=str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        logger.info("embedding daemon on %s, model %s, db %s", self.socket_path, self.encoder.model_id, self.db_path)
        async with server:
            await asyncio.gather(server.serve_forever(), self.run_indexer())
