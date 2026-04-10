"""
PostgreSQL + pgvector storage backend.

Uses pgvector for semantic similarity search
and JSONB for structured metadata storage.

Schema:
- entries: id, key, memory_type, value (JSONB), source, session_id
- ccs_dimensions: JSONB (8-dim state)
- lifecycle: created_at, updated_at, last_accessed, valid_at, invalid_at, ttl
- verification: is_verified, verification_score
- importance/decay: importance, decay_rate, current_strength
- conflict: conflict_id, superseded_by
- vector embedding: embedding (vector(384))
"""
from __future__ import annotations
import json
import time
import logging
from urllib.parse import urlsplit, urlunsplit
from typing import Any, Dict, List, Optional
try:
    import asyncpg
except ImportError:
    asyncpg = None
try:
    from pgvector.asyncpg import register_vector
except ImportError:
    register_vector = None
from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.storage.backend import StorageBackend
logger = logging.getLogger(__name__)


def _redact_dsn(dsn: str) -> str:
    try:
        parsed = urlsplit(dsn)
        if not parsed.scheme:
            return "<redacted>"
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        user = parsed.username
        auth = f"{user}:***@" if user else ""
        netloc = f"{auth}{host}{port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        return "<redacted>"
class PostgresBackend(StorageBackend):
    SCHEMA_VERSION = 1

    def __init__(self, dsn: str = "postgresql://localhost/bilinc", vector_dim: int = 384):
        self.dsn = dsn
        self.vector_dim = vector_dim
        self.pool = None
        self._initialized = False

    async def init(self) -> None:
        if asyncpg is None:
            raise ImportError("asyncpg is required for PostgreSQL backend: pip install asyncpg")
        self.pool = await asyncpg.create_pool(dsn=self.dsn, max_size=10)
        async with self.pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            if register_vector:
                try:
                    await register_vector(conn)
                except Exception:
                    pass
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bilinc_entries (
                    id TEXT PRIMARY KEY,
                    key TEXT UNIQUE NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'episodic',
                    value TEXT,
                    metadata JSONB DEFAULT '{}',
                    ccs_dimensions JSONB DEFAULT '{}',
                    source TEXT DEFAULT '',
                    session_id TEXT DEFAULT '',
                    created_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW()),
                    updated_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW()),
                    last_accessed DOUBLE PRECISION DEFAULT 0,
                    access_count INT DEFAULT 0,
                    valid_at DOUBLE PRECISION,
                    invalid_at DOUBLE PRECISION,
                    ttl DOUBLE PRECISION,
                    is_verified BOOLEAN DEFAULT false,
                    verification_score DOUBLE PRECISION DEFAULT 0,
                    verification_method TEXT DEFAULT '',
                    importance DOUBLE PRECISION DEFAULT 1.0,
                    decay_rate DOUBLE PRECISION DEFAULT 0.01,
                    current_strength DOUBLE PRECISION DEFAULT 1.0,
                    conflict_id TEXT,
                    superseded_by TEXT,
                    embedding vector(384),
                    created_ts TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_bilinc_key ON bilinc_entries(key);
                CREATE INDEX IF NOT EXISTS idx_bilinc_type ON bilinc_entries(memory_type);
                CREATE INDEX IF NOT EXISTS idx_bilinc_strength ON bilinc_entries(current_strength);
                CREATE INDEX IF NOT EXISTS idx_bilinc_verified ON bilinc_entries(is_verified) WHERE is_verified = true;
                CREATE INDEX IF NOT EXISTS idx_bilinc_embedding ON bilinc_entries USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
                CREATE INDEX IF NOT EXISTS idx_bilinc_gin_metadata ON bilinc_entries USING GIN (metadata);
            """)
            current = await conn.fetchrow("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
            if current is None or current["version"] < self.SCHEMA_VERSION:
                await conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES ($1, $2)",
                    self.SCHEMA_VERSION,
                    time.time(),
                )
        self._initialized = True
        logger.info("PostgreSQL backend initialized with pgvector")
    async def save(self, entry: MemoryEntry) -> bool:
        if not self._initialized:
            await self.init()
        value_json = json.dumps(entry.value) if entry.value is not None else None
        ccs_json = json.dumps({
            (k.value if hasattr(k, 'value') else k): v
            for k, v in entry.ccs_dimensions.items()
        })
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO bilinc_entries (
                        id, key, memory_type, value, metadata, ccs_dimensions,
                        source, session_id, created_at, updated_at,
                        last_accessed, access_count, valid_at, invalid_at, ttl,
                        is_verified, verification_score, verification_method,
                        importance, decay_rate, current_strength,
                        conflict_id, superseded_by
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                              $11, $12, $13, $14, $15, $16, $17, $18,
                              $19, $20, $21, $22, $23)
                    ON CONFLICT (key) DO UPDATE SET
                        id = EXCLUDED.id,
                        memory_type = EXCLUDED.memory_type,
                        value = EXCLUDED.value,
                        metadata = EXCLUDED.metadata,
                        ccs_dimensions = EXCLUDED.ccs_dimensions,
                        source = EXCLUDED.source,
                        session_id = EXCLUDED.session_id,
                        updated_at = EXCLUDED.updated_at,
                        valid_at = EXCLUDED.valid_at,
                        invalid_at = EXCLUDED.invalid_at,
                        ttl = EXCLUDED.ttl,
                        is_verified = EXCLUDED.is_verified,
                        verification_score = EXCLUDED.verification_score,
                        verification_method = EXCLUDED.verification_method,
                        importance = EXCLUDED.importance,
                        decay_rate = EXCLUDED.decay_rate,
                        current_strength = EXCLUDED.current_strength,
                        conflict_id = EXCLUDED.conflict_id,
                        superseded_by = EXCLUDED.superseded_by
                """,
                    entry.id, entry.key, entry.memory_type.value,
                    value_json, json.dumps(entry.metadata or {}), ccs_json,
                    entry.source, entry.session_id, entry.created_at, entry.updated_at,
                    entry.last_accessed, entry.access_count, entry.valid_at, entry.invalid_at, entry.ttl,
                    entry.is_verified, entry.verification_score, entry.verification_method,
                    entry.importance, entry.decay_rate, entry.current_strength,
                    entry.conflict_id, entry.superseded_by,
                )
                return True
        except Exception as e:
            logger.error(f"Failed to save entry {entry.key}: {e}")
            return False
    async def restore(self, entry: MemoryEntry) -> bool:
        """PostgreSQL save path already preserves the provided fields."""
        return await self.save(entry)
    async def load(self, key: str) -> Optional[MemoryEntry]:
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM bilinc_entries WHERE key = $1", key
            )
            if not row:
                return None
            return self._row_to_entry(row)
    async def search_by_intent(self, intent: str, top_k: int = 10, memory_types: Optional[List[str]] = None) -> List[Dict]:
        """Search by semantic intent using BM25 (tsvector) as MVP approach."""
        if not self._initialized:
            await self.init()
        type_filter = ""
        if memory_types:
            placeholders = ','.join([f"${j}" for j in range(3, 3 + len(memory_types))])
            type_filter = f" AND memory_type IN ({placeholders})"
        sql = f"""
            SELECT *, ts_rank(
                to_tsvector('simple', COALESCE(key, '') || ' ' || COALESCE(value, '') || ' ' || COALESCE(metadata::text, '')),
                plainto_tsquery('simple', $1)) AS rank
            FROM bilinc_entries
            WHERE current_strength > 0.1 {type_filter}
            ORDER BY rank DESC, current_strength DESC
            LIMIT $2
        """
        async with self.pool.acquire() as conn:
            params = [intent, top_k]
            if memory_types:
                params.extend(memory_types)
            rows = await conn.fetch(sql, *params)
            return [{"row": self._row_to_entry(r), "rank": float(r["rank"]) if r["rank"] else 0} for r in rows]
    async def delete(self, key: str) -> bool:
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM bilinc_entries WHERE key = $1", key)
            return result == "DELETE 1"
    async def list_all(self) -> List[MemoryEntry]:
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM bilinc_entries ORDER BY importance DESC, created_at DESC")
            return [self._row_to_entry(r) for r in rows]
    async def load_by_type(self, memory_type: Any, limit: int = 100) -> List[MemoryEntry]:
        """Load entries by memory type."""
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM bilinc_entries WHERE memory_type = $1 ORDER BY importance DESC, created_at DESC LIMIT $2",
                memory_type.value if hasattr(memory_type, 'value') else str(memory_type),
                limit
            )
            return [self._row_to_entry(r) for r in rows]
    async def stats(self) -> Dict[str, Any]:
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE is_verified) as verified,
                    COUNT(*) FILTER (WHERE current_strength < 0.3) as stale,
                    COUNT(*) FILTER (WHERE conflict_id IS NOT NULL) as conflicts
                FROM bilinc_entries
            """)
            by_type_rows = await conn.fetch(
                "SELECT memory_type, COUNT(*) AS cnt FROM bilinc_entries GROUP BY memory_type"
            )
            version_row = await conn.fetchrow(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            stats = dict(row) if row else {}
            return {
                "total_entries": stats.get("total", 0),
                "verified_entries": stats.get("verified", 0),
                "stale_entries": stats.get("stale", 0),
                "conflicts": stats.get("conflicts", 0),
                "by_type": {r["memory_type"]: r["cnt"] for r in by_type_rows},
                "schema_version": version_row["version"] if version_row else 0,
                "dsn": _redact_dsn(self.dsn),
            }
    def _row_to_entry(self, row) -> MemoryEntry:
        """Convert database row to MemoryEntry."""
        import json
        value = json.loads(row["value"]) if row["value"] else None
        metadata = json.loads(row.get("metadata", "{}")) if row.get("metadata") else {}
        ccs_json = json.loads(row.get("ccs_dimensions", "{}")) if row.get("ccs_dimensions") else {}
        return MemoryEntry(
            id=row["id"],
            key=row["key"],
            memory_type=MemoryType(row["memory_type"]),
            value=value,
            metadata=metadata,
            ccs_dimensions={k: v for k, v in ccs_json.items()},
            source=row.get("source", ""),
            session_id=row.get("session_id", ""),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            last_accessed=float(row.get("last_accessed", 0)),
            access_count=row.get("access_count", 0),
            valid_at=float(row["valid_at"]) if row.get("valid_at") else None,
            invalid_at=float(row["invalid_at"]) if row.get("invalid_at") else None,
            ttl=float(row["ttl"]) if row.get("ttl") else None,
            is_verified=row.get("is_verified", False),
            verification_score=float(row.get("verification_score", 0)),
            verification_method=row.get("verification_method", ""),
            importance=float(row.get("importance", 1.0)),
            decay_rate=float(row.get("decay_rate", 0.01)),
            current_strength=float(row.get("current_strength", 1.0)),
            conflict_id=row.get("conflict_id"),
            superseded_by=row.get("superseded_by"),
        )
    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
