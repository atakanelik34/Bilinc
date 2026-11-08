import asyncio
from uuid import uuid4

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from bilinc.cloud.service import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    """One client for the whole test, entered as a context manager.

    A bare ``TestClient`` starts a new thread with its own event loop for every request, so a project's plane
    (including its thread-bound SQLite audit connection) was created on one thread and used on another; that
    only worked while Python happened to reuse the thread identifier. Entering the client keeps one portal thread.
    """
    with TestClient(create_app(runtime_dir=tmp_path, sidecar_token="secret")) as entered:
        yield entered


def test_requests_of_one_client_share_one_event_loop(client):
    """Guards the fixture: a bare ``TestClient`` runs every request on a new loop and thread.

    The loops are kept in a list so none can be garbage collected and have its address reused.
    """
    loops = []

    @client.app.get("/_probe_loop")
    async def probe():
        loops.append(asyncio.get_running_loop())
        return {}

    for _ in range(3):
        assert client.get("/_probe_loop").status_code == 200
    assert len(loops) == 3 and all(loop is loops[0] for loop in loops)


def test_a_bare_test_client_uses_a_new_event_loop_per_request(tmp_path):
    """The behaviour the fixture exists to avoid (deterministic: the loops are kept alive)."""
    app = create_app(runtime_dir=tmp_path, sidecar_token="secret")
    loops = []

    @app.get("/_probe_loop")
    async def probe():
        loops.append(asyncio.get_running_loop())
        return {}

    bare = TestClient(app)
    bare.get("/_probe_loop")
    bare.get("/_probe_loop")
    assert len(loops) == 2 and loops[0] is not loops[1]


def test_cloud_sidecar_requires_internal_token(client):

    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"X-Bilinc-Sidecar-Token": "secret"}).status_code == 200


def test_cloud_sidecar_keeps_project_state_isolated(client):
    headers = {"X-Bilinc-Sidecar-Token": "secret"}
    project_a = str(uuid4())
    project_b = str(uuid4())

    assert client.post(
        f"/v1/projects/{project_a}/commit",
        headers=headers,
        json={"key": "agent.memory", "value": {"tenant": "a"}},
    ).status_code == 200
    assert client.post(
        f"/v1/projects/{project_b}/commit",
        headers=headers,
        json={"key": "agent.memory", "value": {"tenant": "b"}},
    ).status_code == 200

    recall_a = client.post(
        f"/v1/projects/{project_a}/recall",
        headers=headers,
        json={"query": "tenant", "profile": "balanced"},
    ).json()
    recall_b = client.post(
        f"/v1/projects/{project_b}/recall",
        headers=headers,
        json={"query": "tenant", "profile": "balanced"},
    ).json()

    assert [item["value"] for item in recall_a["results"]] == [{"tenant": "a"}]
    assert [item["value"] for item in recall_b["results"]] == [{"tenant": "b"}]


def test_cloud_sidecar_accepts_the_same_recall_limit_as_the_public_route(client):
    """The route accepted 100 while the sidecar capped at 50, so 51-100 became 503s."""
    headers = {"X-Bilinc-Sidecar-Token": "secret"}
    project_id = str(uuid4())

    accepted = client.post(
        f"/v1/projects/{project_id}/recall",
        headers=headers,
        json={"query": "anything", "profile": "balanced", "limit": 100},
    )
    rejected = client.post(
        f"/v1/projects/{project_id}/recall",
        headers=headers,
        json={"query": "anything", "profile": "balanced", "limit": 101},
    )

    assert accepted.status_code == 200
    assert rejected.status_code == 422


def test_cloud_sidecar_forwards_a_bounded_point_in_time_timestamp(client):
    headers = {"X-Bilinc-Sidecar-Token": "secret"}
    project_id = str(uuid4())

    response = client.post(
        f"/v1/projects/{project_id}/recall",
        headers=headers,
        json={
            "query": "anything",
            "profile": "balanced",
            "query_timestamp": "2024-01-31T12:00:00Z",
        },
    )
    assert response.status_code == 200
    assert response.json().get("query_timestamp_supported") is not False

    rejected = client.post(
        f"/v1/projects/{project_id}/recall",
        headers=headers,
        json={"query": "anything", "query_timestamp": "x" * 65},
    )
    assert rejected.status_code == 422


def test_cloud_sidecar_commit_returns_versions_and_carries_provenance(client):
    headers = {"X-Bilinc-Sidecar-Token": "secret"}
    project_id = str(uuid4())

    result = client.post(
        f"/v1/projects/{project_id}/commit",
        headers=headers,
        json={
            "key": "agent.memory",
            "value": {"state": "ready"},
            "source": "hermes_session",
            "session_id": "sess-1",
            "canonical": True,
            "priority": 0.9,
        },
    ).json()

    assert result["success"] is True
    assert result["entry_version"].startswith("v1_")
    assert result["state_version"]


def test_cloud_sidecar_health_advertises_create_only_commit(client):

    health = client.get("/health", headers={"X-Bilinc-Sidecar-Token": "secret"}).json()

    assert "commit_if_absent" in health["capabilities"]


def test_cloud_sidecar_create_only_commit_never_overwrites(client):
    headers = {"X-Bilinc-Sidecar-Token": "secret"}
    project_id = str(uuid4())
    commit_url = f"/v1/projects/{project_id}/commit"

    created = client.post(
        commit_url,
        headers=headers,
        json={"key": "decision.db", "value": "postgres", "if_absent": True},
    )
    assert created.status_code == 200
    first_version = created.json()["entry_version"]

    refused = client.post(
        commit_url,
        headers=headers,
        json={"key": "decision.db", "value": "sqlite", "if_absent": True},
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "memory_exists"

    # The refused write left the entry exactly as it was: revising against the
    # original version still succeeds, which proves nothing was replaced.
    revised = client.post(
        f"/v1/projects/{project_id}/revise",
        headers=headers,
        json={"key": "decision.db", "value": "postgres 16", "expected_version": first_version},
    )
    assert revised.status_code == 200


def test_cloud_sidecar_recall_returns_a_version_revise_accepts(client):
    headers = {"X-Bilinc-Sidecar-Token": "secret"}
    project_id = str(uuid4())

    client.post(
        f"/v1/projects/{project_id}/commit",
        headers=headers,
        json={"key": "decision.database", "value": "We chose Postgres", "source": "claude"},
    )
    results = client.post(
        f"/v1/projects/{project_id}/recall",
        headers=headers,
        json={"query": "database decision"},
    ).json()["results"]

    hit = next(item for item in results if item["key"] == "decision.database")
    assert hit["entry_version"].startswith("v1_")
    assert hit["source"] == "claude"
    assert hit["updated_at"]

    revised = client.post(
        f"/v1/projects/{project_id}/revise",
        headers=headers,
        json={"key": "decision.database", "value": "Postgres 16", "expected_version": hit["entry_version"]},
    )
    assert revised.status_code == 200


def test_cloud_sidecar_plain_commit_still_revises_existing_keys(client):
    headers = {"X-Bilinc-Sidecar-Token": "secret"}
    commit_url = f"/v1/projects/{uuid4()}/commit"

    assert client.post(commit_url, headers=headers, json={"key": "k", "value": 1}).status_code == 200
    assert client.post(commit_url, headers=headers, json={"key": "k", "value": 2}).status_code == 200


def test_cloud_sidecar_rejects_an_unknown_memory_type_with_a_stable_code(client):
    headers = {"X-Bilinc-Sidecar-Token": "secret"}
    project_id = str(uuid4())

    response = client.post(
        f"/v1/projects/{project_id}/recall",
        headers=headers,
        json={"query": "anything", "memory_types": ["dreams"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_memory_type"


# Before 2.6.3 a lost audit store answered HTTP 500 text/plain; it is a 503 with a stable code now.

def _lost_connection_errors():
    psycopg = pytest.importorskip("psycopg")
    return [
        psycopg.OperationalError("the connection is closed"),               # client side: sqlstate None
        psycopg.OperationalError("server closed the connection unexpectedly"),
        psycopg.errors.AdminShutdown("terminating connection due to administrator command"),  # 57P01
        psycopg.errors.CrashShutdown("crash shutdown"),                       # 57P02
        psycopg.errors.CannotConnectNow("the database system is starting up"),  # 57P03
        psycopg.errors.lookup("08006")("connection failure"),                 # class 08
        psycopg.errors.lookup("57P04")("database dropped"),
        psycopg.errors.lookup("57P05")("idle session timeout"),
        psycopg.errors.lookup("25P03")("idle-in-transaction session timeout"),  # an InternalError, not Operational
        psycopg.errors.lookup("53300")("sorry, too many clients already"),   # common while a server restarts
    ]


def test_runtime_errors_maps_a_lost_audit_store_to_503():
    from fastapi import HTTPException

    from bilinc.cloud.service import _runtime_errors

    for error in _lost_connection_errors():
        with pytest.raises(HTTPException) as caught:
            with _runtime_errors():
                raise error
        assert (caught.value.status_code, caught.value.detail) == (503, "audit_store_unavailable"), error
        assert caught.value.__cause__ is error


@pytest.mark.parametrize("sqlstate", ["55P03", "57014", "40P01", "53100", "28P01", "28000"])
def test_runtime_errors_does_not_call_an_error_in_a_live_session_unavailable(sqlstate):
    """Lock timeout, statement cancel, deadlock, disk full: the session is fine, so no 503 and today's 500 stays.

    A rejected password (28P01, 28000) is a misconfiguration, not an outage, so it stays a 500 as well.
    """
    psycopg = pytest.importorskip("psycopg")

    from bilinc.cloud.service import _runtime_errors

    error = psycopg.errors.lookup(sqlstate)("in a live session")
    assert isinstance(error, psycopg.OperationalError)
    with pytest.raises(type(error)) as caught:
        with _runtime_errors():
            raise error
    assert caught.value is error


@pytest.mark.parametrize(
    ("code", "status", "detail"),
    [
        ("memory_not_found", 404, "memory_not_found"),
        ("memory_exists", 409, "memory_exists"),
        ("snapshot_unreadable", 404, "snapshot_unreadable"),
        ("version_conflict", 409, "version_conflict"),
        ("secret_detected", 422, "secret_detected"),
        ("purge_disabled", 403, "purge_disabled"),
        ("purge_unsupported", 501, "purge_unsupported"),
        ("invalid_cursor", 400, "invalid_cursor"),
        ("/srv/private/path: some SQL text", 400, "invalid_request"),
    ],
)
def test_runtime_errors_still_maps_value_error_codes(code, status, detail):
    from fastapi import HTTPException

    from bilinc.cloud.service import _runtime_errors

    with pytest.raises(HTTPException) as caught:
        with _runtime_errors():
            raise ValueError(code)
    assert (caught.value.status_code, caught.value.detail) == (status, detail)


def test_runtime_errors_leaves_other_errors_alone():
    """Only a lost connection is a 503: a SQL bug or a tenant-schema mismatch stays a server error."""
    psycopg = pytest.importorskip("psycopg")

    from bilinc.cloud.service import _runtime_errors

    for error in (psycopg.ProgrammingError("syntax error"), RuntimeError("tenant_schema_not_active")):
        with pytest.raises(type(error)) as caught:
            with _runtime_errors():
                raise error
        assert caught.value is error


def test_runtime_errors_logs_the_first_line_of_the_reason(caplog):
    import logging

    psycopg = pytest.importorskip("psycopg")
    from fastapi import HTTPException

    from bilinc.cloud.service import _runtime_errors

    reason = 'connection to server at "h", port 5432 failed: FATAL:  password authentication failed for user "u"'
    for message, expected in (
        (reason + "\nDETAIL: the second line", reason),
        ("y" * 500, "y" * 200),
    ):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="bilinc.cloud.service"):
            with pytest.raises(HTTPException):
                with _runtime_errors():
                    raise psycopg.OperationalError(message)
        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "OperationalError" in logged and expected in logged
        assert "DETAIL" not in logged and "y" * 201 not in logged


def test_runtime_errors_masks_url_credentials_in_its_warning(caplog):
    import logging

    psycopg = pytest.importorskip("psycopg")
    from fastapi import HTTPException

    from bilinc.cloud.service import _runtime_errors

    with caplog.at_level(logging.WARNING, logger="bilinc.cloud.service"):
        with pytest.raises(HTTPException):
            with _runtime_errors():
                raise psycopg.OperationalError('could not connect "postgresql://svc:Sup3rS3cret@db.example:5432/x"')
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "Sup3rS3cret" not in logged
    assert "postgresql://svc:***@db.example:5432/x" in logged


def test_runtime_errors_works_without_psycopg(monkeypatch):
    """SQLite-mode deployments may not have psycopg installed at all."""
    from fastapi import HTTPException

    from bilinc.cloud.service import _runtime_errors
    from bilinc.core import postgres_audit_sync

    monkeypatch.setattr(postgres_audit_sync, "psycopg", None)   # what its guarded import leaves behind
    with pytest.raises(HTTPException) as caught:
        with _runtime_errors():
            raise ValueError("memory_not_found")
    assert caught.value.status_code == 404
    with pytest.raises(RuntimeError, match="boom"):
        with _runtime_errors():
            raise RuntimeError("boom")
