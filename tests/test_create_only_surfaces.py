"""B4b: the create-only commit (``if_absent``) on the Cloud MCP adapter and the CLI.

The SDK already sends ``ifAbsent``; these surfaces pass it through. Without the option the request is the
same as before. The network is a recording transport; no real key is used.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from bilinc.client import CloudClient, error_for_response

SECRET_VALUE = "a value that must not come back in an error"


class Recording:
    def __init__(self, answer=None, error=None):
        self.answer = answer if answer is not None else {"success": True}
        self.error = error
        self.bodies = []

    def __call__(self, method, url, *, headers, body, timeout):
        self.bodies.append(json.loads(body.decode("utf-8")) if body else None)
        if self.error is not None:
            raise self.error
        return self.answer


def _exists():
    return error_for_response(409, {"error": "memory_exists", "message": "memory already exists"})


def _mcp(monkeypatch, transport):
    import bilinc.cloud_mcp as cloud_mcp

    monkeypatch.setattr(cloud_mcp, "create_client", lambda: CloudClient(api_key="bil_live_example", transport=transport))
    return cloud_mcp.build_server()


def _call(server, arguments):
    return asyncio.run(server.call_tool("commit_mem", arguments))


def _text(result):
    """Flatten whatever FastMCP returns (content list, or (content, structured)) into text."""
    parts = result[0] if isinstance(result, tuple) else result
    return " ".join(getattr(part, "text", str(part)) for part in parts)


# 1 ----------------------------------------------------------------------------------------------
def test_mcp_commit_mem_passes_if_absent_through(monkeypatch):
    transport = Recording()
    server = _mcp(monkeypatch, transport)
    _call(server, {"key": "k", "value": 1, "if_absent": True})
    _call(server, {"key": "k", "value": 1})
    assert transport.bodies[0]["ifAbsent"] is True
    assert "ifAbsent" not in transport.bodies[1]                 # default request unchanged


# 2 ----------------------------------------------------------------------------------------------
def test_mcp_commit_mem_schema_has_an_optional_if_absent(monkeypatch):
    server = _mcp(monkeypatch, Recording())
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    schema = tools["commit_mem"].inputSchema
    assert "if_absent" in schema["properties"]
    assert "if_absent" not in schema.get("required", [])
    assert "memory_exists" in (tools["commit_mem"].description or "")


# 3 ----------------------------------------------------------------------------------------------
def test_mcp_commit_mem_reports_memory_exists_as_an_error(monkeypatch):
    server = _mcp(monkeypatch, Recording(error=_exists()))
    try:
        result = _call(server, {"key": "k", "value": SECRET_VALUE, "if_absent": True})
    except Exception as exc:                                     # ToolError on some mcp versions
        text = str(exc)
    else:
        text = _text(result)                                     # an isError result
    # The SDK puts the service's message in the error text (the code stays on the exception, as for every
    # tool); a success answer would carry neither.
    assert "memory already exists" in text
    assert '"success": true' not in text.lower()
    assert SECRET_VALUE not in text


# 4 + 5 ------------------------------------------------------------------------------------------
@pytest.fixture
def cli(monkeypatch, tmp_path):
    import bilinc.cli.main as cli_main

    monkeypatch.setenv("BILINC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("BILINC_API_KEY", "bil_live_example")
    monkeypatch.delenv("BILINC_BASE_URL", raising=False)

    def run(transport, *argv):
        monkeypatch.setattr(cli_main, "_client", lambda args: CloudClient(api_key="bil_live_example", transport=transport))
        return cli_main.main(list(argv))

    return run


def test_cli_commit_if_absent_flag(cli):
    transport = Recording()
    assert cli(transport, "commit", "--key", "k", "--value", "v", "--if-absent") == 0
    assert cli(transport, "commit", "--key", "k", "--value", "v") == 0
    assert transport.bodies[0]["ifAbsent"] is True
    assert "ifAbsent" not in transport.bodies[1]


def test_cli_commit_if_absent_on_an_existing_key_fails(cli, capsys):
    assert cli(Recording(error=_exists()), "commit", "--key", "k", "--value", SECRET_VALUE, "--if-absent") == 1
    err = capsys.readouterr().err
    assert "bilinc: error:" in err and "memory already exists" in err
    assert SECRET_VALUE not in err
