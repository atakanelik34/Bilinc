"""
SQLite storage backend for Bilinc.

Local-first, zero-setup persistence for Bilinc memory.
Supports all 5 brain-mimetic memory types with typed tables.
"""
from __future__ import annotations

import json
try:
    import pysqlite3 as sqlite3  # macOS: has SQLITE_ENABLE_LOAD_EXTENSION
except ImportError:
    import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.event_ledger import MemoryEvent, create_memory_event, event_from_dict, stable_json
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

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS eval_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_version INTEGER NOT NULL DEFAULT 1,
                tool_name TEXT NOT NULL,
                query TEXT NOT NULL,
                retrieved_keys TEXT NOT NULL DEFAULT '[]',
                retrieved_scores TEXT NOT NULL DEFAULT '[]',
                memory_types TEXT NOT NULL DEFAULT '[]',
                latency_ms INTEGER NOT NULL DEFAULT 0,
                detail TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_candidates_created_at ON eval_candidates (created_at)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_candidates_tool ON eval_candidates (tool_name)")

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_events (
                id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                specversion TEXT NOT NULL,
                type TEXT NOT NULL,
                source TEXT NOT NULL,
                subject TEXT NOT NULL,
                time REAL NOT NULL,
                operation TEXT NOT NULL,
                memory_key TEXT,
                memory_type TEXT,
                project_id TEXT,
                org_id TEXT,
                actor_type TEXT NOT NULL DEFAULT 'unknown',
                actor_id_hash TEXT,
                request_id TEXT,
                before_hash TEXT,
                after_hash TEXT,
                payload_ref TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                audit_log_id INTEGER,
                prev_event_hash TEXT,
                event_hash TEXT NOT NULL,
                checkpoint_root TEXT,
                datacontenttype TEXT NOT NULL DEFAULT 'application/json'
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_time ON memory_events (time, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_operation ON memory_events (operation)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_memory_key ON memory_events (memory_key)")

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                memory_key TEXT NOT NULL,
                holder TEXT NOT NULL,
                subject TEXT NOT NULL,
                claim TEXT NOT NULL,
                kind TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5,
                valid_at REAL,
                invalid_at REAL,
                source TEXT DEFAULT '',
                provenance_id TEXT DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                superseded_by TEXT,
                metadata TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        for idx_name, col in [
            ("idx_claims_memory_key", "memory_key"),
            ("idx_claims_holder_active", "holder, active"),
            ("idx_claims_subject_active", "subject, active"),
            ("idx_claims_kind_active", "kind, active"),
        ]:
            self._conn.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON claims ({col})")

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT 'unknown',
                aliases TEXT NOT NULL DEFAULT '[]',
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_canonical_name ON entities (canonical_name)")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS entity_mentions (
                id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                memory_key TEXT NOT NULL,
                mention_text TEXT NOT NULL,
                source TEXT DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.5,
                created_at REAL NOT NULL
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity_id ON entity_mentions (entity_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_mentions_memory_key ON entity_mentions (memory_key)")

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
        return [self._row_to_entry(r) for r in rows]

    async def delete(self, key: str) -> bool:
        conn = self._get_conn()
        conn.execute("DELETE FROM claims WHERE memory_key = ?", (key,))
        conn.execute("DELETE FROM entity_mentions WHERE memory_key = ?", (key,))
        self._prune_orphan_entities(conn)
        r = conn.execute("DELETE FROM memories WHERE key = ?", (key,))
        conn.commit()
        return r.rowcount > 0

    async def delete_entity_mentions_for_memory_key(self, memory_key: str) -> int:
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM entity_mentions WHERE memory_key = ?", (memory_key,))
        self._prune_orphan_entities(conn)
        conn.commit()
        return cursor.rowcount

    def _prune_orphan_entities(self, conn) -> int:
        cursor = conn.execute(
            """
            DELETE FROM entities
            WHERE id NOT IN (SELECT DISTINCT entity_id FROM entity_mentions)
            """
        )
        return cursor.rowcount

    async def save_entity(self, entity) -> bool:
        from bilinc.core.entities import Entity

        if not isinstance(entity, Entity):
            raise TypeError("entity must be Entity")
        entity.updated_at = time.time()
        conn = self._get_conn()
        existing = conn.execute("SELECT aliases FROM entities WHERE id = ?", (entity.id,)).fetchone()
        aliases = list(entity.aliases)
        if existing:
            try:
                aliases.extend(json.loads(existing["aliases"] or "[]"))
            except Exception:
                pass
        deduped_aliases = []
        seen = set()
        for alias in aliases:
            key = " ".join(str(alias).strip().lower().split())
            if key and key not in seen:
                seen.add(key)
                deduped_aliases.append(str(alias).strip())
        conn.execute(
            """
            INSERT INTO entities (id, canonical_name, entity_type, aliases, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                canonical_name=excluded.canonical_name,
                entity_type=excluded.entity_type,
                aliases=excluded.aliases,
                metadata=excluded.metadata,
                updated_at=excluded.updated_at
            """,
            (
                entity.id,
                entity.canonical_name,
                entity.entity_type,
                json.dumps(deduped_aliases),
                json.dumps(entity.metadata),
                entity.created_at,
                entity.updated_at,
            ),
        )
        conn.commit()
        return True

    async def add_entity_alias(self, entity_id: str, alias: str) -> bool:
        entity = await self.find_entity_by_id(entity_id)
        if entity is None:
            return False
        entity.aliases.append(alias)
        await self.save_entity(entity)
        return True

    async def save_entity_mention(self, mention) -> bool:
        from bilinc.core.entities import EntityMention

        if not isinstance(mention, EntityMention):
            raise TypeError("mention must be EntityMention")
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO entity_mentions (id, entity_id, memory_key, mention_text, source, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                entity_id=excluded.entity_id,
                memory_key=excluded.memory_key,
                mention_text=excluded.mention_text,
                source=excluded.source,
                confidence=excluded.confidence
            """,
            (mention.id, mention.entity_id, mention.memory_key, mention.mention_text, mention.source, mention.confidence, mention.created_at),
        )
        conn.commit()
        return True

    async def find_entity_by_id(self, entity_id: str):
        row = self._get_conn().execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
        return self._row_to_entity(row) if row else None

    async def find_entity(self, name: str):
        normalized = " ".join(str(name).strip().lower().split())
        rows = self._get_conn().execute("SELECT * FROM entities").fetchall()
        for row in rows:
            entity = self._row_to_entity(row)
            names = [entity.canonical_name, *entity.aliases]
            if any(" ".join(candidate.strip().lower().split()) == normalized for candidate in names):
                return entity
        return None

    async def list_entity_mentions(self, entity_id: str | None = None, memory_key: str | None = None, limit: int = 100):
        sql = "SELECT * FROM entity_mentions WHERE 1=1"
        params: list[object] = []
        if entity_id is not None:
            sql += " AND entity_id = ?"
            params.append(entity_id)
        if memory_key is not None:
            sql += " AND memory_key = ?"
            params.append(memory_key)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        rows = self._get_conn().execute(sql, tuple(params)).fetchall()
        return [self._row_to_entity_mention(row) for row in rows]

    async def list_memories_for_entity(self, name: str, limit: int = 100) -> list[str]:
        entity = await self.find_entity(name)
        if entity is None:
            return []
        rows = self._get_conn().execute(
            "SELECT DISTINCT memory_key FROM entity_mentions WHERE entity_id = ? ORDER BY created_at DESC LIMIT ?",
            (entity.id, int(limit)),
        ).fetchall()
        return [row["memory_key"] for row in rows]

    def _row_to_entity(self, row):
        from bilinc.core.entities import Entity

        return Entity.from_dict({
            "id": row["id"],
            "canonical_name": row["canonical_name"],
            "entity_type": row["entity_type"],
            "aliases": json.loads(row["aliases"] or "[]"),
            "metadata": json.loads(row["metadata"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })

    def _row_to_entity_mention(self, row):
        from bilinc.core.entities import EntityMention

        return EntityMention.from_dict({
            "id": row["id"],
            "entity_id": row["entity_id"],
            "memory_key": row["memory_key"],
            "mention_text": row["mention_text"],
            "source": row["source"],
            "confidence": row["confidence"],
            "created_at": row["created_at"],
        })

    async def delete_claims_for_memory_key(self, memory_key: str) -> int:
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM claims WHERE memory_key = ?", (memory_key,))
        conn.commit()
        return cursor.rowcount

    async def deactivate_claims_for_memory_key(self, memory_key: str, keep_ids: list[str] | None = None) -> int:
        conn = self._get_conn()
        keep_ids = keep_ids or []
        if keep_ids:
            placeholders = ",".join("?" for _ in keep_ids)
            cursor = conn.execute(
                f"UPDATE claims SET active = 0, updated_at = ? WHERE memory_key = ? AND id NOT IN ({placeholders})",
                (time.time(), memory_key, *keep_ids),
            )
        else:
            cursor = conn.execute(
                "UPDATE claims SET active = 0, updated_at = ? WHERE memory_key = ?",
                (time.time(), memory_key),
            )
        conn.commit()
        return cursor.rowcount

    async def save_claim(self, claim) -> bool:
        from bilinc.core.models import Claim

        if not isinstance(claim, Claim):
            raise TypeError("claim must be Claim")
        conn = self._get_conn()
        claim.updated_at = time.time()
        conn.execute(
            """
            INSERT INTO claims (
                id, memory_key, holder, subject, claim, kind, confidence,
                valid_at, invalid_at, source, provenance_id, active, superseded_by,
                metadata, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                memory_key=excluded.memory_key,
                holder=excluded.holder,
                subject=excluded.subject,
                claim=excluded.claim,
                kind=excluded.kind,
                confidence=excluded.confidence,
                valid_at=excluded.valid_at,
                invalid_at=excluded.invalid_at,
                source=excluded.source,
                provenance_id=excluded.provenance_id,
                active=excluded.active,
                superseded_by=excluded.superseded_by,
                metadata=excluded.metadata,
                updated_at=excluded.updated_at
            """,
            (
                claim.id,
                claim.memory_key,
                claim.holder,
                claim.subject,
                claim.claim,
                claim.kind.value,
                claim.confidence,
                claim.valid_at,
                claim.invalid_at,
                claim.source,
                claim.provenance_id,
                int(claim.active),
                claim.superseded_by,
                json.dumps(claim.metadata),
                claim.created_at,
                claim.updated_at,
            ),
        )
        conn.commit()
        return True

    async def list_claims(
        self,
        holder: str | None = None,
        subject: str | None = None,
        kind: str | None = None,
        active: bool | None = True,
        limit: int = 100,
    ):
        sql = "SELECT * FROM claims WHERE 1=1"
        params: list[object] = []
        if holder is not None:
            sql += " AND holder = ?"
            params.append(holder)
        if subject is not None:
            sql += " AND subject = ?"
            params.append(subject)
        if kind is not None:
            sql += " AND kind = ?"
            params.append(getattr(kind, "value", str(kind)))
        if active is not None:
            sql += " AND active = ?"
            params.append(int(active))
            if active:
                sql += " AND (valid_at IS NULL OR valid_at <= ?) AND (invalid_at IS NULL OR invalid_at > ?)"
                now = time.time()
                params.extend([now, now])
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(int(limit))
        rows = self._get_conn().execute(sql, tuple(params)).fetchall()
        return [self._row_to_claim(row) for row in rows]

    async def search_claims(self, query: str, limit: int = 10):
        needle = f"%{query}%"
        now = time.time()
        rows = self._get_conn().execute(
            """
            SELECT * FROM claims
            WHERE active = 1
              AND (valid_at IS NULL OR valid_at <= ?)
              AND (invalid_at IS NULL OR invalid_at > ?)
              AND (claim LIKE ? OR subject LIKE ? OR holder LIKE ?)
            ORDER BY updated_at DESC LIMIT ?
            """,
            (now, now, needle, needle, needle, int(limit)),
        ).fetchall()
        return [self._row_to_claim(row) for row in rows]

    async def supersede_claim(self, old_id: str, new_claim) -> bool:
        await self.save_claim(new_claim)
        conn = self._get_conn()
        conn.execute(
            "UPDATE claims SET active = 0, superseded_by = ?, updated_at = ? WHERE id = ?",
            (new_claim.id, time.time(), old_id),
        )
        conn.commit()
        return True

    def _row_to_claim(self, row):
        from bilinc.core.models import Claim

        return Claim.from_dict({
            "id": row["id"],
            "memory_key": row["memory_key"],
            "holder": row["holder"],
            "subject": row["subject"],
            "claim": row["claim"],
            "kind": row["kind"],
            "confidence": row["confidence"],
            "valid_at": row["valid_at"],
            "invalid_at": row["invalid_at"],
            "source": row["source"],
            "provenance_id": row["provenance_id"],
            "active": bool(row["active"]),
            "superseded_by": row["superseded_by"],
            "metadata": json.loads(row["metadata"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })

    async def append_memory_event(
        self,
        *,
        operation: str,
        subject: str,
        source: str = "bilinc.core.stateplane",
        memory_key: Optional[str] = None,
        memory_type: Optional[str] = None,
        payload_json: Optional[dict] = None,
        before_value=None,
        after_value=None,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        actor_type: str = "unknown",
        actor_id: Optional[str] = None,
        request_id: Optional[str] = None,
        payload_ref: Optional[str] = None,
        audit_log_id: Optional[int] = None,
        checkpoint_root: Optional[str] = None,
    ) -> MemoryEvent:
        """Append one semantic memory event with SQLite write serialization."""
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT event_hash FROM memory_events ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            prev_event_hash = previous["event_hash"] if previous else None
            event = create_memory_event(
                operation=operation,
                subject=subject,
                source=source,
                memory_key=memory_key,
                memory_type=memory_type,
                payload_json=payload_json,
                before_value=before_value,
                after_value=after_value,
                project_id=project_id,
                org_id=org_id,
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
                payload_ref=payload_ref,
                audit_log_id=audit_log_id,
                prev_event_hash=prev_event_hash,
                checkpoint_root=checkpoint_root,
            )
            conn.execute(
                """
                INSERT INTO memory_events (
                    id, schema_version, specversion, type, source, subject, time,
                    operation, memory_key, memory_type, project_id, org_id,
                    actor_type, actor_id_hash, request_id, before_hash, after_hash,
                    payload_ref, payload_json, audit_log_id, prev_event_hash,
                    event_hash, checkpoint_root, datacontenttype
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.schema_version,
                    event.specversion,
                    event.type,
                    event.source,
                    event.subject,
                    event.time,
                    event.operation,
                    event.memory_key,
                    event.memory_type,
                    event.project_id,
                    event.org_id,
                    event.actor_type,
                    event.actor_id_hash,
                    event.request_id,
                    event.before_hash,
                    event.after_hash,
                    event.payload_ref,
                    stable_json(event.payload_json),
                    event.audit_log_id,
                    event.prev_event_hash,
                    event.event_hash,
                    event.checkpoint_root,
                    event.datacontenttype,
                ),
            )
            conn.commit()
            return event
        except Exception:
            conn.rollback()
            raise

    async def list_memory_events(
        self,
        *,
        operation: Optional[str] = None,
        memory_key: Optional[str] = None,
        ids: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[MemoryEvent]:
        """Return semantic memory events ordered oldest-first."""
        params: list[object] = []
        clauses: list[str] = []
        if operation is not None:
            clauses.append("operation = ?")
            params.append(operation)
        if memory_key is not None:
            clauses.append("memory_key = ?")
            params.append(memory_key)
        if ids is not None:
            ids_l = [str(item) for item in ids]
            if not ids_l:
                return []
            clauses.append("id IN (" + ",".join("?" for _ in ids_l) + ")")
            params.extend(ids_l)
        sql = "SELECT * FROM memory_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rowid ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._get_conn().execute(sql, tuple(params)).fetchall()
        events = [self._row_to_memory_event(row) for row in rows]
        if ids is not None:
            order = {str(event_id): idx for idx, event_id in enumerate(ids)}
            events.sort(key=lambda event: order.get(event.id, len(order)))
        return events

    def _row_to_memory_event(self, row) -> MemoryEvent:
        return event_from_dict({
            "id": row["id"],
            "schema_version": row["schema_version"],
            "specversion": row["specversion"],
            "type": row["type"],
            "source": row["source"],
            "subject": row["subject"],
            "time": row["time"],
            "operation": row["operation"],
            "memory_key": row["memory_key"],
            "memory_type": row["memory_type"],
            "project_id": row["project_id"],
            "org_id": row["org_id"],
            "actor_type": row["actor_type"],
            "actor_id_hash": row["actor_id_hash"],
            "request_id": row["request_id"],
            "before_hash": row["before_hash"],
            "after_hash": row["after_hash"],
            "payload_ref": row["payload_ref"],
            "payload_json": json.loads(row["payload_json"] or "{}"),
            "audit_log_id": row["audit_log_id"],
            "prev_event_hash": row["prev_event_hash"],
            "event_hash": row["event_hash"],
            "checkpoint_root": row["checkpoint_root"],
            "datacontenttype": row["datacontenttype"],
        })

    async def record_eval_candidate(self, row) -> bool:
        """Persist one opt-in retrieval eval candidate row."""
        from bilinc.eval.capture import EvalCaptureRow, dedupe_preserve_order

        if not isinstance(row, EvalCaptureRow):
            raise TypeError("row must be EvalCaptureRow")
        conn = self._get_conn()
        retrieved_keys = dedupe_preserve_order(row.retrieved_keys)
        conn.execute(
            """
            INSERT INTO eval_candidates (
                schema_version, tool_name, query, retrieved_keys, retrieved_scores,
                memory_types, latency_ms, detail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.schema_version,
                row.tool_name,
                row.query,
                json.dumps(retrieved_keys),
                json.dumps(row.retrieved_scores[:len(retrieved_keys)]),
                json.dumps(row.memory_types[:len(retrieved_keys)]),
                row.latency_ms,
                json.dumps(row.detail),
                row.created_at,
            ),
        )
        conn.commit()
        return True

    async def list_eval_candidates(self, since: float | None = None, limit: int | None = None):
        """Return captured retrieval eval rows ordered oldest-first."""
        params: list[object] = []
        sql = "SELECT * FROM eval_candidates"
        if since is not None:
            sql += " WHERE created_at >= ?"
            params.append(float(since))
        sql += " ORDER BY created_at ASC, id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._get_conn().execute(sql, tuple(params)).fetchall()
        return [self._eval_row_to_capture(row) for row in rows]

    def _eval_row_to_capture(self, row):
        from bilinc.eval.capture import EvalCaptureRow

        return EvalCaptureRow(
            schema_version=int(row["schema_version"]),
            tool_name=row["tool_name"],
            query=row["query"],
            retrieved_keys=[str(value) for value in json.loads(row["retrieved_keys"] or "[]")],
            retrieved_scores=[float(value) for value in json.loads(row["retrieved_scores"] or "[]")],
            memory_types=[str(value) for value in json.loads(row["memory_types"] or "[]")],
            latency_ms=int(row["latency_ms"]),
            created_at=float(row["created_at"]),
            detail=dict(json.loads(row["detail"] or "{}")),
        )
    
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
    
    @staticmethod
    def _decode_value(raw: Optional[str]):
        """Decode stored JSON values, accepting legacy raw text rows as strings."""
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def _row_to_entry(self, row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"], memory_type=MemoryType(row["memory_type"]),
            key=row["key"], value=self._decode_value(row["value"]),
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
