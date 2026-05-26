from uuid import uuid4

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from bilinc.cloud.service import create_app


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
