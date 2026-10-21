"""
Cryptographic Audit Trail: a linear SHA-256 hash chain (not a Merkle tree).

Every state mutation is logged; each row's root hashes the previous root and
the row's own data hash. Tamper detection via root hash verification.
Operations: CREATE, UPDATE, DELETE, CONSOLIDATE, FORGET, ROLLBACK, SNAPSHOT, PURGE.

A PURGE removes the stored values of one key's rows and appends a receipt
whose hashed ``after_value`` lists every ``{id, data_hash}`` it emptied. The
chain keeps verifying because a purged row's stored data hash is trusted only
when a later receipt names it; emptying a row without a receipt still breaks
verification.
"""
from __future__ import annotations

import hashlib
import json
import time
import sqlite3
import threading
from typing import Any, Dict, List, Optional, NamedTuple
from enum import Enum


class OpType(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    CONSOLIDATE = "consolidate"
    FORGET = "forget"
    ROLLBACK = "rollback"
    SNAPSHOT = "snapshot"
    PURGE = "purge"


class AuditEntry(NamedTuple):
    id: int
    timestamp: float
    op_type: str
    key: str
    before_value: Optional[str]
    after_value: Optional[str]
    data_hash: str
    prev_root: str
    root_hash: str
    metadata: str


def row_data_hash(row: Any) -> str:
    """The data hash a row's stored fields produce."""
    data_str = f"{row['op_type']}:{row['key']}:{row['timestamp']}:{row['before_value']}:{row['after_value']}"
    return hashlib.sha256(data_str.encode()).hexdigest()


def purge_receipt_targets(rows: List[Any]) -> Dict[int, tuple[str, int]]:
    """Map each purged row id to ``(data_hash, receipt id)`` from the PURGE receipts in ``rows``."""
    targets: Dict[int, tuple[str, int]] = {}
    for row in rows:
        if row["op_type"] != OpType.PURGE.value or not row["after_value"]:
            continue
        try:
            receipt = json.loads(row["after_value"])
        except (TypeError, ValueError):
            continue
        for item in receipt.get("purged", []) if isinstance(receipt, dict) else []:
            if isinstance(item, dict) and isinstance(item.get("id"), int) and isinstance(item.get("data_hash"), str):
                targets[item["id"]] = (item["data_hash"], row["id"])
    return targets


def verify_chain(rows: List[Any]) -> Dict[str, Any]:
    """Recompute the chain over ``rows`` (oldest first).

    A row whose values were purged cannot be rehashed; its stored data hash is
    used instead, but only when a later PURGE receipt names that exact
    ``{id, data_hash}``. Anything else is recomputed from the stored fields.
    """
    if not rows:
        return {"valid": True, "entries": 0, "message": "Empty audit log"}
    targets = purge_receipt_targets(rows)
    current_root = "0" * 64  # Genesis
    first_error = None
    purged_rows = 0
    for row in rows:
        expected_data_hash = row_data_hash(row)
        target = targets.get(row["id"])
        if (
            expected_data_hash != row["data_hash"]
            and target is not None
            and target[0] == row["data_hash"]
            and target[1] > row["id"]
            and row["before_value"] is None
            and row["after_value"] is None
        ):
            expected_data_hash = row["data_hash"]
            purged_rows += 1
        expected_root = hashlib.sha256(f"{current_root}:{expected_data_hash}".encode()).hexdigest()
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
        "purged_rows": purged_rows,
    }


class AuditTrail:
    """
    Append-only cryptographic audit log backed by SQLite.
    
    Each entry is chained via SHA-256:
      root_n = SHA256(root_{n-1} + data_hash_n)
    
    Tamper detection: any modification breaks the chain.
    """
    
    def __init__(self, db_path: str = "audit_trail.db"):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._root_hash: str = ""
        self._lock = threading.Lock()
    
    async def init(self) -> None:
        """Initialize audit trail database."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                op_type TEXT NOT NULL,
                key TEXT NOT NULL,
                before_value TEXT,
                after_value TEXT,
                data_hash TEXT NOT NULL,
                prev_root TEXT NOT NULL,
                root_hash TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_key ON audit_log (key)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log (timestamp)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_op ON audit_log (op_type)")
        
        # Load last root hash
        row = self.conn.execute(
            "SELECT root_hash FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self._root_hash = row["root_hash"] if row else "0" * 64  # Genesis hash
        self.conn.commit()
    
    def log(self, op_type: OpType, key: str,
            before_value: Any = None, after_value: Any = None,
            metadata: Optional[Dict] = None) -> AuditEntry:
        """
        Append an immutable audit entry and return it.
        
        Thread-safe: uses a lock to prevent race conditions
        when multiple async tasks call log() concurrently.
        
        Returns the new root hash for verification.
        """
        if self.conn is None:
            raise RuntimeError("AuditTrail not initialized. Call .init() first.")
        
        with self._lock:
            timestamp = time.time()
            before_json = json.dumps(before_value) if before_value is not None else None
            after_json = json.dumps(after_value) if after_value is not None else None
            meta_json = json.dumps(metadata or {})
            op_value = op_type.value if hasattr(op_type, "value") else str(op_type)
            
            # Compute data hash
            data_str = f"{op_value}:{key}:{timestamp}:{before_json}:{after_json}"
            data_hash = hashlib.sha256(data_str.encode()).hexdigest()
            
            try:
                # Cross-process safety: serialize writers and read the latest
                # persisted root inside the same transaction that inserts the
                # next row. A process-local cached root can be stale when
                # multiple MCP stdio processes share one SQLite database.
                self.conn.execute("BEGIN IMMEDIATE")
                row = self.conn.execute(
                    "SELECT root_hash FROM audit_log ORDER BY id DESC LIMIT 1"
                ).fetchone()
                prev_root = row["root_hash"] if row else "0" * 64
                new_root = hashlib.sha256(f"{prev_root}:{data_hash}".encode()).hexdigest()
                
                cursor = self.conn.execute("""
                    INSERT INTO audit_log (timestamp, op_type, key, before_value, after_value,
                                           data_hash, prev_root, root_hash, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (timestamp, op_value, key, before_json, after_json,
                      data_hash, prev_root, new_root, meta_json))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

            self._root_hash = new_root
            
            return AuditEntry(
                id=cursor.lastrowid, timestamp=timestamp,
                op_type=op_value, key=key,
                before_value=before_json, after_value=after_json,
                data_hash=data_hash, prev_root=prev_root,
                root_hash=new_root, metadata=meta_json,
            )
    
    def verify_integrity(self) -> Dict[str, Any]:
        """
        Verify the entire audit chain hasn't been tampered.

        Recomputes root from genesis and compares with stored values; purged
        rows are accepted only through a PURGE receipt (see ``verify_chain``).
        """
        if self.conn is None:
            raise RuntimeError("AuditTrail not initialized")
        rows = self.conn.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall()
        return verify_chain(rows)

    def has_purgeable_rows(self, key: str) -> bool:
        """Whether any row for ``key`` still holds a value a purge would remove."""
        if self.conn is None:
            raise RuntimeError("AuditTrail not initialized")
        row = self.conn.execute(
            "SELECT 1 FROM audit_log WHERE key = ? AND (before_value IS NOT NULL OR after_value IS NOT NULL) "
            "AND op_type != ? LIMIT 1",
            (key, OpType.PURGE.value),
        ).fetchone()
        return row is not None

    def purge_key(self, key: str, metadata: Optional[Dict] = None) -> int:
        """Remove the stored values of every row for ``key``; return how many rows were emptied.

        The receipt is appended first, so the chain verifies at every step: a
        crash between the two leaves values in place under a valid receipt.
        """
        if self.conn is None:
            raise RuntimeError("AuditTrail not initialized")
        rows = self.conn.execute(
            "SELECT id, data_hash, metadata FROM audit_log WHERE key = ? "
            "AND (before_value IS NOT NULL OR after_value IS NOT NULL) AND op_type != ? ORDER BY id",
            (key, OpType.PURGE.value),
        ).fetchall()
        if not rows:
            return 0
        self.log(
            OpType.PURGE,
            key,
            after_value={"purged": [{"id": row["id"], "data_hash": row["data_hash"]} for row in rows]},
            metadata=metadata,
        )
        purged_at = time.time()
        with self._lock:
            for row in rows:
                try:
                    meta = json.loads(row["metadata"] or "{}")
                except (TypeError, ValueError):
                    meta = {}
                meta["purged_at"] = purged_at
                self.conn.execute(
                    "UPDATE audit_log SET before_value = NULL, after_value = NULL, metadata = ? WHERE id = ?",
                    (json.dumps(meta), row["id"]),
                )
            self.conn.commit()
        return len(rows)

    def get_history(self, key: Optional[str] = None, limit: int = 100) -> List[AuditEntry]:
        """Get audit history, optionally filtered by key."""
        if self.conn is None:
            raise RuntimeError("AuditTrail not initialized")
        
        if key:
            rows = self.conn.execute(
                "SELECT * FROM audit_log WHERE key = ? ORDER BY id DESC LIMIT ?",
                (key, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        
        return [AuditEntry(
            id=r["id"], timestamp=r["timestamp"], op_type=r["op_type"],
            key=r["key"], before_value=r["before_value"], after_value=r["after_value"],
            data_hash=r["data_hash"], prev_root=r["prev_root"],
            root_hash=r["root_hash"], metadata=r["metadata"],
        ) for r in rows]
    
    def get_state_at(self, timestamp: float) -> Dict[str, Any]:
        """
        Reconstruct the state as it was at a given timestamp.
        Replay all operations up to that point.
        """
        if self.conn is None:
            raise RuntimeError("AuditTrail not initialized")
        
        rows = self.conn.execute(
            "SELECT * FROM audit_log WHERE timestamp <= ? ORDER BY id ASC",
            (timestamp,)
        ).fetchall()
        
        state = {}
        for r in rows:
            if r["op_type"] in (
                OpType.CREATE.value,
                OpType.UPDATE.value,
                OpType.CONSOLIDATE.value,
            ):
                state[r["key"]] = json.loads(r["after_value"]) if r["after_value"] else None
            elif r["op_type"] in (OpType.DELETE.value, OpType.FORGET.value):
                state.pop(r["key"], None)

        return state
    
    def get_root_hash(self) -> str:
        """Get the current root hash."""
        return self._root_hash
    
    async def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
