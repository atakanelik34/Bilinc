"""
Cryptographic Audit Trail — Merkle-chain based immutable operation log.

Every state mutation is logged with SHA-256 hash chain.
Operations: CREATE, UPDATE, DELETE, CONSOLIDATE, FORGET
Tamper detection via root hash verification.
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
            
            # Compute data hash
            data_str = f"{op_type.value}:{key}:{timestamp}:{before_json}:{after_json}"
            data_hash = hashlib.sha256(data_str.encode()).hexdigest()
            
            # Chain with previous root
            prev_root = self._root_hash
            new_root = hashlib.sha256(f"{prev_root}:{data_hash}".encode()).hexdigest()
            
            cursor = self.conn.execute("""
                INSERT INTO audit_log (timestamp, op_type, key, before_value, after_value,
                                       data_hash, prev_root, root_hash, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (timestamp, op_type.value, key, before_json, after_json,
                  data_hash, prev_root, new_root, meta_json))
            self.conn.commit()

            self._root_hash = new_root
            
            return AuditEntry(
                id=cursor.lastrowid, timestamp=timestamp,
                op_type=op_type.value, key=key,
                before_value=before_json, after_value=after_json,
                data_hash=data_hash, prev_root=prev_root,
                root_hash=new_root, metadata=meta_json,
            )
    
    def verify_integrity(self) -> Dict[str, Any]:
        """
        Verify the entire audit chain hasn't been tampered.
        
        Recomputes root from genesis and compares with stored values.
        Returns verification result with details.
        """
        if self.conn is None:
            raise RuntimeError("AuditTrail not initialized")
        
        rows = self.conn.execute(
            "SELECT * FROM audit_log ORDER BY id ASC"
        ).fetchall()
        
        if not rows:
            return {"valid": True, "entries": 0, "message": "Empty audit log"}
        
        current_root = "0" * 64  # Genesis
        first_error = None
        total_entries = len(rows)
        
        for row in rows:
            # Recompute data hash
            data_str = f"{row['op_type']}:{row['key']}:{row['timestamp']}:{row['before_value']}:{row['after_value']}"
            expected_data_hash = hashlib.sha256(data_str.encode()).hexdigest()
            
            # Recompute root
            expected_root = hashlib.sha256(f"{current_root}:{expected_data_hash}".encode()).hexdigest()
            
            # Verify chain
            if row['data_hash'] != expected_data_hash:
                first_error = f"Data hash mismatch at entry {row['id']}"
                break
            
            if row['root_hash'] != expected_root:
                first_error = f"Root hash mismatch at entry {row['id']}"
                break
            
            current_root = expected_root
        
        # Final root should match stored root
        last_row = rows[-1]
        root_mismatch = last_row["root_hash"] != current_root
        
        return {
            "valid": first_error is None and not root_mismatch,
            "entries": total_entries,
            "current_root": current_root,
            "stored_root": last_row["root_hash"],
            "root_mismatch": root_mismatch,
            "first_error": first_error,
        }
    
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
