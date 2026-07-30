"""Frozen public contract for the Bilinc Cloud core memory lifecycle.

This file is the single source of truth for what the public SDK and the Cloud
MCP adapter promise to agent developers. The target surface is exactly eight
lifecycle capabilities: commit_mem, recall, revise, forget, status, snapshot,
diff, and rollback. Operator/debug tooling stays local-only.
"""

from __future__ import annotations

import asyncio
import json

import pytest


CLOUD_MCP_TOOL_NAMES = (
    "commit_mem",
    "recall",
    "revise",
    "forget",
    "status",
    "snapshot",
    "diff",
    "rollback",
)

# Local-only tools that must never leak into the Cloud MCP adapter.
LOCAL_ONLY_TOOL_NAMES = (
    "consolidate",
    "summarize",
    "event_segment",
    "bilinc_workspace_preview",
    "bilinc_workspace_status",
    "bilinc_workspace_replay_session",
    "bilinc_health",
    "bilinc_benchmark",
    "bilinc_export",
    "bilinc_import",
    "claims_list",
    "claims_search",
    "claim_contradictions",
    "contradictions",
    "verify",
    "query_graph",
    "bilinc_recall_smart",
    "bilinc_query_analysis",
)


class RecordingTransport:
    """Capture outbound SDK calls and replay canned responses."""

    def __init__(self, *responses):
        self.responses = list(responses) or [{}]
        self.calls = []

    def __call__(self, method, url, *, headers, body, timeout):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": json.loads(body.decode("utf-8")) if body else None,
                "timeout": timeout,
            }
        )
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


def _client(transport):
    from bilinc import CloudClient

    return CloudClient(api_key="bil_live_contract", transport=transport)


def _tools():
    from bilinc.cloud_mcp import build_server

    return {tool.name: tool for tool in asyncio.run(build_server().list_tools())}


# --------------------------------------------------------------------------
# Frozen MCP surface
# --------------------------------------------------------------------------


def test_cloud_mcp_exposes_exactly_the_eight_lifecycle_tools():
    assert tuple(sorted(_tools())) == tuple(sorted(CLOUD_MCP_TOOL_NAMES))


def test_cloud_mcp_does_not_expose_local_only_tools():
    names = set(_tools())
    assert names.isdisjoint(LOCAL_ONLY_TOOL_NAMES)


def test_cloud_mcp_import_and_build_do_not_require_an_api_key(monkeypatch):
    monkeypatch.delenv("BILINC_API_KEY", raising=False)
    monkeypatch.setenv("BILINC_CONFIG_DIR", "/nonexistent-bilinc-config")

    assert set(_tools()) == set(CLOUD_MCP_TOOL_NAMES)


@pytest.mark.parametrize("name", ["forget", "rollback"])
def test_destructive_mcp_tools_describe_their_risk(name):
    description = (_tools()[name].description or "").lower()
    assert "destructive" in description


def test_forget_requires_key_and_reason():
    schema = _tools()["forget"].inputSchema
    assert set(schema["required"]) == {"key", "reason"}


def test_rollback_requires_explicit_mode_and_reason():
    schema = _tools()["rollback"].inputSchema
    assert "mode" in schema["properties"]
    assert set(schema["required"]) >= {"snapshot_id", "reason"}


def test_recall_keeps_profiles_in_one_tool():
    schema = _tools()["recall"].inputSchema
    assert "profile" in schema["properties"]
    assert "limit" in schema["properties"]


# --------------------------------------------------------------------------
# Frozen SDK surface
# --------------------------------------------------------------------------


def test_cloud_client_exposes_the_lifecycle_methods():
    from bilinc import CloudClient

    for method in (
        "commit",
        "recall",
        "revise",
        "forget",
        "status",
        "health",
        "snapshot",
        "diff",
        "rollback_preview",
        "rollback",
    ):
        assert callable(getattr(CloudClient, method, None)), method


def test_bilinc_alias_still_points_at_cloud_client():
    import bilinc

    assert bilinc.Bilinc is bilinc.CloudClient


def test_status_is_authenticated_and_health_is_service_level():
    transport = RecordingTransport({"ok": True})
    client = _client(transport)

    client.status()
    client.health()

    assert transport.calls[0]["method"] == "GET"
    assert transport.calls[0]["url"].endswith("/api/cloud/status")
    assert transport.calls[1]["url"].endswith("/api/cloud/health")


def test_commit_and_recall_paths_are_unchanged():
    transport = RecordingTransport({"success": True}, {"results": []})
    client = _client(transport)

    client.commit("project.status", {"phase": "trial"})
    client.recall("trial status")

    assert transport.calls[0]["url"].endswith("/api/cloud/memory/commit")
    assert transport.calls[1]["url"].endswith("/api/cloud/memory/recall")


def test_lifecycle_methods_use_their_public_routes():
    transport = RecordingTransport({"ok": True})
    client = _client(transport)

    client.revise("k", {"v": 1})
    client.forget("k", reason="superseded")
    client.snapshot(action="create")
    client.snapshot(action="list")
    client.diff("snap_a")
    client.rollback_preview("snap_a", reason="bad agent run")
    client.rollback("snap_a", confirmation_token="tok", reason="bad agent run")

    paths = [call["url"].split("bilinc.space")[-1] for call in transport.calls]
    assert paths == [
        "/api/cloud/memory/revise",
        "/api/cloud/memory/forget",
        "/api/cloud/memory/snapshots",
        "/api/cloud/memory/snapshots?limit=20",
        "/api/cloud/memory/diff",
        "/api/cloud/memory/rollback/preview",
        "/api/cloud/memory/rollback",
    ]


def test_snapshot_list_is_a_read_and_create_is_a_write():
    transport = RecordingTransport({"snapshots": []})
    client = _client(transport)

    client.snapshot(action="list")
    client.snapshot(action="create", label="before-refactor")

    assert transport.calls[0]["method"] == "GET"
    assert transport.calls[1]["method"] == "POST"
    assert transport.calls[1]["body"]["label"] == "before-refactor"


def test_forget_requires_a_reason_in_the_sdk():
    from bilinc.client import BilincValidationError

    client = _client(RecordingTransport({"ok": True}))

    with pytest.raises(BilincValidationError):
        client.forget("k", reason="   ")


def test_rollback_execute_requires_a_confirmation_token():
    from bilinc.client import BilincValidationError

    client = _client(RecordingTransport({"ok": True}))

    with pytest.raises(BilincValidationError):
        client.rollback("snap_a", confirmation_token="", reason="cleanup")


def test_recall_limit_is_bounded_at_one_hundred():
    from bilinc.client import MAX_RECALL_LIMIT, BilincValidationError

    assert MAX_RECALL_LIMIT == 100
    client = _client(RecordingTransport({"results": []}))

    client.recall("q", limit=MAX_RECALL_LIMIT)
    with pytest.raises(BilincValidationError):
        client.recall("q", limit=MAX_RECALL_LIMIT + 1)


def test_idempotency_key_travels_as_a_header():
    transport = RecordingTransport({"ok": True})
    client = _client(transport)

    client.commit("k", 1, idempotency_key="req-1")

    assert transport.calls[0]["headers"]["Idempotency-Key"] == "req-1"


# --------------------------------------------------------------------------
# Frozen error contract
# --------------------------------------------------------------------------


CANONICAL_ERROR_STATUS = {
    "missing_api_key": 401,
    "invalid_api_key": 401,
    "entitlement_inactive": 403,
    "capability_not_entitled": 403,
    "payment_required": 402,
    "invalid_request": 400,
    "memory_not_found": 404,
    "snapshot_not_found": 404,
    "version_conflict": 409,
    "idempotency_conflict": 409,
    "state_changed_since_preview": 409,
    "rollback_confirmation_expired": 410,
    "rate_limited": 429,
    "cloud_runtime_unavailable": 503,
}


def test_canonical_error_codes_are_published_by_the_sdk():
    from bilinc.client import CANONICAL_ERROR_CODES

    assert dict(CANONICAL_ERROR_CODES) == CANONICAL_ERROR_STATUS


@pytest.mark.parametrize(
    ("status", "exc_name"),
    [
        (401, "BilincAuthError"),
        (402, "BilincPaymentRequiredError"),
        (403, "BilincEntitlementError"),
        (400, "BilincValidationError"),
        (404, "BilincNotFoundError"),
        (409, "BilincConflictError"),
        (410, "BilincConfirmationExpiredError"),
        (429, "BilincRateLimitError"),
        (503, "BilincRuntimeUnavailableError"),
    ],
)
def test_http_status_maps_to_a_typed_sdk_error(status, exc_name):
    import bilinc.client as client_module

    expected = getattr(client_module, exc_name)
    raised = client_module.error_for_response(
        status,
        {"error": "boom", "message": "boom", "requestId": "req_1", "retryable": False},
    )

    assert isinstance(raised, expected)
    assert isinstance(raised, client_module.BilincCloudError)
    assert raised.status == status
    assert raised.request_id == "req_1"


def test_typed_errors_remain_catchable_as_the_legacy_base():
    from bilinc.client import BilincCloudError, BilincError, error_for_response

    error = error_for_response(503, {"error": "cloud_runtime_unavailable"})

    assert isinstance(error, BilincCloudError)
    assert isinstance(error, BilincError)
    assert error.retryable is True
