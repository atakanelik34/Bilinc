"""
SQLite storage backend for Bilinc.

Local-first, zero-setup persistence for Bilinc memory.
Supports all 5 brain-mimetic memory types with typed tables.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.storage.backend import StorageBackend


class SQLiteBackend(StorageBackend):
    """
    SQLite-backed persistent storage.
    - Single 'memories' table with JSON column for values
    - Indexed by key, memory_type, importance, current_strength
    - WAL mode for concurrent reads
    - Schema versioning with automatic migrations
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str = "bilinc.db"):
        self.db_path = Path(db_path).expanduser()
        self._conn = None

    @property
    def audit_db_path(self) -> str:
        """Audit trail should live in the same SQLite file for exact state recovery."""
        return str(self.db_path)
    
    def _get_conn(self):
        if self._conn is None:
            raise RuntimeError("Backend not initialized. Call .init() first.")
        return self._conn
    
    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA journal_mode=WAL")

        # Load sqlite-vec extension for vector search
        try:
            self._conn.enable_load_extension(True)
            import sqlite_vec
            sqlite_vec.load(self._conn)
        except (ImportError, Exception):
            pass  # sqlite-vec not available

        # Schema versioning table
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL
            )
        """)

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                key TEXT UNIQUE NOT NULL,
                memory_type TEXT NOT NULL,
                value TEXT,
                metadata TEXT DEFAULT '{}',
                ccs_dimensions TEXT DEFAULT '{}',
                source TEXT DEFAULT '',
                session_id TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_accessed REAL DEFAULT 0.0,
                access_count INTEGER DEFAULT 0,
                valid_at REAL,
                invalid_at REAL,
                ttl REAL,
                is_verified INTEGER DEFAULT 0,
                verification_score REAL DEFAULT 0.0,
                verification_method TEXT DEFAULT '',
                importance REAL DEFAULT 1.0,
                decay_rate REAL DEFAULT 0.01,
                current_strength REAL DEFAULT 1.0,
                conflict_id TEXT,
                superseded_by TEXT
            )
        """)
        
        for idx_name, col in [
            ("idx_type", "memory_type"), ("idx_key", "key"),
            ("idx_strength", "current_strength"), ("idx_importance", "importance"),
        ]:
            self._conn.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON memories ({col})")

        # FTS5 full-text search (insert trigger only - simple and reliable)
        try:
            self._conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts
                USING fts5(key, value_text, tokenize='porter unicode61')
            """)
            self._conn.execute("""
                CREATE TRIGGER IF NOT EXISTS mem_fts_insert AFTER INSERT ON memories BEGIN
                    INSERT OR REPLACE INTO mem_fts(rowid, key, value_text)
                    VALUES (new.rowid, new.key, COALESCE(new.value, ''));
                END
            """)
            self._conn.execute("""
                CREATE TRIGGER IF NOT EXISTS mem_fts_update AFTER UPDATE ON memories BEGIN
                    DELETE FROM mem_fts WHERE rowid = old.rowid;
                    INSERT INTO mem_fts(rowid, key, value_text)
                    VALUES (new.rowid, new.key, COALESCE(new.value, ''));
                END
            """)
            self._conn.execute("""
                CREATE TRIGGER IF NOT EXISTS mem_fts_delete AFTER DELETE ON memories BEGIN
                    DELETE FROM mem_fts WHERE rowid = old.rowid;
                END
            """)

        except Exception:
            pass  # FTS5 not available

        # Record schema version if not already present
        current = self._conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        if current is None or current["version"] < self.SCHEMA_VERSION:
            self._conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (self.SCHEMA_VERSION, time.time())
            )

        self._conn.commit()
    
    async def save(self, entry: MemoryEntry) -> bool:
        c = self._get_conn()
        entry.last_accessed = time.time()
        entry.access_count += 1
        entry.updated_at = time.time()
        return await self.restore(entry)

    async def restore(self, entry: MemoryEntry) -> bool:
        """Store an entry exactly as provided, without mutating timestamps or counters."""
        c = self._get_conn()
        c.execute("""
            INSERT INTO memories (id, key, memory_type, value, metadata, ccs_dimensions,
                source, session_id, created_at, updated_at,
                last_accessed, access_count, valid_at, invalid_at, ttl,
                is_verified, verification_score, verification_method,
                importance, decay_rate, current_strength, conflict_id, superseded_by)
            VALUES (:id, :key, :memory_type, :value, :metadata, :ccs,
                :source, :session_id, :created_at, :updated_at,
                :last_accessed, :access_count, :valid_at, :invalid_at, :ttl,
                :is_verified, :verification_score, :verification_method,
                :importance, :decay_rate, :current_strength, :conflict_id, :superseded_by)
            ON CONFLICT(key) DO UPDATE SET
                memory_type=:memory_type, value=:value, metadata=:metadata, ccs_dimensions=:ccs,
                updated_at=:updated_at, last_accessed=:last_accessed,
                access_count=:access_count,
                is_verified=:is_verified, verification_score=:verification_score,
                verification_method=:verification_method,
                importance=:importance, decay_rate=:decay_rate,
                current_strength=:current_strength,
                conflict_id=:conflict_id, superseded_by=:superseded_by
        """, {
            "id": entry.id, "key": entry.key, "memory_type": entry.memory_type.value,
            "value": json.dumps(entry.value) if entry.value is not None else None,
            "metadata": json.dumps(entry.metadata), "ccs": json.dumps(entry.ccs_dimensions),
            "source": entry.source, "session_id": entry.session_id,
            "created_at": entry.created_at, "updated_at": entry.updated_at,
            "last_accessed": entry.last_accessed, "access_count": entry.access_count,
            "valid_at": entry.valid_at, "invalid_at": entry.invalid_at, "ttl": entry.ttl,
            "is_verified": int(entry.is_verified),
            "verification_score": entry.verification_score,
            "verification_method": entry.verification_method,
            "importance": entry.importance, "decay_rate": entry.decay_rate,
            "current_strength": entry.current_strength,
            "conflict_id": entry.conflict_id, "superseded_by": entry.superseded_by,
        })
        c.commit()
        return True
    
    async def load(self, key: str) -> Optional[MemoryEntry]:
        row = self._get_conn().execute("SELECT * FROM memories WHERE key = ?", (key,)).fetchone()
        return self._row_to_entry(row) if row else None
    
    async def load_by_type(self, memory_type: MemoryType, limit: int = 100) -> List[MemoryEntry]:
        rows = self._get_conn().execute(
            "SELECT * FROM memories WHERE memory_type = ? ORDER BY importance DESC LIMIT ?",
            (memory_type.value, limit)
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]
    
    async def load_high_priority(self, limit: int = 50) -> List[MemoryEntry]:
        rows = self._get_conn().execute("""
            SELECT * FROM memories WHERE (invalid_at IS NULL OR invalid_at > ?)
              AND current_strength > 0.1
            ORDER BY importance * current_strength DESC LIMIT ?
        """, (time.time(), limit)).fetchall()
        return [self._row_to_entry(r) for r in rows]
    

    async def load_stale(self):
        import time
        now = time.time()
        rows = self._get_conn().execute("""
            SELECT * FROM memories WHERE invalid_at IS NOT NULL AND invalid_at < ? OR current_strength < 0.1
            ORDER BY current_strength ASC
        """, (now,)).fetchall()
        from bilinc.core.models import MemoryEntry
        return [self._row_to_entry(r) for r in rows]

    async def delete(self, key: str) -> bool:
        r = self._get_conn().execute("DELETE FROM memories WHERE key = ?", (key,))
        self._get_conn().commit()
        return r.rowcount > 0
    
    async def list_all(self) -> List[MemoryEntry]:
        rows = self._get_conn().execute("SELECT * FROM memories ORDER BY created_at DESC").fetchall()
        return [self._row_to_entry(r) for r in rows]
    
    async def count_by_type(self) -> Dict[str, int]:
        rows = self._get_conn().execute("SELECT memory_type, COUNT(*) as cnt FROM memories GROUP BY memory_type")
        return {r["memory_type"]: r["cnt"] for r in rows}
    
    def fts_rebuild(self):
        """Rebuild FTS5 index from memories table. Call during consolidation."""
        try:
            self._conn.execute("INSERT INTO mem_fts(mem_fts) VALUES('rebuild')")
            self._conn.commit()
            return True
        except Exception:
            return False

    def fts_search(self, query: str, limit: int = 10):
        """Direct FTS5 search. Returns (rowid, key, rank) tuples."""
        try:
            fts_query = ' OR '.join(query.split())
            return self._conn.execute("""
                SELECT rowid, key, rank FROM mem_fts
                WHERE mem_fts MATCH ?
                ORDER BY rank LIMIT ?
            """, (fts_query, limit)).fetchall()
        except Exception:
            return []

    async def stats(self) -> Dict:
        c = self._get_conn()
        total = c.execute("SELECT COUNT(*) as cnt FROM memories").fetchone()["cnt"]
        by_type = await self.count_by_type()
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        # Get schema version
        ver_row = c.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        schema_version = ver_row["version"] if ver_row else 0

        return {
            "total_entries": total,
            "by_type": by_type,
            "db_size_bytes": db_size,
            "db_path": str(self.db_path),
            "schema_version": schema_version,
        }
    
    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def _row_to_entry(self, row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"], memory_type=MemoryType(row["memory_type"]),
            key=row["key"], value=json.loads(row["value"]) if row["value"] is not None else None,
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            ccs_dimensions=json.loads(row["ccs_dimensions"]) if row["ccs_dimensions"] else {},
            source=row["source"] or "", session_id=row["session_id"] or "",
            created_at=row["created_at"], updated_at=row["updated_at"],
            last_accessed=row["last_accessed"], access_count=row["access_count"],
            valid_at=row["valid_at"], invalid_at=row["invalid_at"], ttl=row["ttl"],
            is_verified=bool(row["is_verified"]), verification_score=row["verification_score"],
            verification_method=row["verification_method"] or "",
            importance=row["importance"], decay_rate=row["decay_rate"],
            current_strength=row["current_strength"],
            conflict_id=row["conflict_id"], superseded_by=row["superseded_by"],
        )
