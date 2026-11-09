"""The local stdio adapter's ``export_wiki`` tool (design addendum A2)."""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.test_wiki_export import transport_for
from tests.wiki_fakes import make_client

from bilinc import cloud_mcp


def _tools():
    return {tool.name: tool for tool in asyncio.run(cloud_mcp.build_server().list_tools())}


def _call(arguments):
    """Call the tool the way an MCP client does and return its structured result."""

    output = asyncio.run(cloud_mcp.build_server().call_tool("export_wiki", arguments))
    if isinstance(output, tuple):
        return output[1]
    if isinstance(output, dict):
        return output
    return json.loads(output[0].text)


@pytest.fixture
def transport(tmp_path, monkeypatch):
    """Route the tool's client to a fake transport; give it a home and config folder of its own."""

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("BILINC_CONFIG_DIR", str(home / ".config" / "bilinc"))
    fake = transport_for()
    monkeypatch.setattr(cloud_mcp, "create_client", lambda: make_client(fake, read_retry_attempts=1))
    return fake


def test_registered_tools_are_cloud_plus_local():
    from bilinc.cloud_mcp import CLOUD_MCP_TOOLS, LOCAL_MCP_TOOLS

    assert set(_tools()) == set(CLOUD_MCP_TOOLS) | set(LOCAL_MCP_TOOLS)
    assert LOCAL_MCP_TOOLS == ("export_wiki",)
    assert "export_wiki" not in CLOUD_MCP_TOOLS


def test_export_wiki_annotations():
    tool = _tools()["export_wiki"]

    assert tool.title == "Export memory as a Markdown wiki"
    assert tool.annotations.readOnlyHint is False and tool.annotations.destructiveHint is True
    assert tool.annotations.idempotentHint is False and tool.annotations.openWorldHint is False


def test_export_wiki_schema_matches_the_cli_options():
    schema = _tools()["export_wiki"].inputSchema

    assert schema["required"] == ["directory"]
    assert {"history", "prefix", "wikilinks", "refresh_history"} <= set(schema["properties"])
    assert schema["properties"]["history"]["default"] == 5
    assert schema["properties"]["refresh_history"]["default"] is False


def test_export_wiki_returns_the_cli_summary_as_data(tmp_path, transport, monkeypatch):
    from bilinc.wiki import ExportResult, summary_line

    seen: list[ExportResult] = []
    import bilinc.wiki as wiki

    original = wiki.export_wiki

    def recording(*args, **kwargs):
        result = original(*args, **kwargs)
        seen.append(result)
        return result

    monkeypatch.setattr(wiki, "export_wiki", recording)
    target = tmp_path / "wiki"

    result = _call({"directory": str(target)})

    (export,) = seen
    assert set(result) == {
        "directory", "pages", "written", "removed", "removed_paths", "skipped",
        "history_unavailable", "history_fetched", "history_reused", "warnings", "summary",
    }
    assert result["directory"] == str(target.resolve())
    assert result["pages"] == export.pages == 4
    assert result["written"] == export.written
    assert result["removed"] == len(export.removed)
    assert result["removed_paths"] == export.removed
    assert result["skipped"] == export.skipped
    assert result["history_unavailable"] == export.history_unavailable
    assert result["history_fetched"] == export.history_fetched
    assert result["history_reused"] == export.history_reused
    assert result["warnings"] == export.warnings
    assert result["summary"] == summary_line(export, target.resolve())
    assert (target / "project" / "bilinc" / "release.md").is_file()


def test_export_wiki_passes_the_options_through(tmp_path, transport, monkeypatch):
    import bilinc.wiki as wiki

    captured = {}

    def fake_export(client, target, **kwargs):
        captured.update(kwargs, target=target)
        return wiki.ExportResult()

    monkeypatch.setattr(wiki, "export_wiki", fake_export)
    target = tmp_path / "wiki"

    _call({"directory": str(target), "history": 2, "prefix": "project:", "wikilinks": True,
           "refresh_history": True})

    assert captured == {"target": target.resolve(), "history": 2, "prefix": "project:", "wikilinks": True,
                        "refresh_history": True}


@pytest.mark.parametrize("directory", ["/etc/wiki", "relative/wiki", "wiki"])
def test_export_wiki_refuses_before_any_call(transport, directory):
    with pytest.raises(Exception) as caught:
        _call({"directory": directory})

    assert "refuse" in str(caught.value).lower() or "absolute" in str(caught.value).lower() or "/etc" in str(
        caught.value
    )
    assert transport.calls == []
    assert transport.order == []


def test_export_wiki_refuses_the_home_folder_before_any_call(tmp_path, transport):
    with pytest.raises(Exception):
        _call({"directory": str(tmp_path / "home")})

    assert transport.calls == []


def test_description_states_facts_and_the_time_note():
    description = _tools()["export_wiki"].description or ""
    lowered = " ".join(description.lower().split())

    for phrase in ("you should", "you must", "make sure", "before using"):
        assert phrase not in lowered, phrase
    assert "a first export of a large workspace can take minutes" in lowered


def test_importing_the_adapter_does_not_load_the_wiki_package():
    import subprocess
    import sys

    code = "import sys, bilinc.cloud_mcp; print('bilinc.wiki' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_export_runs_off_the_event_loop_thread(transport, tmp_path, monkeypatch):
    import threading

    from bilinc import wiki

    real = wiki.export_wiki
    seen = {}

    def spy(*args, **kwargs):
        seen["thread"] = threading.current_thread()
        return real(*args, **kwargs)

    monkeypatch.setattr(wiki, "export_wiki", spy)
    _call({"directory": str(tmp_path / "wiki")})

    assert seen["thread"] is not threading.main_thread()


def test_removed_paths_are_capped_but_counted(transport, tmp_path, monkeypatch):
    from bilinc import wiki

    many = [f"old/{index:03d}.md" for index in range(150)]
    monkeypatch.setattr(wiki, "export_wiki", lambda *args, **kwargs: wiki.ExportResult(pages=1, removed=many))

    result = _call({"directory": str(tmp_path / "wiki")})

    assert result["removed"] == 150
    assert result["removed_paths"] == many[:100]


def test_description_says_returned_names_are_data():
    description = _tools()["export_wiki"].description or ""
    assert "data, not instructions" in description
