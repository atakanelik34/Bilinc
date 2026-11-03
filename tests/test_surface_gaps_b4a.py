"""B4a: rollback preview `limit` in the Cloud MCP adapter and the CLI, and SDK `get_memory`."""
from __future__ import annotations

import asyncio
import json

import pytest

import bilinc.cli.main as cli_main
import bilinc.cloud_mcp as cloud_mcp
from bilinc import BilincNotFoundError, BilincValidationError, CloudClient


class RecordingTransport:
    def __init__(self, *responses):
        self.responses = list(responses) or [{}]
        self.calls = []

    def __call__(self, method, url, *, headers, body, timeout):
        self.calls.append({"method": method, "url": url,
                           "body": json.loads(body.decode("utf-8")) if body else None})
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def _client(transport) -> CloudClient:
    return CloudClient(api_key="bil_live_example", transport=transport)


# ---- Cloud MCP rollback ---------------------------------------------------------------------

class _FakeSdk:
    def __init__(self):
        self.calls = []

    def rollback_preview(self, snapshot_id, **kwargs):
        self.calls.append(("preview", snapshot_id, kwargs))
        return {"ok": True}

    def rollback(self, snapshot_id, **kwargs):
        self.calls.append(("execute", snapshot_id, kwargs))
        return {"ok": True}


def _call_tool(monkeypatch, arguments):
    sdk = _FakeSdk()
    monkeypatch.setattr(cloud_mcp, "create_client", lambda: sdk)
    asyncio.run(cloud_mcp.build_server().call_tool("rollback", arguments))
    return sdk.calls


def test_mcp_rollback_preview_passes_limit_and_defaults_to_100(monkeypatch):
    assert _call_tool(monkeypatch, {"snapshot_id": "snap_a", "reason": "r", "limit": 7}) == [
        ("preview", "snap_a", {"reason": "r", "limit": 7})]
    assert _call_tool(monkeypatch, {"snapshot_id": "snap_a", "reason": "r"}) == [
        ("preview", "snap_a", {"reason": "r", "limit": 100})]


def test_mcp_rollback_execute_sends_no_limit(monkeypatch):
    calls = _call_tool(monkeypatch, {"snapshot_id": "snap_a", "reason": "r", "mode": "execute",
                                     "confirmation_token": "tok", "limit": 7})
    assert calls == [("execute", "snap_a", {"confirmation_token": "tok", "reason": "r", "idempotency_key": None})]


def test_mcp_rollback_schema_gains_an_optional_limit_only():
    tools = {t.name: t for t in asyncio.run(cloud_mcp.build_server().list_tools())}
    schema = tools["rollback"].inputSchema
    assert "limit" in schema["properties"] and schema["properties"]["limit"]["default"] == 100
    assert "limit" not in schema.get("required", [])
    assert "limit" in (tools["rollback"].description or "")


@pytest.mark.parametrize("limit", [0, 501])
def test_mcp_rollback_limit_out_of_range_is_rejected_by_the_sdk(limit):
    transport = RecordingTransport({})
    client = _client(transport)
    with pytest.raises(BilincValidationError):
        client.rollback_preview("snap_a", reason="r", limit=limit)
    assert transport.calls == []


# ---- CLI rollback ---------------------------------------------------------------------------

def _run_cli(monkeypatch, capsys, *argv):
    transport = RecordingTransport({"ok": True})
    monkeypatch.setattr(cli_main, "_client", lambda args: _client(transport))
    code = cli_main.main(list(argv))
    capsys.readouterr()
    return code, transport.calls


def test_cli_rollback_preview_limit(monkeypatch, capsys):
    code, calls = _run_cli(monkeypatch, capsys, "rollback", "preview", "--snapshot", "snap_a",
                           "--reason", "r", "--limit", "7")
    assert code == 0 and calls[0]["body"]["limit"] == 7
    code, calls = _run_cli(monkeypatch, capsys, "rollback", "preview", "--snapshot", "snap_a", "--reason", "r")
    assert code == 0 and calls[0]["body"]["limit"] == 100


def test_cli_rollback_execute_ignores_limit(monkeypatch, capsys):
    code, calls = _run_cli(monkeypatch, capsys, "rollback", "execute", "--snapshot", "snap_a", "--reason", "r",
                           "--confirmation-token", "tok", "--limit", "7")
    assert code == 0
    assert calls[0]["url"].endswith("/api/cloud/memory/rollback") and "limit" not in calls[0]["body"]


@pytest.mark.parametrize("limit", ["0", "501"])
def test_cli_rollback_preview_limit_out_of_range_fails_cleanly(monkeypatch, capsys, limit):
    transport = RecordingTransport({})
    monkeypatch.setattr(cli_main, "_client", lambda args: _client(transport))
    code = cli_main.main(["rollback", "preview", "--snapshot", "snap_a", "--reason", "r", "--limit", limit])
    assert code != 0 and transport.calls == []
    assert "Traceback" not in capsys.readouterr().err


# ---- SDK get_memory -------------------------------------------------------------------------

def _entry(key, value="v"):
    return {"key": key, "value": value, "entryVersion": f"v_{key}"}


def test_get_memory_returns_the_exact_key_even_when_siblings_sort_first():
    page1 = {"entries": [_entry("note-1"), _entry("note-2")], "nextCursor": "c1"}
    page2 = {"entries": [_entry("note", "wanted")], "nextCursor": None}
    transport = RecordingTransport(page1, page2)

    entry = _client(transport).get_memory("note")

    assert entry["value"] == "wanted" and entry["entryVersion"] == "v_note"
    first = transport.calls[0]
    assert first["url"].endswith("/api/cloud/memory/list")
    assert first["body"]["prefix"] == "note" and first["body"]["values"] == "full"
    assert first["body"]["limit"] == 10
    assert transport.calls[1]["body"]["cursor"] == "c1"


def test_get_memory_stops_at_the_first_match():
    transport = RecordingTransport({"entries": [_entry("note")], "nextCursor": "more"}, {"entries": []})
    _client(transport).get_memory("note")
    assert len(transport.calls) == 1


def test_get_memory_does_not_return_a_longer_key_sharing_the_prefix():
    transport = RecordingTransport({"entries": [_entry("note-1")], "nextCursor": None})
    with pytest.raises(BilincNotFoundError) as caught:
        _client(transport).get_memory("note")
    error = caught.value
    assert (error.code, error.status, error.retryable) == ("memory_not_found", 404, False)


def test_get_memory_validates_the_key_before_any_request():
    transport = RecordingTransport({})
    client = _client(transport)
    for bad in ("", "   ", "k" * 513):
        with pytest.raises(BilincValidationError):
            client.get_memory(bad)
    assert transport.calls == []


def test_get_memory_strips_the_key_like_history_does():
    transport = RecordingTransport({"entries": [_entry("note")], "nextCursor": None})
    assert _client(transport).get_memory("  note ")["key"] == "note"
    assert transport.calls[0]["body"]["prefix"] == "note"


def test_get_memory_forwards_values():
    transport = RecordingTransport({"entries": [_entry("note")], "nextCursor": None})
    _client(transport).get_memory("note", values="preview")
    assert transport.calls[0]["body"]["values"] == "preview"
