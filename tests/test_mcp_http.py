"""HTTP MCP transport tests for auth and rate limiting."""

import json

import pytest
from mcp.types import ClientCapabilities, Implementation, InitializeRequestParams
from starlette.testclient import TestClient

from bilinc import StatePlane
from bilinc.mcp_server.server_v2 import (
    _extract_bearer_token,
    _hash_client_token,
    _resolve_http_client_id,
    create_mcp_http_app,
)


def _initialize_payload() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": InitializeRequestParams(
            protocolVersion="2025-03-26",
            capabilities=ClientCapabilities(),
            clientInfo=Implementation(name="pytest", version="1.0"),
        ).model_dump(by_alias=True, exclude_none=True),
    }


def _initialize_headers(token: str | None = None) -> dict:
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
    }
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    return headers


class TestHTTPHelpers:
    def test_extract_bearer_token(self):
        assert _extract_bearer_token("Bearer secret") == "secret"
        assert _extract_bearer_token("bearer secret") == "secret"
        assert _extract_bearer_token("Token secret") is None
        assert _extract_bearer_token("Bearer") is None
        assert _extract_bearer_token(None) is None

    def test_hash_client_token_stable(self):
        assert _hash_client_token("a") == _hash_client_token("a")
        assert _hash_client_token("a") != _hash_client_token("b")

    def test_resolve_http_client_id_prefers_token(self):
        scope = {"client": ("127.0.0.1", 1234)}
        cid = _resolve_http_client_id("secret", scope)
        assert cid.startswith("token:")
        assert _resolve_http_client_id(None, scope) == "ip:127.0.0.1"


class TestHTTPAuthAndRateLimit:
    def test_http_app_requires_auth_by_default(self, monkeypatch):
        monkeypatch.delenv("STATEMEL_API_KEY", raising=False)
        with pytest.raises(ValueError):
            create_mcp_http_app()

    def test_missing_token_returns_401(self):
        app = create_mcp_http_app(auth_token="secret")
        with TestClient(app) as client:
            response = client.post("/mcp", headers=_initialize_headers(), json=_initialize_payload())
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"

    def test_invalid_token_returns_401(self):
        app = create_mcp_http_app(auth_token="secret")
        with TestClient(app) as client:
            response = client.post("/mcp", headers=_initialize_headers("wrong"), json=_initialize_payload())
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"

    def test_valid_bearer_token_initializes_successfully(self):
        app = create_mcp_http_app(auth_token="secret")
        with TestClient(app) as client:
            response = client.post("/mcp", headers=_initialize_headers("secret"), json=_initialize_payload())
        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == 1
        assert "result" in body
        assert response.headers.get("mcp-session-id")

    def test_rate_limit_same_token_same_bucket(self):
        app = create_mcp_http_app(auth_token="secret", max_tokens=1, refill_rate=0.0)
        with TestClient(app) as client:
            first = client.post("/mcp", headers=_initialize_headers("secret"), json=_initialize_payload())
            second = client.post("/mcp", headers=_initialize_headers("secret"), json=_initialize_payload())
        assert first.status_code == 200
        assert second.status_code == 429
        assert second.json()["error"] == "rate_limited"

    def test_allow_unauthenticated_explicit_dev_mode(self, monkeypatch):
        monkeypatch.delenv("STATEMEL_API_KEY", raising=False)
        app = create_mcp_http_app(allow_unauthenticated=True, max_tokens=5, refill_rate=0.0)
        with TestClient(app) as client:
            response = client.post("/mcp", headers=_initialize_headers(), json=_initialize_payload())
        assert response.status_code == 200
        assert "result" in response.json()

    def test_route_prefix_is_configurable(self):
        app = create_mcp_http_app(auth_token="secret", route_prefix="/secure-mcp")
        with TestClient(app) as client:
            response = client.post("/secure-mcp", headers=_initialize_headers("secret"), json=_initialize_payload())
        assert response.status_code == 200

    def test_health_endpoint_requires_auth_and_reports_status(self):
        plane = StatePlane(enable_verification=False, enable_audit=False)
        app = create_mcp_http_app(plane=plane, auth_token="secret")
        with TestClient(app) as client:
            unauthorized = client.get("/health")
            authorized = client.get("/health", headers={"authorization": "Bearer secret"})

        assert unauthorized.status_code == 401
        assert authorized.status_code == 200
        payload = authorized.json()
        assert payload["service"] == "bilinc-mcp-http"
        assert payload["liveness"]["status"] == "healthy"
        assert payload["readiness"]["status"] == "healthy"

    def test_metrics_endpoint_returns_bilinc_prometheus_output(self):
        plane = StatePlane(enable_verification=False, enable_audit=False)
        app = create_mcp_http_app(plane=plane, auth_token="secret")
        with TestClient(app) as client:
            response = client.get("/metrics", headers={"authorization": "Bearer secret"})

        assert response.status_code == 200
        assert "bilinc_uptime_seconds" in response.text
        assert "synaptic" + "_" not in response.text

    def test_auth_failure_and_rate_limit_increment_metrics(self):
        plane = StatePlane(enable_verification=False, enable_audit=False)
        app = create_mcp_http_app(plane=plane, auth_token="secret", max_tokens=1, refill_rate=0.0)
        with TestClient(app) as client:
            client.post("/mcp", headers=_initialize_headers("wrong"), json=_initialize_payload())
            client.post("/mcp", headers=_initialize_headers("secret"), json=_initialize_payload())
            client.post("/mcp", headers=_initialize_headers("secret"), json=_initialize_payload())

        assert plane.metrics.get_counter("auth_failures_total") == 1
        assert plane.metrics.get_counter("rate_limit_hits_total") == 1

    def test_allow_unauthenticated_health_reports_degraded_readiness(self):
        plane = StatePlane(enable_verification=False, enable_audit=False)
        app = create_mcp_http_app(plane=plane, allow_unauthenticated=True)
        with TestClient(app) as client:
            response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["readiness"]["status"] == "degraded"
        assert "http_auth_disabled" in body["readiness"]["issues"]
