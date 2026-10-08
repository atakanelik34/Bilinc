"""SDK, CLI and stdio MCP surface for 2.3.8 memory review: list, history, confirm, export."""

from __future__ import annotations

import asyncio
import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest


class RecordingTransport:
    """Capture outbound SDK calls and replay canned responses in order."""

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
            }
        )
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


def _client(transport):
    from bilinc import CloudClient

    return CloudClient(api_key="bil_live_example", transport=transport)


# --- client ------------------------------------------------------------------


def test_history_posts_camel_case_to_the_history_route():
    transport = RecordingTransport({"key": "a", "entries": []})

    _client(transport).history("team.deploy_day", limit=5, values="preview")

    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://bilinc.space/api/cloud/memory/history"
    assert call["body"] == {"key": "team.deploy_day", "limit": 5, "values": "preview"}
    assert "Idempotency-Key" not in call["headers"]


def test_history_validates_inputs_before_any_request():
    from bilinc import BilincValidationError

    transport = RecordingTransport({})
    client = _client(transport)

    with pytest.raises(BilincValidationError):
        client.history("")
    with pytest.raises(BilincValidationError):
        client.history("a", limit=101)
    with pytest.raises(BilincValidationError):
        client.history("a", values="raw")
    assert transport.calls == []


def test_list_memories_sends_filters_and_normalizes_datetimes():
    transport = RecordingTransport({"entries": [], "nextCursor": None, "total": 0})
    naive = datetime(2026, 10, 1, 12, 0, 0)
    aware = datetime(2026, 10, 8, 15, 0, 0, tzinfo=timezone(timedelta(hours=3)))

    _client(transport).list_memories(
        prefix="team.",
        memory_type="working",
        updated_after=naive,
        updated_before=aware,
        cursor="abc",
        limit=25,
        values="none",
    )

    call = transport.calls[0]
    assert call["url"] == "https://bilinc.space/api/cloud/memory/list"
    assert call["body"] == {
        "limit": 25,
        "values": "none",
        "prefix": "team.",
        "memoryType": "working",
        "updatedAfter": "2026-10-01T12:00:00Z",
        "updatedBefore": "2026-10-08T12:00:00Z",
        "cursor": "abc",
    }


def test_list_memories_defaults_and_iso_string_passthrough():
    transport = RecordingTransport({"entries": []})

    _client(transport).list_memories(updated_after="2026-10-01T00:00:00Z")

    assert transport.calls[0]["body"] == {
        "limit": 50,
        "values": "preview",
        "updatedAfter": "2026-10-01T00:00:00Z",
    }


def test_list_memories_rejects_unknown_memory_type():
    from bilinc import BilincValidationError

    with pytest.raises(BilincValidationError):
        _client(RecordingTransport({})).list_memories(memory_type="imaginary")


def test_iter_memories_follows_the_cursor_to_the_last_page():
    transport = RecordingTransport(
        {"entries": [{"key": "a"}, {"key": "b"}], "nextCursor": "c1", "total": 3},
        {"entries": [{"key": "c"}], "nextCursor": None, "total": 3},
    )

    keys = [entry["key"] for entry in _client(transport).iter_memories(prefix="x", page_size=2)]

    assert keys == ["a", "b", "c"]
    assert "cursor" not in transport.calls[0]["body"]
    assert transport.calls[1]["body"]["cursor"] == "c1"
    assert all(call["body"]["limit"] == 2 and call["body"]["prefix"] == "x" for call in transport.calls)


def test_iter_memories_stops_on_a_repeated_cursor():
    from bilinc import BilincCloudError

    transport = RecordingTransport({"entries": [{"key": "a"}], "nextCursor": "same"})

    with pytest.raises(BilincCloudError):
        list(_client(transport).iter_memories())
    assert len(transport.calls) == 2


def test_export_pages_with_full_values():
    transport = RecordingTransport(
        {"entries": [{"key": "a", "value": 1}], "nextCursor": "c1"},
        {"entries": [{"key": "b", "value": {"x": 2}}], "nextCursor": None},
    )

    exported = _client(transport).export(prefix="team.")

    assert exported["count"] == 2
    assert [entry["key"] for entry in exported["entries"]] == ["a", "b"]
    assert exported["exported_at"].endswith("Z")
    assert all(call["body"]["values"] == "full" for call in transport.calls)
    assert all(call["body"]["limit"] == 100 for call in transport.calls)


def _too_large():
    from bilinc.client import error_for_response

    return error_for_response(
        400,
        {"error": "invalid_request", "message": "too large", "details": {"reason": "response_too_large"}},
    )


def test_export_retries_an_oversized_page_with_smaller_pages():
    transport = RecordingTransport(
        _too_large(),
        {"entries": [{"key": "a", "value": "x" * 10}], "nextCursor": None},
    )

    exported = _client(transport).export()

    assert exported["count"] == 1
    assert [call["body"]["limit"] for call in transport.calls] == [100, 10]
    assert "valueOmitted" not in exported["entries"][0]


def test_export_shrinks_to_single_entries_and_keeps_every_full_value():
    transport = RecordingTransport(
        _too_large(),
        _too_large(),
        {"entries": [{"key": "huge", "value": "x" * 50}], "nextCursor": None},
    )

    exported = _client(transport).export()

    assert exported["entries"] == [{"key": "huge", "value": "x" * 50}]
    assert [(call["body"]["limit"], call["body"]["values"]) for call in transport.calls] == [
        (100, "full"),
        (10, "full"),
        (1, "full"),
    ]


def test_export_fails_rather_than_dropping_a_value():
    from bilinc import BilincValidationError

    transport = RecordingTransport(_too_large(), _too_large(), _too_large())

    with pytest.raises(BilincValidationError):
        _client(transport).export()
    assert all(call["body"]["values"] == "full" for call in transport.calls)


def test_export_does_not_swallow_other_validation_errors():
    from bilinc import BilincValidationError
    from bilinc.client import error_for_response

    transport = RecordingTransport(error_for_response(400, {"error": "invalid_request", "message": "bad cursor"}))

    with pytest.raises(BilincValidationError):
        _client(transport).export()
    assert len(transport.calls) == 1


def test_confirm_is_a_single_shot_write_with_optional_fields():
    transport = RecordingTransport({"success": True, "confirmed": True})

    _client(transport).confirm("home.city", expected_version="v1_abc", reason="still true", idempotency_key="idem-1")

    call = transport.calls[0]
    assert call["url"] == "https://bilinc.space/api/cloud/memory/confirm"
    assert call["body"] == {"key": "home.city", "expectedVersion": "v1_abc", "reason": "still true"}
    assert call["headers"]["Idempotency-Key"] == "idem-1"


@pytest.mark.parametrize(
    ("status", "code", "exc_name"),
    [
        (404, "memory_not_found", "BilincNotFoundError"),
        (409, "version_conflict", "BilincConflictError"),
        (503, "capability_unavailable", "BilincRuntimeUnavailableError"),
    ],
)
def test_confirm_errors_map_to_typed_errors_and_are_not_retried(status, code, exc_name):
    import bilinc.client as client_module

    error = client_module.error_for_response(status, {"error": code, "retryable": status == 503})
    transport = RecordingTransport(error)

    with pytest.raises(getattr(client_module, exc_name)) as raised:
        _client(transport).confirm("home.city")

    assert raised.value.code == code
    assert len(transport.calls) == 1


def test_review_methods_are_part_of_the_public_client():
    from bilinc import CloudClient

    for method in ("history", "list_memories", "iter_memories", "confirm", "export"):
        assert callable(getattr(CloudClient, method, None)), method


# --- CLI ---------------------------------------------------------------------


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, api_key=None, base_url="https://bilinc.space", timeout=30.0):
        self.calls = []
        FakeClient.instances.append(self)

    def history(self, key, *, limit=20, values="full"):
        self.calls.append(("history", key, limit, values))
        return {
            "key": key,
            "exists": True,
            "entries": [
                {"op": "confirm", "at": "2026-10-08T12:00:03.000Z", "before": "thursday", "after": "thursday"},
                {
                    "op": "update",
                    "at": "2026-10-08T12:00:02.000Z",
                    "before": "tuesday",
                    "after": "thursday",
                    "reason": "moved",
                    "source": "claude",
                },
                {"op": "forget", "at": "2026-10-01T09:00:00.000Z", "reason": "stale", "valuesRedacted": True},
            ],
            "truncated": True,
            "values": values,
        }

    def list_memories(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {
            "entries": [
                {
                    "key": "team.deploy_day",
                    "memoryType": "semantic",
                    "updatedAt": "2026-10-08T12:00:02.000Z",
                    "value": "thursday",
                }
            ],
            "nextCursor": "next123",
            "total": 7,
        }

    def iter_memories(self, **kwargs):
        self.calls.append(("iter", kwargs))
        yield {"key": "a", "memoryType": "working", "updatedAt": "2026-10-08T00:00:00Z", "value": 1}
        yield {"key": "b", "memoryType": "semantic", "updatedAt": "2026-10-08T00:00:01Z", "value": 2}

    def confirm(self, key, *, expected_version=None, reason=None):
        self.calls.append(("confirm", key, expected_version, reason))
        return {"success": True, "key": key, "confirmed": True}

    def export(self, *, prefix=None, memory_type=None):
        self.calls.append(("export", prefix, memory_type))
        return {"exported_at": "2026-10-08T12:00:00Z", "count": 1, "entries": [{"key": "a", "value": "secret"}]}


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    from bilinc.cli import main as cli_main

    FakeClient.instances = []
    monkeypatch.setenv("BILINC_API_KEY", "bil_live_cli_test")
    monkeypatch.setenv("BILINC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(cli_main, "CloudClient", FakeClient)
    return cli_main


def test_cli_history_prints_a_compact_timeline(cli, capsys):
    assert cli.main(["history", "team.deploy_day", "--limit", "3"]) == 0
    out = capsys.readouterr().out

    assert "team.deploy_day  (3 shown, newest first)" in out
    assert "2026-10-08 12:00:02  update    tuesday -> thursday  reason: moved  source: claude" in out
    assert "confirm" in out
    assert "(value not shown: the memory was forgotten)" in out
    assert "older changes not shown" in out
    assert FakeClient.instances[0].calls == [("history", "team.deploy_day", 3, "full")]


def test_cli_history_json_prints_the_raw_response(cli, capsys):
    assert cli.main(["history", "team.deploy_day", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["key"] == "team.deploy_day"


def test_cli_list_prints_a_table_with_a_next_page_hint(cli, capsys):
    assert cli.main(["list", "--prefix", "team.", "--type", "semantic", "--limit", "10"]) == 0
    out = capsys.readouterr().out

    assert "KEY" in out and "UPDATED (UTC)" in out
    assert "team.deploy_day" in out and "thursday" in out
    assert "1 shown of 7" in out
    # The continuation repeats the filters: a cursor alone would widen the scope.
    assert "bilinc list --prefix team. --type semantic --limit 10 --cursor next123" in out
    _, kwargs = FakeClient.instances[0].calls[0]
    assert kwargs["prefix"] == "team." and kwargs["memory_type"] == "semantic" and kwargs["limit"] == 10


def test_cli_list_all_follows_every_page(cli, capsys):
    assert cli.main(["list", "--all", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [entry["key"] for entry in payload["entries"]] == ["a", "b"]
    assert FakeClient.instances[0].calls[0][0] == "iter"


def test_cli_confirm_prints_the_result(cli, capsys):
    assert cli.main(["confirm", "home.city", "--expected-version", "v1_abc", "--reason", "checked"]) == 0
    assert '"confirmed": true' in capsys.readouterr().out
    assert FakeClient.instances[0].calls == [("confirm", "home.city", "v1_abc", "checked")]


def test_cli_export_writes_an_owner_only_file(cli, capsys, tmp_path):
    target = tmp_path / "bilinc-export.json"

    assert cli.main(["export", "-o", str(target), "--prefix", "team."]) == 0

    captured = capsys.readouterr()
    assert "secret" not in captured.out
    assert "Exported 1 memories" in captured.err
    assert json.loads(target.read_text(encoding="utf-8"))["count"] == 1
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_cli_export_defaults_to_stdout(cli, capsys):
    assert cli.main(["export"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 1


def test_cli_review_commands_fail_cleanly_without_a_key(monkeypatch, capsys):
    from bilinc.cli.main import main

    monkeypatch.delenv("BILINC_API_KEY", raising=False)
    monkeypatch.setenv("BILINC_CONFIG_DIR", os.devnull)

    for argv in (["history", "a"], ["list"], ["confirm", "a"], ["export"]):
        assert main(argv) == 1
        err = capsys.readouterr().err
        assert "Traceback" not in err
        assert "bilinc login" in err


# --- stdio MCP ----------------------------------------------------------------


def _tools():
    from bilinc.cloud_mcp import build_server

    return {tool.name: tool for tool in asyncio.run(build_server().list_tools())}


def test_review_tools_are_registered_with_honest_hints():
    tools = _tools()

    for name in ("list_memories", "history"):
        hints = tools[name].annotations
        assert hints.readOnlyHint is True and hints.destructiveHint is False, name

    confirm = tools["confirm"].annotations
    assert confirm.readOnlyHint is False
    assert confirm.destructiveHint is False


def test_review_tool_schemas():
    tools = _tools()

    assert tools["history"].inputSchema["required"] == ["key"]
    assert tools["confirm"].inputSchema["required"] == ["key"]
    assert "required" not in tools["list_memories"].inputSchema or not tools["list_memories"].inputSchema["required"]
    assert {"prefix", "memory_type", "cursor", "limit", "values"} <= set(tools["list_memories"].inputSchema["properties"])


@pytest.mark.parametrize("name", ["list_memories", "history", "confirm"])
def test_review_tool_descriptions_state_facts_not_instructions(name):
    description = (_tools()[name].description or "").lower()

    for phrase in ("you should", "you must", "always ", "never call", "before using", "make sure"):
        assert phrase not in description, (name, phrase)


def test_cloud_mcp_tool_constant_matches_the_registered_tools():
    from bilinc.cloud_mcp import CLOUD_MCP_TOOLS

    assert set(CLOUD_MCP_TOOLS) == set(_tools())


def test_cli_list_hint_quotes_filter_values(cli, capsys):
    assert cli.main(["list", "--prefix", "my team", "--values", "none"]) == 0
    out = capsys.readouterr().out

    assert "bilinc list --prefix 'my team' --limit 50 --values none --cursor next123" in out


def test_cli_export_tightens_an_existing_world_readable_file(cli, capsys, tmp_path):
    target = tmp_path / "existing.json"
    target.write_text("old")
    os.chmod(target, 0o644)

    assert cli.main(["export", "-o", str(target)]) == 0

    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert json.loads(target.read_text())["count"] == 1


def test_cli_export_keeps_the_old_file_when_writing_fails(cli, monkeypatch, tmp_path):
    from bilinc.cli import main as cli_main

    target = tmp_path / "existing.json"
    target.write_text("previous export")

    def broken_dumps(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(cli_main.json, "dumps", broken_dumps)
    with pytest.raises(RuntimeError):
        cli_main._write_private_json(str(target), {"count": 0})

    assert target.read_text() == "previous export"
    assert [path.name for path in tmp_path.iterdir() if path.name.startswith(".bilinc-export-")] == []


def test_cli_export_does_not_need_fchmod(cli, monkeypatch, tmp_path):
    """Windows before Python 3.13 has no os.fchmod."""
    monkeypatch.delattr(os, "fchmod", raising=False)
    target = tmp_path / "out.json"

    assert cli.main(["export", "-o", str(target)]) == 0
    assert json.loads(target.read_text())["count"] == 1
