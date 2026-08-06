from uuid import uuid4

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from bilinc.cloud.service import create_app  # noqa: E402


def test_cloud_sidecar_requires_internal_token(tmp_path):
    client = TestClient(create_app(runtime_dir=tmp_path, sidecar_token="secret"))

    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"X-Bilinc-Sidecar-Token": "secret"}).status_code == 200


def test_cloud_sidecar_keeps_project_state_isolated(tmp_path):
    client = TestClient(create_app(runtime_dir=tmp_path, sidecar_token="secret"))
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


def test_cloud_sidecar_accepts_the_same_recall_limit_as_the_public_route(tmp_path):
    """The route accepted 100 while the sidecar capped at 50, so 51-100 became 503s."""
    client = TestClient(create_app(runtime_dir=tmp_path, sidecar_token="secret"))
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


def test_cloud_sidecar_forwards_a_bounded_point_in_time_timestamp(tmp_path):
    client = TestClient(create_app(runtime_dir=tmp_path, sidecar_token="secret"))
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


def test_cloud_sidecar_commit_returns_versions_and_carries_provenance(tmp_path):
    client = TestClient(create_app(runtime_dir=tmp_path, sidecar_token="secret"))
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


def test_cloud_sidecar_rejects_an_unknown_memory_type_with_a_stable_code(tmp_path):
    client = TestClient(create_app(runtime_dir=tmp_path, sidecar_token="secret"))
    headers = {"X-Bilinc-Sidecar-Token": "secret"}
    project_id = str(uuid4())

    response = client.post(
        f"/v1/projects/{project_id}/recall",
        headers=headers,
        json={"query": "anything", "memory_types": ["dreams"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_memory_type"
