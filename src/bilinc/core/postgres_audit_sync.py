"""Synchronous StatePlane-compatible PostgreSQL audit trail for opt-in canaries."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Optional

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None

from bilinc.core.audit import AuditEntry, OpType
from bilinc.storage.postgres_tenancy import quoted, search_path_setting, validate_schema_name


class SyncPostgresAuditTrail:
    """Keep StatePlane's synchronous audit API over PostgreSQL."""

    def __init__(self, dsn: str, schema: Optional[str] = None):
        self.dsn = dsn
        # Same tenant schema as the backend, so each project keeps its own chain.
        self.schema = validate_schema_name(schema) if schema is not None else None
        self.conn = None
        self._root_hash = "0" * 64

    async def init(self) -> None:
        if psycopg is None:
            raise ImportError("psycopg is required for SyncPostgresAuditTrail")
        if self.schema:
            with psycopg.connect(self.dsn, autocommit=True) as bootstrap:
                bootstrap.execute(f"CREATE SCHEMA IF NOT EXISTS {quoted(self.schema)}")
            self.conn = psycopg.connect(
                self.dsn,
                row_factory=dict_row,
                autocommit=True,
                options=f"-c search_path={search_path_setting(self.schema)}",
            )
        else:
            self.conn = psycopg.connect(self.dsn, row_factory=dict_row, autocommit=True)
        # autocommit: a read never leaves an implicit transaction open, so each
        # `with conn.transaction()` in log() is a real, committed transaction
        # rather than a savepoint inside one that is never committed.
        with self.conn.cursor() as cur:
            if self.schema:
                cur.execute("SELECT current_schema() AS schema")
                if (cur.fetchone() or {}).get("schema") != self.schema:
                    raise RuntimeError("tenant_schema_not_active")
            cur.execute(
                """
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
                """
            )
            cur.execute("SELECT root_hash FROM audit_log ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            self._root_hash = row["root_hash"] if row else "0" * 64
        self.conn.commit()

    def log(
        self,
        op_type: OpType,
        key: str,
        before_value: Any = None,
        after_value: Any = None,
        metadata: Optional[Dict] = None,
    ) -> AuditEntry:
        if self.conn is None:
            raise RuntimeError("SyncPostgresAuditTrail not initialized")
        timestamp = time.time()
        before_json = json.dumps(before_value) if before_value is not None else None
        after_json = json.dumps(after_value) if after_value is not None else None
        meta_json = json.dumps(metadata or {})
        op_value = op_type.value if hasattr(op_type, "value") else str(op_type)
        data_hash = hashlib.sha256(
            f"{op_value}:{key}:{timestamp}:{before_json}:{after_json}".encode()
        ).hexdigest()
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute("SELECT root_hash FROM audit_log ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                prev_root = row["root_hash"] if row else "0" * 64
                new_root = hashlib.sha256(
                    f"{prev_root}:{data_hash}".encode()
                ).hexdigest()
                cur.execute(
                    """
                    INSERT INTO audit_log (
                        timestamp, op_type, key, before_value, after_value,
                        data_hash, prev_root, root_hash, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        timestamp, op_value, key, before_json, after_json,
                        data_hash, prev_root, new_root, meta_json,
                    ),
                )
                entry_id = cur.fetchone()["id"]
        self._root_hash = new_root
        return AuditEntry(
            id=entry_id, timestamp=timestamp, op_type=op_value, key=key,
            before_value=before_json, after_value=after_json,
            data_hash=data_hash, prev_root=prev_root, root_hash=new_root,
            metadata=meta_json,
        )

    def verify_integrity(self) -> Dict[str, Any]:
        if self.conn is None:
            raise RuntimeError("SyncPostgresAuditTrail not initialized")
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM audit_log ORDER BY id ASC")
            rows = cur.fetchall()
        if not rows:
            return {"valid": True, "entries": 0, "message": "Empty audit log"}
        current_root = "0" * 64
        first_error = None
        for row in rows:
            data_hash = hashlib.sha256(
                f"{row['op_type']}:{row['key']}:{row['timestamp']}:"
                f"{row['before_value']}:{row['after_value']}".encode()
            ).hexdigest()
            expected_root = hashlib.sha256(
                f"{current_root}:{data_hash}".encode()
            ).hexdigest()
            if row["data_hash"] != data_hash:
                first_error = f"Data hash mismatch at entry {row['id']}"
                break
            if row["root_hash"] != expected_root:
                first_error = f"Root hash mismatch at entry {row['id']}"
                break
            current_root = expected_root
        last = rows[-1]
        root_mismatch = last["root_hash"] != current_root
        return {
            "valid": first_error is None and not root_mismatch,
            "entries": len(rows),
            "current_root": current_root,
            "stored_root": last["root_hash"],
            "root_mismatch": root_mismatch,
            "first_error": first_error,
        }

    def get_history(self, key: Optional[str] = None, limit: int = 100):
        if self.conn is None:
            raise RuntimeError("SyncPostgresAuditTrail not initialized")
        with self.conn.cursor() as cur:
            if key:
                cur.execute(
                    "SELECT * FROM audit_log WHERE key=%s ORDER BY id DESC LIMIT %s",
                    (key, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM audit_log ORDER BY id DESC LIMIT %s",
                    (limit,),
                )
            rows = cur.fetchall()
        return [
            AuditEntry(
                id=row["id"], timestamp=row["timestamp"], op_type=row["op_type"],
                key=row["key"], before_value=row["before_value"],
                after_value=row["after_value"], data_hash=row["data_hash"],
                prev_root=row["prev_root"], root_hash=row["root_hash"],
                metadata=row["metadata"],
            )
            for row in rows
        ]

    def get_state_at(self, timestamp: float) -> Dict[str, Any]:
        if self.conn is None:
            raise RuntimeError("SyncPostgresAuditTrail not initialized")
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM audit_log WHERE timestamp <= %s ORDER BY id ASC",
                (timestamp,),
            )
            rows = cur.fetchall()
        state = {}
        for row in rows:
            if row["op_type"] in (
                OpType.CREATE.value, OpType.UPDATE.value, OpType.CONSOLIDATE.value,
            ):
                state[row["key"]] = (
                    json.loads(row["after_value"]) if row["after_value"] else None
                )
            elif row["op_type"] in (OpType.DELETE.value, OpType.FORGET.value):
                state.pop(row["key"], None)
        return state

    def get_root_hash(self) -> str:
        return self._root_hash

    async def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None
