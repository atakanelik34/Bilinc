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
from bilinc.core.event_ledger import MemoryEvent, create_memory_event, event_from_dict
from bilinc.observability.health import _redact_dsn
from bilinc.storage.backend import StorageBackend
from bilinc.storage.postgres_tenancy import TENANT_TABLES, quoted, search_path_setting, validate_schema_name
logger = logging.getLogger(__name__)


class PostgresBackend(StorageBackend):
    SCHEMA_VERSION = 1

    def __init__(
        self,
        dsn: str = "postgresql://localhost/bilinc",
        vector_dim: int = 384,
        schema: Optional[str] = None,
    ):
        self.dsn = dsn
        self.vector_dim = vector_dim
        # With a schema, this backend serves exactly one tenant: every pooled
        # connection pins search_path to it (see postgres_tenancy).
        self.schema = validate_schema_name(schema) if schema is not None else None
        self.pool = None
        self._initialized = False

    async def init(self) -> None:
        if asyncpg is None:
            raise ImportError("asyncpg is required for PostgreSQL backend: pip install asyncpg")
        if self.schema:
            # The schema must exist before any pooled connection pins its
            # search_path to it; otherwise tables would silently land in public.
            bootstrap = await asyncpg.connect(dsn=self.dsn)
            try:
                await bootstrap.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
                await bootstrap.execute(f"CREATE SCHEMA IF NOT EXISTS {quoted(self.schema)}")
            finally:
                await bootstrap.close()
            # Small, self-draining pool: one per active project, not ten.
            self.pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=0,
                max_size=4,
                max_inactive_connection_lifetime=60.0,
                server_settings={"search_path": search_path_setting(self.schema)},
            )
        else:
            self.pool = await asyncpg.create_pool(dsn=self.dsn, max_size=10)
        async with self.pool.acquire() as conn:
            if self.schema and await conn.fetchval("SELECT current_schema()") != self.schema:
                raise RuntimeError("tenant_schema_not_active")
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
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS eval_candidates (
                    id BIGSERIAL PRIMARY KEY,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    tool_name TEXT NOT NULL,
                    query TEXT NOT NULL,
                    retrieved_keys JSONB NOT NULL DEFAULT '[]',
                    retrieved_scores JSONB NOT NULL DEFAULT '[]',
                    memory_types JSONB NOT NULL DEFAULT '[]',
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    detail JSONB NOT NULL DEFAULT '{}',
                    created_at DOUBLE PRECISION NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_eval_candidates_created_at ON eval_candidates(created_at);
                CREATE INDEX IF NOT EXISTS idx_eval_candidates_tool ON eval_candidates(tool_name);
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bilinc_claims (
                    id TEXT PRIMARY KEY,
                    memory_key TEXT NOT NULL,
                    holder TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
                    valid_at DOUBLE PRECISION,
                    invalid_at DOUBLE PRECISION,
                    source TEXT DEFAULT '',
                    provenance_id TEXT DEFAULT '',
                    active BOOLEAN NOT NULL DEFAULT true,
                    superseded_by TEXT,
                    metadata JSONB DEFAULT '{}',
                    created_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_bilinc_claims_memory_key ON bilinc_claims(memory_key);
                CREATE INDEX IF NOT EXISTS idx_bilinc_claims_holder_active ON bilinc_claims(holder, active);
                CREATE INDEX IF NOT EXISTS idx_bilinc_claims_subject_active ON bilinc_claims(subject, active);
                CREATE INDEX IF NOT EXISTS idx_bilinc_claims_kind_active ON bilinc_claims(kind, active);
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL DEFAULT 'unknown',
                    aliases JSONB NOT NULL DEFAULT '[]',
                    metadata JSONB NOT NULL DEFAULT '{}',
                    created_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_entities_canonical_name ON entities(canonical_name);
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS entity_mentions (
                    id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    mention_text TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
                    created_at DOUBLE PRECISION NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity_id ON entity_mentions(entity_id);
                CREATE INDEX IF NOT EXISTS idx_entity_mentions_memory_key ON entity_mentions(memory_key);
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_events (
                    id TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    specversion TEXT NOT NULL,
                    type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    time DOUBLE PRECISION NOT NULL,
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
                    payload_json JSONB NOT NULL DEFAULT '{}',
                    audit_log_id BIGINT,
                    prev_event_hash TEXT,
                    event_hash TEXT NOT NULL,
                    checkpoint_root TEXT,
                    datacontenttype TEXT NOT NULL DEFAULT 'application/json'
                );
                CREATE INDEX IF NOT EXISTS idx_memory_events_operation ON memory_events(operation);
                CREATE INDEX IF NOT EXISTS idx_memory_events_memory_key ON memory_events(memory_key);
                CREATE INDEX IF NOT EXISTS idx_memory_events_time ON memory_events(time);
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    timestamp DOUBLE PRECISION NOT NULL,
                    op_type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    before_value TEXT,
                    after_value TEXT,
                    data_hash TEXT NOT NULL,
                    prev_root TEXT NOT NULL,
                    root_hash TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_audit_log_key ON audit_log(key);
                CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
                CREATE INDEX IF NOT EXISTS idx_audit_log_op ON audit_log(op_type);
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_bilinc_entries_fts
                ON bilinc_entries
                USING GIN (to_tsvector('simple',
                    COALESCE(key, '') || ' ' ||
                    COALESCE(value::text, '') || ' ' ||
                    COALESCE(metadata::text, '')
                ))
            """)
            current = await conn.fetchrow("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
            if current is None or current["version"] < self.SCHEMA_VERSION:
                await conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES ($1, $2)",
                    self.SCHEMA_VERSION,
                    time.time(),
                )
            if self.schema:
                # Fail closed: every table must resolve inside the tenant schema,
                # so no query can fall through to a shared table in public.
                present = {
                    row["table_name"]
                    for row in await conn.fetch(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema = $1",
                        self.schema,
                    )
                }
                missing = [table for table in TENANT_TABLES if table not in present]
                if missing:
                    raise RuntimeError("tenant_schema_incomplete:" + ",".join(missing))
        self._initialized = True
        logger.info("PostgreSQL backend initialized with pgvector")

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
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                previous = await conn.fetchrow(
                    "SELECT event_hash FROM memory_events ORDER BY time DESC, id DESC LIMIT 1"
                )
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
                    prev_event_hash=previous["event_hash"] if previous else None,
                    checkpoint_root=checkpoint_root,
                )
                await conn.execute(
                    """
                    INSERT INTO memory_events (
                        id, schema_version, specversion, type, source, subject, time,
                        operation, memory_key, memory_type, project_id, org_id,
                        actor_type, actor_id_hash, request_id, before_hash, after_hash,
                        payload_ref, payload_json, audit_log_id, prev_event_hash,
                        event_hash, checkpoint_root, datacontenttype
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                              $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24)
                    """,
                    event.id, event.schema_version, event.specversion, event.type,
                    event.source, event.subject, event.time, event.operation,
                    event.memory_key, event.memory_type, event.project_id, event.org_id,
                    event.actor_type, event.actor_id_hash, event.request_id,
                    event.before_hash, event.after_hash, event.payload_ref,
                    json.dumps(event.payload_json or {}), event.audit_log_id,
                    event.prev_event_hash, event.event_hash, event.checkpoint_root,
                    event.datacontenttype,
                )
                return event

    async def list_memory_events(
        self,
        *,
        operation: Optional[str] = None,
        memory_key: Optional[str] = None,
        ids: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[MemoryEvent]:
        if not self._initialized:
            await self.init()
        clauses: list[str] = []
        params: list[Any] = []
        if operation is not None:
            params.append(operation)
            clauses.append(f"operation = ${len(params)}")
        if memory_key is not None:
            params.append(memory_key)
            clauses.append(f"memory_key = ${len(params)}")
        if ids is not None:
            values = [str(item) for item in ids]
            if not values:
                return []
            params.append(values)
            clauses.append(f"id = ANY(${len(params)}::text[])")
        sql = "SELECT * FROM memory_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY time ASC, id ASC"
        if limit is not None:
            params.append(int(limit))
            sql += f" LIMIT ${len(params)}"
        rows = await self.pool.fetch(sql, *params)
        events = []
        for row in rows:
            payload = row["payload_json"]
            if isinstance(payload, str):
                payload = json.loads(payload or "{}")
            events.append(event_from_dict({
                "id": row["id"], "schema_version": row["schema_version"],
                "specversion": row["specversion"], "type": row["type"],
                "source": row["source"], "subject": row["subject"],
                "time": row["time"], "operation": row["operation"],
                "memory_key": row["memory_key"], "memory_type": row["memory_type"],
                "project_id": row["project_id"], "org_id": row["org_id"],
                "actor_type": row["actor_type"], "actor_id_hash": row["actor_id_hash"],
                "request_id": row["request_id"], "before_hash": row["before_hash"],
                "after_hash": row["after_hash"], "payload_ref": row["payload_ref"],
                "payload_json": payload or {}, "audit_log_id": row["audit_log_id"],
                "prev_event_hash": row["prev_event_hash"], "event_hash": row["event_hash"],
                "checkpoint_root": row["checkpoint_root"],
                "datacontenttype": row["datacontenttype"],
            }))
        if ids is not None:
            order = {str(event_id): index for index, event_id in enumerate(ids)}
            events.sort(key=lambda event: order.get(event.id, len(order)))
        return events

    async def save_entity(self, entity) -> bool:
        from bilinc.core.entities import Entity
        if not isinstance(entity, Entity):
            raise TypeError("entity must be Entity")
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO entities (
                    id, canonical_name, entity_type, aliases, metadata, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT(id) DO UPDATE SET
                    canonical_name=EXCLUDED.canonical_name,
                    entity_type=EXCLUDED.entity_type,
                    aliases=EXCLUDED.aliases,
                    metadata=EXCLUDED.metadata,
                    updated_at=EXCLUDED.updated_at
                """,
                entity.id,
                entity.canonical_name,
                entity.entity_type,
                json.dumps(entity.aliases or []),
                json.dumps(entity.metadata or {}),
                entity.created_at,
                entity.updated_at,
            )
        return True

    async def add_entity_alias(self, entity_id: str, alias: str) -> bool:
        entity = await self.find_entity_by_id(entity_id)
        if entity is None:
            return False
        if alias not in entity.aliases:
            entity.aliases.append(alias)
        return await self.save_entity(entity)

    async def save_entity_mention(self, mention) -> bool:
        from bilinc.core.entities import EntityMention
        if not isinstance(mention, EntityMention):
            raise TypeError("mention must be EntityMention")
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO entity_mentions (
                    id, entity_id, memory_key, mention_text, source, confidence, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT(id) DO UPDATE SET
                    entity_id=EXCLUDED.entity_id,
                    memory_key=EXCLUDED.memory_key,
                    mention_text=EXCLUDED.mention_text,
                    source=EXCLUDED.source,
                    confidence=EXCLUDED.confidence
                """,
                mention.id,
                mention.entity_id,
                mention.memory_key,
                mention.mention_text,
                mention.source,
                mention.confidence,
                mention.created_at,
            )
        return True

    async def find_entity_by_id(self, entity_id: str):
        if not self._initialized:
            await self.init()
        row = await self.pool.fetchrow("SELECT * FROM entities WHERE id=$1", entity_id)
        return self._row_to_entity(row) if row else None

    async def find_entity(self, name: str):
        if not self._initialized:
            await self.init()
        normalized = " ".join(str(name).strip().lower().split())
        rows = await self.pool.fetch("SELECT * FROM entities ORDER BY created_at ASC")
        for row in rows:
            entity = self._row_to_entity(row)
            names = [entity.canonical_name, *(entity.aliases or [])]
            if any(" ".join(str(candidate).strip().lower().split()) == normalized for candidate in names):
                return entity
        return None

    async def list_entity_mentions(
        self,
        entity_id: str | None = None,
        memory_key: str | None = None,
        limit: int = 100,
    ):
        if not self._initialized:
            await self.init()
        clauses = []
        params: list[Any] = []
        if entity_id is not None:
            params.append(entity_id)
            clauses.append("entity_id = " + chr(36) + str(len(params)))
        if memory_key is not None:
            params.append(memory_key)
            clauses.append("memory_key = " + chr(36) + str(len(params)))
        params.append(int(limit))
        sql = "SELECT * FROM entity_mentions"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT " + chr(36) + str(len(params))
        rows = await self.pool.fetch(sql, *params)
        return [self._row_to_entity_mention(row) for row in rows]

    async def list_memories_for_entity(self, name: str, limit: int = 100) -> list[str]:
        entity = await self.find_entity(name)
        if entity is None:
            return []
        rows = await self.pool.fetch(
            "SELECT memory_key FROM entity_mentions WHERE entity_id=" + chr(36) + "1 GROUP BY memory_key ORDER BY MAX(created_at) DESC LIMIT " + chr(36) + "2",
            entity.id,
            int(limit),
        )
        return [row["memory_key"] for row in rows]

    async def delete_entity_mentions_for_memory_key(self, memory_key: str) -> int:
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM entity_mentions WHERE memory_key=" + chr(36) + "1",
                memory_key,
            )
        return int(result.split()[-1])

    def _row_to_entity(self, row):
        from bilinc.core.entities import Entity
        if row is None:
            return None
        aliases = row["aliases"]
        metadata = row["metadata"]
        if isinstance(aliases, str):
            aliases = json.loads(aliases or "[]")
        if isinstance(metadata, str):
            metadata = json.loads(metadata or "{}")
        return Entity.from_dict({
            "id": row["id"],
            "canonical_name": row["canonical_name"],
            "entity_type": row["entity_type"],
            "aliases": aliases or [],
            "metadata": metadata or {},
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

    def fts_rebuild(self):
        """PostgreSQL uses a maintained expression index; rebuild is a no-op."""
        return True

    async def fts_search(self, query: str, limit: int = 10):
        if not self._initialized:
            await self.init()
        vector = (
            "to_tsvector('simple', COALESCE(key, '') || ' ' || "
            "COALESCE(value::text, '') || ' ' || COALESCE(metadata::text, ''))"
        )
        sql = (
            "SELECT id, key, ts_rank(" + vector + ", plainto_tsquery('simple', $1)) AS rank "
            "FROM bilinc_entries WHERE " + vector + " @@ plainto_tsquery('simple', $1) "
            "ORDER BY rank LIMIT $2"
        )
        rows = await self.pool.fetch(sql, str(query), int(limit))
        return [(row["id"], row["key"], float(row["rank"])) for row in rows]

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

    async def save_claim(self, claim) -> bool:
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO bilinc_claims (
                    id, memory_key, holder, subject, claim, kind, confidence,
                    valid_at, invalid_at, source, provenance_id, active,
                    superseded_by, metadata, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                          $9, $10, $11, $12, $13, $14, $15, $16)
                ON CONFLICT (id) DO UPDATE SET
                    memory_key = EXCLUDED.memory_key,
                    holder = EXCLUDED.holder,
                    subject = EXCLUDED.subject,
                    claim = EXCLUDED.claim,
                    kind = EXCLUDED.kind,
                    confidence = EXCLUDED.confidence,
                    valid_at = EXCLUDED.valid_at,
                    invalid_at = EXCLUDED.invalid_at,
                    source = EXCLUDED.source,
                    provenance_id = EXCLUDED.provenance_id,
                    active = EXCLUDED.active,
                    superseded_by = EXCLUDED.superseded_by,
                    metadata = EXCLUDED.metadata,
                    updated_at = EXCLUDED.updated_at
            """,
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
                claim.active,
                claim.superseded_by,
                json.dumps(claim.metadata or {}),
                claim.created_at,
                claim.updated_at,
            )
        return True

    async def list_claims(
        self,
        holder: str | None = None,
        subject: str | None = None,
        kind: str | None = None,
        active: bool | None = True,
        limit: int = 100,
    ):
        if not self._initialized:
            await self.init()
        sql = "SELECT * FROM bilinc_claims WHERE 1=1"
        params: list[Any] = []
        if holder is not None:
            params.append(holder)
            sql += f" AND holder = ${len(params)}"
        if subject is not None:
            params.append(subject)
            sql += f" AND subject = ${len(params)}"
        if kind is not None:
            params.append(getattr(kind, "value", str(kind)))
            sql += f" AND kind = ${len(params)}"
        if active is not None:
            params.append(bool(active))
            sql += f" AND active = ${len(params)}"
            if active:
                now = time.time()
                params.append(now)
                sql += f" AND (valid_at IS NULL OR valid_at <= ${len(params)})"
                params.append(now)
                sql += f" AND (invalid_at IS NULL OR invalid_at > ${len(params)})"
        params.append(int(limit))
        sql += f" ORDER BY updated_at DESC LIMIT ${len(params)}"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [self._row_to_claim(row) for row in rows]

    async def list_claims_for_memory_keys(self, memory_keys: list[str], active: bool | None = True, limit: int | None = None):
        if not self._initialized:
            await self.init()
        keys = [str(key) for key in memory_keys if key is not None]
        if not keys:
            return []
        sql = "SELECT * FROM bilinc_claims WHERE memory_key = ANY($1::text[])"
        params: list[Any] = [keys]
        if active is not None:
            params.append(bool(active))
            sql += f" AND active = ${len(params)}"
            if active:
                now = time.time()
                params.append(now)
                sql += f" AND (valid_at IS NULL OR valid_at <= ${len(params)})"
                params.append(now)
                sql += f" AND (invalid_at IS NULL OR invalid_at > ${len(params)})"
        sql += " ORDER BY updated_at DESC"
        if limit is not None:
            params.append(int(limit))
            sql += f" LIMIT ${len(params)}"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [self._row_to_claim(row) for row in rows]

    async def search_claims(self, query: str, limit: int = 10):
        if not self._initialized:
            await self.init()
        needle = f"%{query}%"
        now = time.time()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM bilinc_claims
                WHERE active = true
                  AND (valid_at IS NULL OR valid_at <= $1)
                  AND (invalid_at IS NULL OR invalid_at > $2)
                  AND (claim ILIKE $3 OR subject ILIKE $3 OR holder ILIKE $3)
                ORDER BY updated_at DESC LIMIT $4
                """,
                now,
                now,
                needle,
                int(limit),
            )
        return [self._row_to_claim(row) for row in rows]

    async def supersede_claim(self, old_id: str, new_claim) -> bool:
        await self.save_claim(new_claim)
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE bilinc_claims SET active = false, superseded_by = $1, updated_at = $2 WHERE id = $3",
                new_claim.id,
                time.time(),
                old_id,
            )
        return True

    def _row_to_claim(self, row):
        from bilinc.core.models import Claim

        metadata = row.get("metadata") if hasattr(row, "get") else row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata or "{}")
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
            "metadata": metadata or {},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })

    async def record_eval_candidate(self, row) -> bool:
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO eval_candidates (
                    schema_version, tool_name, query, retrieved_keys, retrieved_scores,
                    memory_types, latency_ms, detail, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                row.schema_version,
                row.tool_name,
                row.query,
                json.dumps(row.retrieved_keys),
                json.dumps(row.retrieved_scores),
                json.dumps(row.memory_types),
                row.latency_ms,
                json.dumps(row.detail),
                row.created_at,
            )
        return True

    async def list_eval_candidates(self, since: float | None = None, limit: int | None = None):
        if not self._initialized:
            await self.init()
        params: list[Any] = []
        sql = "SELECT * FROM eval_candidates"
        if since is not None:
            params.append(float(since))
            sql += f" WHERE created_at >= ${len(params)}"
        sql += " ORDER BY created_at ASC, id ASC"
        if limit is not None:
            params.append(int(limit))
            sql += f" LIMIT ${len(params)}"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [self._eval_row_to_capture(row) for row in rows]

    def _eval_row_to_capture(self, row):
        from bilinc.eval.capture import EvalCaptureRow

        def as_list(value):
            if isinstance(value, str):
                return json.loads(value or "[]")
            return list(value or [])

        detail = row["detail"]
        if isinstance(detail, str):
            detail = json.loads(detail or "{}")
        return EvalCaptureRow(
            schema_version=int(row["schema_version"]),
            tool_name=row["tool_name"],
            query=row["query"],
            retrieved_keys=[str(value) for value in as_list(row["retrieved_keys"])],
            retrieved_scores=[float(value) for value in as_list(row["retrieved_scores"])],
            memory_types=[str(value) for value in as_list(row["memory_types"])],
            latency_ms=int(row["latency_ms"]),
            created_at=float(row["created_at"]),
            detail=dict(detail or {}),
        )

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
            async with conn.transaction():
                await conn.execute("DELETE FROM bilinc_claims WHERE memory_key = $1", key)
                result = await conn.execute("DELETE FROM bilinc_entries WHERE key = $1", key)
            return result == "DELETE 1"

    async def delete_claims_for_memory_key(self, memory_key: str) -> int:
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM bilinc_claims WHERE memory_key = $1", memory_key)
        return int(result.split()[-1])

    async def deactivate_claims_for_memory_key(self, memory_key: str, keep_ids: list[str] | None = None) -> int:
        if not self._initialized:
            await self.init()
        keep_ids = keep_ids or []
        async with self.pool.acquire() as conn:
            if keep_ids:
                result = await conn.execute(
                    """
                    UPDATE bilinc_claims
                    SET active = false, updated_at = $1
                    WHERE memory_key = $2 AND NOT (id = ANY($3::text[]))
                    """,
                    time.time(),
                    memory_key,
                    keep_ids,
                )
            else:
                result = await conn.execute(
                    "UPDATE bilinc_claims SET active = false, updated_at = $1 WHERE memory_key = $2",
                    time.time(),
                    memory_key,
                )
        return int(result.split()[-1])

    async def list_all(self) -> List[MemoryEntry]:
        if not self._initialized:
            await self.init()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM bilinc_entries ORDER BY importance DESC, created_at DESC")
            return [self._row_to_entry(r) for r in rows]
    @staticmethod
    def _page_filters(
        prefix: Optional[str],
        memory_type: Optional[str],
        updated_after: Optional[float],
        updated_before: Optional[float],
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        def bind(value: Any) -> str:
            params.append(value)
            return f"${len(params)}"

        if prefix:
            # left() instead of LIKE: no wildcard escaping, `_`/`%` stay literal.
            clauses.append(f"left(key, {bind(len(prefix))}) = {bind(prefix)}")
        if memory_type:
            clauses.append(f"memory_type = {bind(memory_type)}")
        if updated_after is not None:
            clauses.append(f"updated_at > {bind(float(updated_after))}")
        if updated_before is not None:
            clauses.append(f"updated_at < {bind(float(updated_before))}")
        return clauses, params

    async def list_page(
        self,
        *,
        prefix: Optional[str] = None,
        memory_type: Optional[str] = None,
        updated_after: Optional[float] = None,
        updated_before: Optional[float] = None,
        after_key: Optional[str] = None,
        limit: int = 50,
    ) -> List[MemoryEntry]:
        """Return one key-ordered page of entries (see SQLiteBackend.list_page)."""
        if not self._initialized:
            await self.init()
        clauses, params = self._page_filters(prefix, memory_type, updated_after, updated_before)
        # COLLATE "C" (byte order) on both the cursor comparison and ORDER BY,
        # so paging agrees with SQLite regardless of the database's locale.
        if after_key is not None:
            params.append(after_key)
            clauses.append(f'key COLLATE "C" > ${len(params)}')
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        sql = (
            f"SELECT * FROM bilinc_entries {where} "
            f'ORDER BY key COLLATE "C" ASC LIMIT ${len(params)}'
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [self._row_to_entry(r) for r in rows]

    async def count_filtered(
        self,
        *,
        prefix: Optional[str] = None,
        memory_type: Optional[str] = None,
        updated_after: Optional[float] = None,
        updated_before: Optional[float] = None,
    ) -> int:
        if not self._initialized:
            await self.init()
        clauses, params = self._page_filters(prefix, memory_type, updated_after, updated_before)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self.pool.acquire() as conn:
            return int(await conn.fetchval(f"SELECT COUNT(*) FROM bilinc_entries {where}", *params))

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
    @staticmethod
    def _decode_value(raw):
        """Decode stored JSON values, accepting legacy raw text rows as strings."""
        if raw is None:
            return None
        import json
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def _row_to_entry(self, row) -> MemoryEntry:
        """Convert database row to MemoryEntry."""
        import json
        value = self._decode_value(row["value"])
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
