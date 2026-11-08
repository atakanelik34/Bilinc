"""Synchronous StatePlane-compatible PostgreSQL audit trail for opt-in canaries."""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

try:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    conninfo_to_dict = None
    dict_row = None

from bilinc.core import postgres_chain_lock
from bilinc.core.audit import AuditEntry, OpType, verify_chain
from bilinc.storage.postgres_tenancy import quoted, search_path_setting, validate_schema_name

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: The trail's calls block the event loop, so a connect must give up and a dead peer must be noticed.
_CONNECT_KWARGS = {
    "connect_timeout": 5,
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
}

#: After a failed reconnect, every trail on that DSN fails fast for this long instead of blocking the
#: event loop on another connect.
RECONNECT_COOLDOWN_SECONDS = 5.0
_failed_reconnects: Dict[str, float] = {}   # dsn -> _clock() of its last failed reconnect
_clock = time.monotonic

#: Server-side SQLSTATEs that end or refuse a session: admin shutdown, crash shutdown, cannot connect now,
#: database dropped, idle session timeout, idle-in-transaction session timeout (an InternalError).
_SESSION_ENDING_SQLSTATES = frozenset({"57P01", "57P02", "57P03", "57P04", "57P05", "25P03"})


def is_connection_failure(exc: BaseException) -> bool:
    """Whether ``exc`` is a lost or refused PostgreSQL connection rather than an error in a live session.

    Client-side losses ("the connection is closed", a refused connect) are OperationalErrors without a
    SQLSTATE; class 08 is a connection exception. A lock timeout, cancel, deadlock or full disk is not.
    """
    if psycopg is None or not isinstance(exc, psycopg.Error):
        return False
    sqlstate = exc.sqlstate
    if sqlstate is None:
        return isinstance(exc, psycopg.OperationalError)
    return sqlstate.startswith("08") or sqlstate in _SESSION_ENDING_SQLSTATES


def describe_error(exc: BaseException, dsn: Optional[str] = None) -> str:
    """Type, SQLSTATE and the first line of the message (at most 200 characters) for a log line.

    libpq connect errors name the host, port, user and reason, never the password; should one ever echo
    ``dsn``, the DSN and its password are masked before the line is cut.
    """
    lines = str(exc).strip().splitlines()
    line = lines[0] if lines else ""
    if dsn:
        password = None
        if conninfo_to_dict is not None:
            with contextlib.suppress(Exception):   # best effort: an unparsable DSN is still masked whole
                password = conninfo_to_dict(dsn).get("password")
        for secret in (dsn, password):
            if secret:
                line = line.replace(secret, "***")
    return f"{type(exc).__name__} (sqlstate {getattr(exc, 'sqlstate', None)}): {line[:200]}"


class SyncPostgresAuditTrail:
    """Keep StatePlane's synchronous audit API over PostgreSQL.

    The trail holds one session. When the server ends it (a restart or failover), the call opens a new
    one and retries once; a second failure raises. A call opens at most one session, and after a failed
    reconnect the DSN cools down (``RECONNECT_COOLDOWN_SECONDS``). A live session that fails (a lock or
    statement timeout) is not retried.
    """

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
            with psycopg.connect(self.dsn, autocommit=True, **_CONNECT_KWARGS) as bootstrap:
                bootstrap.execute(f"CREATE SCHEMA IF NOT EXISTS {quoted(self.schema)}")
        self.conn = self._connect()
        with self.conn.cursor() as cur:
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

    def _connect(self):
        """Open the trail's session; every (re)connect checks that the tenant schema is the active one.

        A session in any other schema would read and extend another tenant's chain, so it is closed and
        refused. autocommit: a read never leaves an implicit transaction open, so each
        ``with conn.transaction()`` in log() is a real, committed transaction rather than a savepoint
        inside one that is never committed.
        """
        options = {"options": f"-c search_path={search_path_setting(self.schema)}"} if self.schema else {}
        conn = psycopg.connect(self.dsn, row_factory=dict_row, autocommit=True, **_CONNECT_KWARGS, **options)
        try:
            if self.schema:
                row = conn.execute("SELECT current_schema() AS schema").fetchone()
                if (row or {}).get("schema") != self.schema:
                    raise RuntimeError("tenant_schema_not_active")
        except BaseException:
            conn.close()
            raise
        return conn

    def _session(self):
        """The open session, and whether this call had to open it. ``close()`` is final."""
        if self.conn is None:
            raise RuntimeError("SyncPostgresAuditTrail not initialized")
        if self.conn.closed:
            return self._reconnect(), True
        return self.conn, False

    def _reconnect(self):
        failed_at = _failed_reconnects.get(self.dsn)
        if failed_at is not None and _clock() - failed_at < RECONNECT_COOLDOWN_SECONDS:
            raise psycopg.OperationalError("audit store reconnect is cooling down after a failed attempt")
        try:
            conn = self._connect()
        except psycopg.OperationalError as exc:
            _failed_reconnects[self.dsn] = _clock()
            logger.warning("Audit trail reconnect failed: %s", describe_error(exc, self.dsn))
            raise
        _failed_reconnects.pop(self.dsn, None)
        # Replaced only on success: if the server is still down the dead session stays, and the next
        # call tries again instead of reading as "not initialized".
        lost, self.conn = self.conn, conn
        if lost is not None:
            # psycopg's close() returns early for a connection that is already BAD, so finish the
            # libpq handle directly instead of waiting for garbage collection. Best effort.
            with contextlib.suppress(Exception):
                lost.close()
                lost.pgconn.finish()
        return conn

    def _run(self, operation: Callable[[Any], _T], retry: Optional[Callable[[Any], _T]] = None) -> _T:
        """Run ``operation(conn)``; if the server ended the session, run ``retry`` (default: the same) once on a new one.

        A live session's error (``conn.closed`` is False: a lock or statement timeout) is not retried,
        and neither is a session this call has just opened, so a call connects at most once.
        """
        conn, opened_now = self._session()
        try:
            return operation(conn)
        except psycopg.OperationalError as exc:
            if opened_now or not conn.closed:
                raise
            logger.warning("Audit trail session lost (%s); reconnecting once", type(exc).__name__)
        return (retry or operation)(self._reconnect())

    def _fetch(self, sql: str, params: tuple = (), *, one: bool = False):
        def query(conn):
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone() if one else cur.fetchall()

        return self._run(query)

    def log(
        self,
        op_type: OpType,
        key: str,
        before_value: Any = None,
        after_value: Any = None,
        metadata: Optional[Dict] = None,
    ) -> AuditEntry:
        # Computed once: a retry must write the very row the first attempt wrote, so its lookup can
        # recognize a first COMMIT that landed with only its ack lost.
        timestamp = time.time()
        before_json = json.dumps(before_value) if before_value is not None else None
        after_json = json.dumps(after_value) if after_value is not None else None
        meta_json = json.dumps(metadata or {})
        op_value = op_type.value if hasattr(op_type, "value") else str(op_type)
        data_hash = hashlib.sha256(
            f"{op_value}:{key}:{timestamp}:{before_json}:{after_json}".encode()
        ).hexdigest()
        row = (timestamp, op_value, key, before_json, after_json, data_hash, meta_json)
        entry, head = self._run(
            lambda conn: self._insert_entry(conn, *row),
            retry=lambda conn: self._insert_entry(conn, *row, find_landed=True),
        )
        self._root_hash = head
        return entry

    def _insert_entry(
        self,
        conn,
        timestamp: float,
        op_value: str,
        key: str,
        before_json: Optional[str],
        after_json: Optional[str],
        data_hash: str,
        meta_json: str,
        *,
        find_landed: bool = False,
    ) -> Tuple[AuditEntry, str]:
        """Append one row in one transaction; return it and the chain head when the transaction ended.

        With ``find_landed`` the row is first looked up and, if it is already there, returned with the
        current head (another writer may have appended after it) instead of being inserted again.
        """
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(postgres_chain_lock.lock_timeout_sql())
                cur.execute(postgres_chain_lock.lock_sql("audit_log"))
                if find_landed:
                    # Under the chain lock, so a still-running earlier attempt has committed or
                    # rolled back by now. The data_hash covers the key, the time and both values.
                    cur.execute(
                        "SELECT id, prev_root, root_hash FROM audit_log WHERE key = %s AND data_hash = %s "
                        "ORDER BY id DESC LIMIT 1",
                        (key, data_hash),
                    )
                    landed = cur.fetchone()
                    if landed is not None:
                        cur.execute("SELECT root_hash FROM audit_log ORDER BY id DESC LIMIT 1")
                        head = cur.fetchone()["root_hash"]
                        return AuditEntry(
                            id=landed["id"], timestamp=timestamp, op_type=op_value, key=key,
                            before_value=before_json, after_value=after_json,
                            data_hash=data_hash, prev_root=landed["prev_root"],
                            root_hash=landed["root_hash"], metadata=meta_json,
                        ), head
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
        return AuditEntry(
            id=entry_id, timestamp=timestamp, op_type=op_value, key=key,
            before_value=before_json, after_value=after_json,
            data_hash=data_hash, prev_root=prev_root, root_hash=new_root,
            metadata=meta_json,
        ), new_root

    def verify_integrity(self) -> Dict[str, Any]:
        return verify_chain(self._fetch("SELECT * FROM audit_log ORDER BY id ASC"))

    def has_purgeable_rows(self, key: str) -> bool:
        """Whether any row for ``key`` still holds a value a purge would remove."""
        row = self._fetch(
            "SELECT 1 FROM audit_log WHERE key = %s AND (before_value IS NOT NULL OR after_value IS NOT NULL) "
            "AND op_type <> %s LIMIT 1",
            (key, OpType.PURGE.value),
            one=True,
        )
        return row is not None

    def purge_key(self, key: str, metadata: Optional[Dict] = None) -> int:
        """Remove the stored values of every row for ``key`` behind a PURGE receipt (see audit.verify_chain)."""
        rows = self._fetch(
            "SELECT id, data_hash FROM audit_log WHERE key = %s "
            "AND (before_value IS NOT NULL OR after_value IS NOT NULL) AND op_type <> %s ORDER BY id",
            (key, OpType.PURGE.value),
        )
        if not rows:
            return 0
        self.log(
            OpType.PURGE,
            key,
            after_value={"purged": [{"id": row["id"], "data_hash": row["data_hash"]} for row in rows]},
            metadata=metadata,
        )
        purged_at = time.time()
        ids = [row["id"] for row in rows]

        def clear_values(conn):  # idempotent, so a retry after a lost ack is harmless
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE audit_log SET before_value = NULL, after_value = NULL, "
                        "metadata = metadata || jsonb_build_object('purged_at', %s::double precision) "
                        "WHERE id = ANY(%s)",
                        (purged_at, ids),
                    )

        self._run(clear_values)
        return len(rows)

    def get_history(self, key: Optional[str] = None, limit: int = 100):
        if key:
            rows = self._fetch("SELECT * FROM audit_log WHERE key=%s ORDER BY id DESC LIMIT %s", (key, limit))
        else:
            rows = self._fetch("SELECT * FROM audit_log ORDER BY id DESC LIMIT %s", (limit,))
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
        rows = self._fetch("SELECT * FROM audit_log WHERE timestamp <= %s ORDER BY id ASC", (timestamp,))
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

    def refresh_root_hash(self) -> str:
        """Read the head of the chain from the store and make it the cached value (see ``AuditTrail``).

        A failed read raises; the cached value is never returned instead.
        """
        row = self._fetch("SELECT root_hash FROM audit_log ORDER BY id DESC LIMIT 1", one=True)
        self._root_hash = row["root_hash"] if row else "0" * 64
        return self._root_hash

    async def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None
