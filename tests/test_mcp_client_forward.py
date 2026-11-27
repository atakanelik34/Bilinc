"""The stdio adapter forwards the MCP client's initialize clientInfo as a label header."""

from __future__ import annotations

import asyncio

import pytest

from bilinc.client import CloudClient, mcp_client_label


def _recording_client(seen: list[dict[str, str]]) -> CloudClient:
    def transport(method, url, *, headers, body, timeout):  # noqa: ANN001 - test double
        seen.append(dict(headers))
        return {"ok": True, "status": "ok"}

    return CloudClient(api_key="bil_live_example", transport=transport)


@pytest.fixture(autouse=True)
def _no_saved_config(monkeypatch):
    monkeypatch.setenv("BILINC_CONFIG_DIR", "/nonexistent-bilinc-config")
    monkeypatch.delenv("BILINC_BASE_URL", raising=False)
    monkeypatch.delenv("BILINC_CLIENT_COMMAND", raising=False)


def _call_over_session(monkeypatch, client_info):
    from mcp.shared.memory import create_connected_server_and_client_session

    from bilinc import cloud_mcp

    seen: list[dict[str, str]] = []
    monkeypatch.setattr(cloud_mcp, "create_client", lambda: _recording_client(seen))
    server = cloud_mcp.build_server()

    async def run():
        async with create_connected_server_and_client_session(server, client_info=client_info) as session:
            for name, arguments in (("status", {}), ("recall", {"query": "q"})):
                result = await session.call_tool(name, arguments)
                assert not result.isError, result

    asyncio.run(run())
    return seen


def test_adapter_sends_initialize_client_name_on_every_call(monkeypatch):
    from mcp.types import Implementation

    seen = _call_over_session(monkeypatch, Implementation(name="claude-code", version="2.1.0"))
    assert len(seen) == 2
    assert seen[1]["X-Bilinc-Client"] == "python-sdk"
    for headers in seen:
        assert headers["X-Bilinc-Mcp-Client"] == "claude-code"
        assert headers["X-Bilinc-Mcp-Client-Version"] == "2.1.0"


def test_adapter_sanitises_hostile_client_name(monkeypatch):
    from mcp.types import Implementation

    seen = _call_over_session(monkeypatch, Implementation(name="Cur\nsor<script>" + "x" * 80, version="\x00"))
    label = seen[0]["X-Bilinc-Mcp-Client"]
    assert label.startswith("Cursorscript")
    assert len(label) <= 48
    assert "X-Bilinc-Mcp-Client-Version" not in seen[0]


def test_plain_sdk_calls_send_no_mcp_client_header():
    seen: list[dict[str, str]] = []
    _recording_client(seen).recall("k")
    assert "X-Bilinc-Mcp-Client" not in seen[0]


def test_reads_carry_mcp_label_but_not_activation_client():
    seen: list[dict[str, str]] = []
    client = _recording_client(seen)
    client.mcp_client = "codex"
    client.health()
    assert seen[0]["X-Bilinc-Mcp-Client"] == "codex"
    assert "X-Bilinc-Client" not in seen[0]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Claude Code", "Claude Code"),
        ("  ", None),
        ("é€", None),
        (None, None),
        (42, None),
        ("a" * 60, "a" * 48),
        ("glama.ai_v1-x", "glama.ai_v1-x"),
    ],
)
def test_mcp_client_label(raw, expected):
    assert mcp_client_label(raw) == expected
