"""Async PostgreSQL audit trail compatible with the SQLite AuditTrail hash chain."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Optional

try:
    import asyncpg
except ImportError:
    asyncpg = None

from bilinc.core.audit import AuditEntry, OpType


class PostgresAuditTrail:
    """Staging/opt-in PostgreSQL implementation of Bilinc's audit hash chain."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool = None
        self._root_hash = "0" * 64

    async def init(self) -> None:
        if asyncpg is None:
            raise ImportError("asyncpg is required for PostgresAuditTrail")
        self.pool = await asyncpg.create_pool(dsn=self.dsn, min_size=1, max_size=5)
        async with self.pool.acquire() as conn:
            await conn.execute(
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
            row = await conn.fetchrow(
                "SELECT root_hash FROM audit_log ORDER BY id DESC LIMIT 1"
            )
            self._root_hash = row["root_hash"] if row else "0" * 64

    async def log(
        self,
        op_type: OpType,
        key: str,
        before_value: Any = None,
        after_value: Any = None,
        metadata: Optional[Dict] = None,
    ) -> AuditEntry:
        if self.pool is None:
            raise RuntimeError("PostgresAuditTrail not initialized")
        timestamp = time.time()
        before_json = json.dumps(before_value) if before_value is not None else None
        after_json = json.dumps(after_value) if after_value is not None else None
        meta_json = json.dumps(metadata or {})
        op_value = op_type.value if hasattr(op_type, "value") else str(op_type)
        data_str = f"{op_value}:{key}:{timestamp}:{before_json}:{after_json}"
        data_hash = hashlib.sha256(data_str.encode()).hexdigest()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT root_hash FROM audit_log ORDER BY id DESC LIMIT 1"
                )
                prev_root = row["root_hash"] if row else "0" * 64
                new_root = hashlib.sha256(
                    f"{prev_root}:{data_hash}".encode()
                ).hexdigest()
                inserted = await conn.fetchrow(
                    """
                    INSERT INTO audit_log (
                        timestamp, op_type, key, before_value, after_value,
                        data_hash, prev_root, root_hash, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING id
                    """,
                    timestamp, op_value, key, before_json, after_json,
                    data_hash, prev_root, new_root, meta_json,
                )
        self._root_hash = new_root
        return AuditEntry(
            id=inserted["id"],
            timestamp=timestamp,
            op_type=op_value,
            key=key,
            before_value=before_json,
            after_value=after_json,
            data_hash=data_hash,
            prev_root=prev_root,
            root_hash=new_root,
            metadata=meta_json,
        )

    async def verify_integrity(self) -> Dict[str, Any]:
        if self.pool is None:
            raise RuntimeError("PostgresAuditTrail not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM audit_log ORDER BY id ASC")
        if not rows:
            return {"valid": True, "entries": 0, "message": "Empty audit log"}
        current_root = "0" * 64
        first_error = None
        for row in rows:
            data_str = (
                f"{row['op_type']}:{row['key']}:{row['timestamp']}:"
                f"{row['before_value']}:{row['after_value']}"
            )
            expected_data_hash = hashlib.sha256(data_str.encode()).hexdigest()
            expected_root = hashlib.sha256(
                f"{current_root}:{expected_data_hash}".encode()
            ).hexdigest()
            if row["data_hash"] != expected_data_hash:
                first_error = f"Data hash mismatch at entry {row['id']}"
                break
            if row["root_hash"] != expected_root:
                first_error = f"Root hash mismatch at entry {row['id']}"
                break
            current_root = expected_root
        last_row = rows[-1]
        root_mismatch = last_row["root_hash"] != current_root
        return {
            "valid": first_error is None and not root_mismatch,
            "entries": len(rows),
            "current_root": current_root,
            "stored_root": last_row["root_hash"],
            "root_mismatch": root_mismatch,
            "first_error": first_error,
        }

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
