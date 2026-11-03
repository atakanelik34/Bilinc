"""Report whether a SQLite database still holds the old ``vec_bilinc`` vector table, and how many vectors.

Before the vector level was removed, ``vec_bilinc`` (a ``sqlite-vec`` table) held embeddings of memories. Nothing
writes or reads it any more, but a database written by an older version can still contain it, and its vectors
are embeddings of memories that were since forgotten or rewritten. This only looks: it opens the file read-only
and changes nothing. It counts the table's rowid shadow table (``vec_bilinc_rowids``), which is a plain table and
needs no extension, and lists every object whose name starts with ``vec_bilinc``.

Usage (from a repository checkout; ``scripts/`` is not part of the package):
    python scripts/count_legacy_vec_table.py PATH_TO_bilinc.db

Dropping the table needs the ``sqlite-vec`` module and is an owner decision (backlog item LOCAL-REPAIR); see the
release note of the change that removed the vector level for the procedure.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


class CountError(RuntimeError):
    """The file could not be inspected."""


def count_legacy_vec_table(path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise CountError(f"database not found: {path}")
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise CountError(f"cannot open {path} read-only: {exc}") from exc
    try:
        objects = sorted(row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'vec\\_bilinc%' ESCAPE '\\'"))
        vectors = 0
        if "vec_bilinc_rowids" in objects:
            vectors = int(conn.execute("SELECT COUNT(*) FROM vec_bilinc_rowids").fetchone()[0])
    except sqlite3.Error as exc:
        raise CountError(f"cannot read {path}: {exc}") from exc
    finally:
        conn.close()
    return {"database": str(path), "present": "vec_bilinc" in objects, "vectors": vectors, "objects": objects}


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 1:
        print("usage: count_legacy_vec_table.py PATH_TO_DATABASE", file=sys.stderr)
        return 2
    try:
        print(json.dumps(count_legacy_vec_table(args[0])))
    except CountError as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
