"""P0 2026-11-08: the Postgres audit trail must survive a server restart.

Azure Postgres restarted at 05:46:12Z. ``SyncPostgresAuditTrail`` opens one psycopg connection in
``init()`` and never reconnects, so every audit-touching call on a cached project plane raised
``psycopg.OperationalError: the connection is closed`` and the sidecar answered HTTP 500 (history,
diff against current, commit, confirm), while list/recall kept working off the cached root hash.

The restart is simulated by terminating the trail's own backend from a separate admin connection,
which is what a restart does to every existing session. Every test asserts recovery.

Needs a disposable PostgreSQL with pgvector (BILINC_TEST_POSTGRES_DSN), see test_cloud_postgres_tenancy.py.
"""
from __future__ import annotations

import os
import time
import traceback
import uuid

import pytest
import pytest_asyncio

from bilinc.core.audit import OpType

_DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
needs_postgres = pytest.mark.skipif(not _DSN, reason="BILINC_TEST_POSTGRES_DSN not set")

HEADERS = {"X-Bilinc-Sidecar-Token": "secret"}


# ---- helpers ------------------------------------------------------------------------------------

def _admin():
    import psycopg

    return psycopg.connect(_DSN, autocommit=True)


def _terminate_backend(pid: int, timeout: float = 10.0) -> None:
    """Kill one server session the way a restart does, and wait until it is really gone."""
    with _admin() as admin:
        assert admin.info.backend_pid != pid
        assert admin.execute("SELECT pg_terminate_backend(%s)", (pid,)).fetchone()[0] is True
        deadline = time.monotonic() + timeout
        while admin.execute("SELECT 1 FROM pg_stat_activity WHERE pid = %s", (pid,)).fetchone():
            assert time.monotonic() < deadline, f"backend {pid} still alive after pg_terminate_backend"
            time.sleep(0.05)


def _rows(schema: str, sql: str, *params):
    with _admin() as admin:
        return admin.execute(sql.format(table=f'"{schema}".audit_log'), params).fetchall()


def _head(schema: str) -> str:
    rows = _rows(schema, "SELECT root_hash FROM {table} ORDER BY id DESC LIMIT 1")
    return rows[0][0] if rows else "0" * 64


def _drop_schema(schema: str) -> None:
    with _admin() as admin:
        admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.fixture(autouse=True)
def _own_reconnect_cooldowns(monkeypatch):
    """Every test starts with no failed reconnect on record, and leaves none behind."""
    from bilinc.core import postgres_audit_sync

    monkeypatch.setattr(postgres_audit_sync, "_failed_reconnects", {}, raising=False)


@pytest.fixture
def schema():
    name = "bilinc_p_" + uuid.uuid4().hex
    yield name
    _drop_schema(name)


@pytest_asyncio.fixture
async def trail(schema):
    from bilinc.core.postgres_audit_sync import SyncPostgresAuditTrail

    audit = SyncPostgresAuditTrail(_DSN, schema=schema)
    await audit.init()
    yield audit
    await audit.close()


# ---- trail level --------------------------------------------------------------------------------

@needs_postgres
@pytest.mark.asyncio
async def test_get_history_after_backend_terminated_returns_rows(trail):
    trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    trail.log(OpType.UPDATE, "p0.key", {"n": 1}, {"n": 2})
    before = [entry.root_hash for entry in trail.get_history("p0.key")]
    assert len(before) == 2

    _terminate_backend(trail.conn.info.backend_pid)

    first = trail.get_history("p0.key")             # the first request after the restart
    second = trail.get_history("p0.key")            # and every request after it
    assert [entry.root_hash for entry in first] == before
    assert [entry.root_hash for entry in second] == before


@needs_postgres
@pytest.mark.asyncio
async def test_get_history_after_an_earlier_failed_call_returns_rows(trail):
    """Prod's steady state: an earlier request already hit the dead session; later ones saw "the connection is closed"."""
    trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    before = [entry.root_hash for entry in trail.get_history("p0.key")]

    _terminate_backend(trail.conn.info.backend_pid)

    first_error = None
    try:
        trail.get_history("p0.key")
    except Exception as exc:  # recorded, not asserted here: the next call is the one prod kept failing
        first_error = exc

    assert [entry.root_hash for entry in trail.get_history("p0.key")] == before
    assert first_error is None, f"first call after the restart failed: {first_error!r}"


@needs_postgres
@pytest.mark.asyncio
async def test_refresh_root_hash_after_backend_terminated_returns_the_true_head(trail, schema):
    from bilinc.core.postgres_audit_sync import SyncPostgresAuditTrail

    trail.log(OpType.CREATE, "p0.a", None, {"n": 1})
    stale = trail.get_root_hash()
    _terminate_backend(trail.conn.info.backend_pid)

    # Another worker keeps writing while this one's session is dead, so the cached head is stale
    # and only a read from the store can be right.
    other = SyncPostgresAuditTrail(_DSN, schema=schema)
    await other.init()
    try:
        head = other.log(OpType.CREATE, "p0.b", None, {"n": 2}).root_hash
    finally:
        await other.close()
    assert head != stale and _head(schema) == head

    assert trail.refresh_root_hash() == head
    assert trail.get_root_hash() == head


@needs_postgres
@pytest.mark.asyncio
async def test_log_after_backend_terminated_appends_exactly_one_row(trail, schema):
    trail.log(OpType.CREATE, "p0.a", None, {"n": 1})
    previous_head = _head(schema)
    count_before = _rows(schema, "SELECT COUNT(*) FROM {table}")[0][0]

    _terminate_backend(trail.conn.info.backend_pid)

    entry = trail.log(OpType.CREATE, "p0.after", None, {"n": 2})

    assert _rows(schema, "SELECT COUNT(*) FROM {table}")[0][0] == count_before + 1
    assert _rows(schema, "SELECT COUNT(*) FROM {table} WHERE key = %s", "p0.after")[0][0] == 1
    assert entry.prev_root == previous_head
    assert entry.root_hash == _head(schema) == trail.get_root_hash()
    integrity = trail.verify_integrity()
    assert integrity["valid"] is True, integrity


# ---- service level: the exact prod shape -------------------------------------------------------

class _RecordServerErrors:
    """ASGI wrapper that keeps what the app raised, so a 500 in an assertion message names its cause."""

    def __init__(self, app):
        self.app = app
        self.errors: list[BaseException] = []

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            self.errors.append(exc)
            raise


def _explain(response, recorder) -> str:
    cause = "none"
    if recorder.errors:
        error = recorder.errors[-1]
        frames = [
            f"{os.path.basename(frame.filename)}:{frame.lineno} {frame.name}"
            for frame in traceback.extract_tb(error.__traceback__)
            if f"{os.sep}bilinc{os.sep}" in frame.filename
        ]
        cause = f"{error!r} via {' -> '.join(frames)}"
    return f"{response.status_code} {response.headers.get('content-type')} {response.text[:200]!r}; server raised: {cause}"


@needs_postgres
@pytest.mark.parametrize("operation", ["history", "diff", "diff_after_failed_request", "commit"])
def test_sidecar_recovers_after_postgres_restart(tmp_path, monkeypatch, operation):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from bilinc.cloud.service import create_app
    from bilinc.storage.postgres_tenancy import project_schema

    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("BILINC_POSTGRES_DSN", _DSN)
    for name in ("BILINC_CLOUD_EMBEDDINGS", "BILINC_CLOUD_PLANE_IDLE_SECONDS", "BILINC_CLOUD_PLANE_MAX"):
        monkeypatch.delenv(name, raising=False)   # one cached plane per project, no eviction: as in prod

    project = str(uuid.uuid4())
    app = create_app(runtime_dir=tmp_path, sidecar_token="secret")
    recorder = _RecordServerErrors(app)

    def post(path, body):
        return client.post(f"/v1/projects/{project}/{path}", headers=HEADERS, json=body)

    try:
        with TestClient(recorder, raise_server_exceptions=False) as client:
            response = post("commit", {"key": "p0.alpha", "value": "before the restart"})
            assert response.status_code == 200, _explain(response, recorder)
            response = post("snapshots", {"label": "before"})
            assert response.status_code == 200, _explain(response, recorder)
            snapshot_id = response.json()["snapshot"]["id"]

            plane = app.state.runtime_manager._planes[project]
            _terminate_backend(plane.audit.conn.info.backend_pid)

            if operation == "history":
                response = post("history", {"key": "p0.alpha"})
                assert response.status_code == 200, _explain(response, recorder)
                body = response.json()
                assert body["exists"] is True and body["entries"], body
            elif operation in ("diff", "diff_after_failed_request"):
                if operation == "diff_after_failed_request":
                    # Prod's steady state: earlier requests already hit the dead session (not asserted
                    # here), so the diff below is the call that kept failing with "the connection is closed".
                    post("history", {"key": "p0.alpha"})
                response = post("diff", {"from_snapshot_id": snapshot_id})
                assert response.status_code == 200, _explain(response, recorder)
                assert response.json()["to_root_hash"] == _head(project_schema(project))
            else:
                response = post("commit", {"key": "p0.beta", "value": "after the restart"})
                assert response.status_code == 200, _explain(response, recorder)
                response = post("history", {"key": "p0.beta"})
                assert response.status_code == 200, _explain(response, recorder)
                body = response.json()
                assert body["exists"] is True and len(body["entries"]) >= 1, body
            if operation != "diff_after_failed_request":
                assert recorder.errors == []
    finally:
        _drop_schema(project_schema(project))


# ---- every read, both shapes of the incident ---------------------------------------------------

_READS = {
    "get_history": lambda trail: [entry.root_hash for entry in trail.get_history("p0.key")],
    "refresh_root_hash": lambda trail: trail.refresh_root_hash(),
    "get_state_at": lambda trail: trail.get_state_at(time.time() + 3600),
    "verify_integrity": lambda trail: trail.verify_integrity(),
    "has_purgeable_rows": lambda trail: trail.has_purgeable_rows("p0.key"),
}


def _lose_session(trail) -> None:
    """Terminate the trail's session and let one raw statement find out, so ``conn.closed`` is True."""
    import psycopg

    _terminate_backend(trail.conn.info.backend_pid)
    with pytest.raises(psycopg.OperationalError):
        trail.conn.execute("SELECT 1")
    assert trail.conn.closed


@needs_postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["first_call_after_restart", "after_a_failed_call"])
@pytest.mark.parametrize("read", sorted(_READS))
async def test_every_read_recovers_after_backend_terminated(trail, read, shape):
    trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    trail.log(OpType.UPDATE, "p0.key", {"n": 1}, {"n": 2})
    expected = _READS[read](trail)
    old_pid = trail.conn.info.backend_pid

    if shape == "first_call_after_restart":
        _terminate_backend(old_pid)                 # the client does not know yet: conn.closed is False
        assert not trail.conn.closed
    else:
        _lose_session(trail)

    assert _READS[read](trail) == expected
    assert _READS[read](trail) == expected          # and every call after it
    assert not trail.conn.closed and trail.conn.info.backend_pid != old_pid


@needs_postgres
@pytest.mark.asyncio
async def test_a_read_that_fails_again_after_the_reconnect_raises_and_keeps_the_cached_head(trail, monkeypatch):
    """One reconnect and one retry, then the error propagates; the cached head is never served instead."""
    import psycopg

    trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    cached = trail.get_root_hash()
    real_connect = trail._connect
    connects = []

    def connect_into_a_dying_session():
        conn = real_connect()
        connects.append(conn.info.backend_pid)
        _terminate_backend(conn.info.backend_pid)
        return conn

    monkeypatch.setattr(trail, "_connect", connect_into_a_dying_session)
    _terminate_backend(trail.conn.info.backend_pid)

    with pytest.raises(psycopg.OperationalError):
        trail.refresh_root_hash()
    assert len(connects) == 1                       # exactly one reconnect, exactly one retry
    assert trail.get_root_hash() == cached


@needs_postgres
@pytest.mark.asyncio
async def test_a_reconnect_that_fails_raises_and_the_next_call_reconnects(trail):
    import psycopg

    trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    expected = _READS["get_history"](trail)
    dsn = trail.dsn
    _lose_session(trail)

    trail.dsn = "postgresql://127.0.0.1:1/x"        # the server is still down
    with pytest.raises(psycopg.OperationalError):
        trail.get_history("p0.key")
    trail.dsn = dsn                                 # the server is back
    assert _READS["get_history"](trail) == expected


@needs_postgres
@pytest.mark.asyncio
async def test_a_closed_trail_does_not_reconnect(trail):
    await trail.close()
    with pytest.raises(RuntimeError, match="not initialized"):
        trail.get_history("p0.key")
    with pytest.raises(RuntimeError, match="not initialized"):
        trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    assert trail.conn is None


# ---- log: a COMMIT that landed but whose ack was lost ------------------------------------------

@needs_postgres
@pytest.mark.asyncio
async def test_log_after_a_lost_commit_ack_returns_the_landed_row_without_a_duplicate(trail, schema, monkeypatch):
    trail.log(OpType.CREATE, "p0.a", None, {"n": 1})
    count_before = _rows(schema, "SELECT COUNT(*) FROM {table}")[0][0]
    real_insert = trail._insert_entry
    attempts = []

    def commit_then_lose_the_ack(*args, **kwargs):
        attempts.append(kwargs)
        entry = real_insert(*args, **kwargs)        # the COMMIT reaches the server
        if len(attempts) == 1:
            _terminate_backend(trail.conn.info.backend_pid)
            trail.conn.execute("SELECT 1")          # ...and the client only sees its session die
        return entry

    monkeypatch.setattr(trail, "_insert_entry", commit_then_lose_the_ack)

    entry = trail.log(OpType.CREATE, "p0.lost_ack", None, {"n": 2})

    assert len(attempts) == 2
    landed = _rows(schema, "SELECT id, data_hash, prev_root, root_hash FROM {table} WHERE key = %s", "p0.lost_ack")
    assert len(landed) == 1                          # no second insert
    assert _rows(schema, "SELECT COUNT(*) FROM {table}")[0][0] == count_before + 1
    assert (entry.id, entry.data_hash, entry.prev_root, entry.root_hash) == landed[0]
    assert entry.root_hash == _head(schema) == trail.get_root_hash()
    integrity = trail.verify_integrity()
    assert integrity["valid"] is True, integrity

    # The landed row is found by its data_hash, not by key alone: the next write still appends.
    follow_up = trail.log(OpType.UPDATE, "p0.lost_ack", {"n": 2}, {"n": 3})
    assert follow_up.prev_root == entry.root_hash
    assert trail.verify_integrity()["valid"] is True


@needs_postgres
@pytest.mark.asyncio
async def test_log_whose_first_attempt_never_committed_inserts_once_on_the_current_head(trail, schema):
    """The insert retry re-reads the head in its new transaction, so a write by another worker in between is kept."""
    from bilinc.core.postgres_audit_sync import SyncPostgresAuditTrail

    trail.log(OpType.CREATE, "p0.a", None, {"n": 1})
    _lose_session(trail)
    other = SyncPostgresAuditTrail(_DSN, schema=schema)
    await other.init()
    try:
        head = other.log(OpType.CREATE, "p0.b", None, {"n": 2}).root_hash
    finally:
        await other.close()

    entry = trail.log(OpType.CREATE, "p0.c", None, {"n": 3})

    assert entry.prev_root == head
    assert _rows(schema, "SELECT COUNT(*) FROM {table} WHERE key = %s", "p0.c")[0][0] == 1
    assert trail.verify_integrity()["valid"] is True


@needs_postgres
@pytest.mark.asyncio
async def test_purge_key_after_backend_terminated(trail):
    trail.log(OpType.CREATE, "p0.key", None, {"secret": 1})
    trail.log(OpType.UPDATE, "p0.key", {"secret": 1}, {"secret": 2})
    _terminate_backend(trail.conn.info.backend_pid)

    assert trail.purge_key("p0.key", metadata={"reason": "p0"}) == 2
    assert trail.has_purgeable_rows("p0.key") is False
    integrity = trail.verify_integrity()
    assert integrity["valid"] is True, integrity


# ---- a reconnect must land in the trail's own tenant schema ------------------------------------

@needs_postgres
@pytest.mark.asyncio
async def test_a_reconnect_lands_in_the_trail_schema(trail, schema):
    trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    _terminate_backend(trail.conn.info.backend_pid)

    trail.get_history("p0.key")

    assert trail.conn.execute("SELECT current_schema() AS schema").fetchone()["schema"] == schema


@needs_postgres
@pytest.mark.asyncio
async def test_a_reconnect_into_another_tenant_schema_is_refused(trail, schema, monkeypatch):
    import psycopg

    from bilinc.core import postgres_audit_sync
    from bilinc.core.postgres_audit_sync import SyncPostgresAuditTrail

    other_schema = "bilinc_p_" + uuid.uuid4().hex
    other = SyncPostgresAuditTrail(_DSN, schema=other_schema)
    await other.init()
    try:
        other.log(OpType.CREATE, "other.key", None, {"n": 1})
        other_rows = _rows(other_schema, "SELECT COUNT(*) FROM {table}")[0][0]
        trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
        real_setting = postgres_audit_sync.search_path_setting
        wrong = [True]
        monkeypatch.setattr(
            postgres_audit_sync, "search_path_setting",
            lambda name: real_setting(other_schema if wrong[0] else name),
        )
        now = [1000.0]
        monkeypatch.setattr(postgres_audit_sync, "_clock", lambda: now[0])
        _terminate_backend(trail.conn.info.backend_pid)

        with pytest.raises(RuntimeError, match="tenant_schema_not_active"):
            trail.log(OpType.CREATE, "p0.key", None, {"n": 2})
        assert trail.conn.closed                    # the wrong-schema session was never kept
        with pytest.raises(psycopg.OperationalError):
            trail.get_history("p0.key")             # inside the cooldown that failure started
        now[0] += 5.1
        with pytest.raises(RuntimeError, match="tenant_schema_not_active"):
            trail.get_history("p0.key")
        assert _rows(other_schema, "SELECT COUNT(*) FROM {table}")[0][0] == other_rows

        wrong[0] = False
        now[0] += 5.1
        assert [entry.key for entry in trail.get_history()] == ["p0.key"]
    finally:
        await other.close()
        _drop_schema(other_schema)


# ---- service: a store that stays down is a 503 with a stable code ------------------------------

@needs_postgres
@pytest.mark.parametrize("operation", ["history", "diff", "commit"])
def test_sidecar_answers_503_while_the_audit_store_stays_down(tmp_path, monkeypatch, operation):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from bilinc.cloud.service import create_app
    from bilinc.storage.postgres_tenancy import project_schema

    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("BILINC_POSTGRES_DSN", _DSN)
    for name in ("BILINC_CLOUD_EMBEDDINGS", "BILINC_CLOUD_PLANE_IDLE_SECONDS", "BILINC_CLOUD_PLANE_MAX"):
        monkeypatch.delenv(name, raising=False)

    project = str(uuid.uuid4())
    app = create_app(runtime_dir=tmp_path, sidecar_token="secret")

    def post(path, body):
        return client.post(f"/v1/projects/{project}/{path}", headers=HEADERS, json=body)

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            assert post("commit", {"key": "p0.alpha", "value": "before"}).status_code == 200
            response = post("snapshots", {"label": "before"})
            assert response.status_code == 200
            path, body = {
                "history": ("history", {"key": "p0.alpha"}),
                "diff": ("diff", {"from_snapshot_id": response.json()["snapshot"]["id"]}),
                "commit": ("commit", {"key": "p0.beta", "value": "while the store is down"}),
            }[operation]

            plane = app.state.runtime_manager._planes[project]
            dsn = plane.audit.dsn
            _terminate_backend(plane.audit.conn.info.backend_pid)
            plane.audit.dsn = "postgresql://127.0.0.1:1/x"   # the reconnect fails too

            response = post(path, body)
            assert response.status_code == 503, response.text
            assert response.headers["content-type"].startswith("application/json")
            assert response.json() == {"detail": "audit_store_unavailable"}

            plane.audit.dsn = dsn                            # the store is back: the same plane recovers
            response = post("history", {"key": "p0.alpha"})
            assert response.status_code == 200, response.text
    finally:
        _drop_schema(project_schema(project))


# ---- reconnect storms: one connect per call, a shared cooldown after a failed one ---------------

class _Psycopg:
    """Stands in for the psycopg module inside the trail only: counts connects and can refuse them."""

    def __init__(self):
        import psycopg

        self._real = psycopg
        self.Error = psycopg.Error
        self.OperationalError = psycopg.OperationalError
        self.down = True
        self.error = "connection refused (simulated)"
        self.connects = []
        self.kwargs = []

    def connect(self, dsn, **kwargs):
        self.connects.append(dsn)
        self.kwargs.append(kwargs)
        if self.down:
            raise self.OperationalError(self.error)
        return self._real.connect(dsn, **kwargs)


@needs_postgres
@pytest.mark.asyncio
async def test_a_failed_reconnect_makes_every_trail_on_the_dsn_fail_fast_until_the_cooldown_ends(
    trail, monkeypatch,
):
    import psycopg

    from bilinc.core import postgres_audit_sync
    from bilinc.core.postgres_audit_sync import SyncPostgresAuditTrail

    other_schema = "bilinc_p_" + uuid.uuid4().hex
    other = SyncPostgresAuditTrail(_DSN, schema=other_schema)
    await other.init()
    try:
        trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
        other.log(OpType.CREATE, "other.key", None, {"n": 1})
        _lose_session(trail)
        _lose_session(other)
        now = [1000.0]
        monkeypatch.setattr(postgres_audit_sync, "_clock", lambda: now[0])
        fake = _Psycopg()
        monkeypatch.setattr(postgres_audit_sync, "psycopg", fake)

        with pytest.raises(psycopg.OperationalError):
            trail.get_history("p0.key")
        assert len(fake.connects) == 1               # the store is down: one attempt

        with pytest.raises(psycopg.OperationalError):
            other.get_history("other.key")          # same DSN, inside the cooldown: no connect at all
        now[0] += 4.9
        with pytest.raises(psycopg.OperationalError):
            other.log(OpType.CREATE, "other.key", None, {"n": 2})
        assert len(fake.connects) == 1

        now[0] += 0.2                               # the cooldown is over: try again (still down)
        with pytest.raises(psycopg.OperationalError):
            other.get_history("other.key")
        assert len(fake.connects) == 2

        fake.down = False                           # the store is back
        now[0] += 5.1
        assert [entry.key for entry in other.get_history("other.key")] == ["other.key"]
        assert [entry.key for entry in trail.get_history("p0.key")] == ["p0.key"]   # success cleared the cooldown
        assert len(fake.connects) == 4
    finally:
        await other.close()
        _drop_schema(other_schema)


@needs_postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("call", ["read", "log"])
async def test_one_call_never_connects_twice(trail, schema, monkeypatch, call):
    """A session this call had to open, lost again in the same call, raises instead of reconnecting again."""
    import psycopg

    trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    count_before = _rows(schema, "SELECT COUNT(*) FROM {table}")[0][0]
    _lose_session(trail)                            # so the call starts by opening a new session
    real_connect = trail._connect
    connects = []

    def connect_into_a_dying_session():
        conn = real_connect()
        connects.append(conn.info.backend_pid)
        _terminate_backend(conn.info.backend_pid)
        return conn

    monkeypatch.setattr(trail, "_connect", connect_into_a_dying_session)

    with pytest.raises(psycopg.OperationalError):
        if call == "read":
            trail.get_history("p0.key")
        else:
            trail.log(OpType.CREATE, "p0.other", None, {"n": 2})
    assert len(connects) == 1
    assert _rows(schema, "SELECT COUNT(*) FROM {table}")[0][0] == count_before


@needs_postgres
@pytest.mark.asyncio
async def test_a_reconnect_passes_the_timeout_and_keepalives_to_psycopg(trail, schema, monkeypatch):
    from bilinc.core import postgres_audit_sync

    trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    _lose_session(trail)
    fake = _Psycopg()
    fake.down = False
    monkeypatch.setattr(postgres_audit_sync, "psycopg", fake)

    assert [entry.key for entry in trail.get_history("p0.key")] == ["p0.key"]

    assert fake.connects == [_DSN]                  # the DSN itself is passed through untouched
    kwargs = fake.kwargs[0]
    assert {name: kwargs.get(name) for name in (
        "connect_timeout", "keepalives", "keepalives_idle", "keepalives_interval", "keepalives_count", "autocommit",
        "application_name",
    )} == {
        "connect_timeout": 5, "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10,
        "keepalives_count": 3, "autocommit": True, "application_name": "bilinc-audit",
    }
    assert schema in kwargs["options"]
    with _admin() as admin:                         # what an operator filters pg_stat_activity by
        assert admin.execute(
            "SELECT application_name FROM pg_stat_activity WHERE pid = %s", (trail.conn.info.backend_pid,),
        ).fetchone()[0] == "bilinc-audit"


@needs_postgres
@pytest.mark.asyncio
async def test_a_reconnect_releases_the_lost_session(trail):
    """psycopg's close() returns early for a connection that is already BAD, so the libpq handle must be finished."""
    trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    _lose_session(trail)
    lost = trail.conn

    trail.get_history("p0.key")

    assert trail.conn is not lost
    assert lost.pgconn.pgconn_ptr is None


@needs_postgres
@pytest.mark.asyncio
async def test_a_failed_reconnect_logs_its_reason_but_never_the_dsn(trail, monkeypatch, caplog):
    import logging

    import psycopg

    from bilinc.core import postgres_audit_sync

    trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    _lose_session(trail)
    trail.dsn = "postgresql://p0user:SECRET-PW-123@127.0.0.1:55441/bilinc_test"
    fake = _Psycopg()
    monkeypatch.setattr(postgres_audit_sync, "psycopg", fake)
    reason = 'connection to server at "h" (10.0.0.1), port 5432 failed: FATAL:  password authentication failed for user "p0user"'

    fake.error = reason + "\nsecond line with more detail"
    with caplog.at_level(logging.WARNING, logger="bilinc.core.postgres_audit_sync"):
        with pytest.raises(psycopg.OperationalError):
            trail.get_history("p0.key")
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "OperationalError" in logged and reason in logged
    assert "second line" not in logged
    assert "SECRET-PW-123" not in logged and trail.dsn not in logged

    # Even if a connect error ever echoed the DSN, the log line would not carry it.
    caplog.clear()
    postgres_audit_sync._failed_reconnects.clear()
    fake.error = f'invalid connection string "{trail.dsn}" and then a very long tail ' + "x" * 400
    with caplog.at_level(logging.WARNING, logger="bilinc.core.postgres_audit_sync"):
        with pytest.raises(psycopg.OperationalError):
            trail.get_history("p0.key")
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "invalid connection string" in logged
    assert "SECRET-PW-123" not in logged and "x" * 201 not in logged


# ---- lost ack while another writer appends ------------------------------------------------------

@needs_postgres
@pytest.mark.asyncio
async def test_lost_ack_retry_caches_the_true_head_when_another_writer_appended(trail, schema, monkeypatch):
    from bilinc.core.postgres_audit_sync import SyncPostgresAuditTrail

    trail.log(OpType.CREATE, "p0.a", None, {"n": 1})
    other = SyncPostgresAuditTrail(_DSN, schema=schema)
    await other.init()
    real_insert = trail._insert_entry
    attempts = []
    appended = {}

    def commit_then_lose_the_ack_while_b_appends(*args, **kwargs):
        attempts.append(kwargs)
        result = real_insert(*args, **kwargs)       # A's COMMIT reaches the server
        if len(attempts) == 1:
            appended["b"] = other.log(OpType.CREATE, "p0.b", None, {"n": 2}).root_hash
            _terminate_backend(trail.conn.info.backend_pid)
            trail.conn.execute("SELECT 1")          # ...and A only sees its session die
        return result

    monkeypatch.setattr(trail, "_insert_entry", commit_then_lose_the_ack_while_b_appends)
    try:
        entry = trail.log(OpType.CREATE, "p0.lost_ack", None, {"n": 3})
    finally:
        await other.close()

    landed = _rows(schema, "SELECT id, root_hash FROM {table} WHERE key = %s", "p0.lost_ack")
    assert len(landed) == 1 and (entry.id, entry.root_hash) == landed[0]   # A's own row, once
    assert trail.get_root_hash() == appended["b"] == _head(schema)          # the cache holds the true head
    assert trail.verify_integrity()["valid"] is True


# ---- closing a lost session for real -----------------------------------------------------------

def _raise_on_close(conn) -> None:
    def close():
        raise RuntimeError("close failed")

    conn.close = close


@needs_postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("close_raises", [False, True])
async def test_closing_a_trail_whose_session_was_lost_releases_the_handle(trail, close_raises):
    trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    _lose_session(trail)
    lost = trail.conn
    if close_raises:
        _raise_on_close(lost)

    await trail.close()

    assert trail.conn is None
    assert lost.pgconn.pgconn_ptr is None


@needs_postgres
@pytest.mark.asyncio
async def test_a_reconnect_finishes_the_lost_handle_even_if_close_raises(trail):
    trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    _lose_session(trail)
    lost = trail.conn
    _raise_on_close(lost)

    assert [entry.key for entry in trail.get_history("p0.key")] == ["p0.key"]

    assert trail.conn is not lost
    assert lost.pgconn.pgconn_ptr is None


# ---- a reconnect that fails for any reason starts the cooldown ---------------------------------

@needs_postgres
@pytest.mark.asyncio
async def test_a_reconnect_refused_for_the_wrong_schema_also_starts_the_cooldown(trail, monkeypatch):
    import psycopg

    from bilinc.core import postgres_audit_sync

    trail.log(OpType.CREATE, "p0.key", None, {"n": 1})
    _lose_session(trail)
    now = [1000.0]
    monkeypatch.setattr(postgres_audit_sync, "_clock", lambda: now[0])
    monkeypatch.setattr(postgres_audit_sync, "search_path_setting", lambda name: "public")
    fake = _Psycopg()
    fake.down = False
    monkeypatch.setattr(postgres_audit_sync, "psycopg", fake)

    with pytest.raises(RuntimeError, match="tenant_schema_not_active"):
        trail.get_history("p0.key")                 # the original error, not a cooldown error
    assert len(fake.connects) == 1

    now[0] += 4.9
    with pytest.raises(psycopg.OperationalError):
        trail.get_history("p0.key")
    assert len(fake.connects) == 1                  # no connect inside the cooldown


# ---- log lines mask credentials by pattern -----------------------------------------------------

def _described(message: str, dsn=None) -> str:
    psycopg = pytest.importorskip("psycopg")
    from bilinc.core.postgres_audit_sync import describe_error

    return describe_error(psycopg.OperationalError(message), dsn)


def test_a_one_letter_password_does_not_garble_the_log_line():
    reason = 'connection to server at "127.0.0.1", port 5432 failed: FATAL:  password authentication failed for user "u"'

    assert reason in _described(reason, dsn="postgresql://u:a@127.0.0.1:5432/x")


@pytest.mark.parametrize(
    ("message", "secret", "masked"),
    [
        ('invalid URI "postgresql://u:p%40ss@h/db"', "p%40ss", 'postgresql://u:***@h/db"'),
        ('bad URI "postgres://user:pw@host:5432/db?sslmode=require"', "pw@", "postgres://user:***@host:5432/db"),
        ("invalid connection option: host=h password='x y' port=5432", "x y", "password=*** port=5432"),
        ("invalid connection option: host=h password=hunter2 port=5432", "hunter2", "password=*** port=5432"),
        ('invalid URI "postgresql://u@h/db?password=s3cret&sslmode=require"', "s3cret", "password=***&sslmode"),
    ],
)
def test_credentials_are_masked_by_pattern_without_a_dsn(message, secret, masked):
    described = _described(message)

    assert secret not in described
    assert masked in described


def test_the_whole_dsn_is_still_masked_when_given():
    dsn = "host=db.internal user=u password=pw dbname=x"

    described = _described(f"could not parse {dsn}", dsn=dsn)

    assert "db.internal" not in described and "pw" not in described
