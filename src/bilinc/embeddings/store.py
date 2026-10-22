"""The ``memory_embeddings`` table: one row per (memory key, model, chunk).

Only the embedding daemon writes it. Readers (recall in the MCP processes)
use their existing connection to the same file. Vectors are float32 BLOBs,
L2-normalized, so a dot product is the cosine.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

TABLE = "memory_embeddings"


def ensure_table(conn) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            memory_key TEXT NOT NULL,
            model TEXT NOT NULL,
            chunk INTEGER NOT NULL,
            text_sha TEXT NOT NULL,
            dim INTEGER NOT NULL,
            vector BLOB NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (memory_key, model, chunk)
        )
    """)
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_model ON {TABLE} (model)")
    conn.commit()


def table_exists(conn) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)).fetchone()
    return row is not None


def indexed_shas(conn, model: str) -> Dict[str, str]:
    """The text fingerprint each key was embedded from, for one model."""
    rows = conn.execute(f"SELECT memory_key, text_sha FROM {TABLE} WHERE model = ? AND chunk = 0", (model,))
    return {str(key): str(sha) for key, sha in rows}


def replace(conn, key: str, model: str, sha: str, vectors: np.ndarray, now: float) -> None:
    conn.execute(f"DELETE FROM {TABLE} WHERE memory_key = ? AND model = ?", (key, model))
    conn.executemany(
        f"INSERT INTO {TABLE} (memory_key, model, chunk, text_sha, dim, vector, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (key, model, chunk, sha, int(vector.shape[0]), np.asarray(vector, dtype=np.float32).tobytes(), now)
            for chunk, vector in enumerate(vectors)
        ],
    )


def delete_keys(conn, keys: Iterable[str], model: str | None = None) -> int:
    removed = 0
    for key in keys:
        if model is None:
            cursor = conn.execute(f"DELETE FROM {TABLE} WHERE memory_key = ?", (key,))
        else:
            cursor = conn.execute(f"DELETE FROM {TABLE} WHERE memory_key = ? AND model = ?", (key, model))
        removed += int(cursor.rowcount or 0)
    return removed


def signature(conn, model: str) -> Tuple[int, float]:
    """Changes whenever a vector for the model is written or removed."""
    count, latest = conn.execute(
        f"SELECT count(*), coalesce(max(updated_at), 0) FROM {TABLE} WHERE model = ?", (model,)
    ).fetchone()
    return int(count), float(latest)


def load(conn, model: str) -> Tuple[List[str], np.ndarray]:
    """Every vector for the model: one key per row (a key repeats once per chunk)."""
    keys: List[str] = []
    blobs: List[bytes] = []
    dim = 0
    for key, vector_dim, blob in conn.execute(
        f"SELECT memory_key, dim, vector FROM {TABLE} WHERE model = ? ORDER BY memory_key, chunk", (model,)
    ):
        keys.append(str(key))
        blobs.append(bytes(blob))
        dim = int(vector_dim)
    if not keys:
        return [], np.zeros((0, 0), dtype=np.float32)
    matrix = np.frombuffer(b"".join(blobs), dtype=np.float32).reshape(len(keys), dim)
    return keys, matrix


def best_per_key(keys: Sequence[str], scores: np.ndarray) -> Dict[str, float]:
    """A memory scores as its best chunk."""
    best: Dict[str, float] = {}
    for key, score in zip(keys, scores.tolist()):
        if score > best.get(key, -2.0):
            best[key] = score
    return best
