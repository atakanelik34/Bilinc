"""`bilinc wiki`: arguments, exit codes, and where output goes."""

from __future__ import annotations

import argparse
import io

import pytest

from bilinc.client import CloudClient, error_for_response
from tests.test_wiki_export import ENTRIES, transport_for
from tests.wiki_fakes import not_found

EXISTING_COMMANDS = {
    "start", "login", "commit", "recall", "revise", "forget", "confirm", "history", "list", "export",
    "snapshot", "diff", "rollback", "status", "health", "doctor", "quicktest", "mcp", "signup",
}


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    from bilinc.cli import main as cli_main

    state = {"transport": transport_for()}

    def fake_client(api_key=None, base_url="https://bilinc.space", timeout=30.0):
        return CloudClient(api_key="bil_live_example", transport=state["transport"], read_retry_attempts=1)

    monkeypatch.setenv("BILINC_API_KEY", "bil_live_cli_test")
    monkeypatch.setenv("BILINC_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(cli_main, "CloudClient", fake_client)
    cli_main.state = state
    return cli_main


def test_wiki_help_renders(capsys):
    from bilinc.cli.main import main

    with pytest.raises(SystemExit) as caught:
        main(["wiki", "--help"])

    out = capsys.readouterr().out
    assert caught.value.code == 0
    assert "--history" in out and "--prefix" in out and "Obsidian-compatible" in out


@pytest.mark.parametrize("bad", ["101", "-1", "x", "1.5"])
def test_wiki_history_is_bounded(bad, tmp_path, capsys):
    from bilinc.cli.main import main

    with pytest.raises(SystemExit) as caught:
        main(["wiki", str(tmp_path), "--history", bad])

    assert caught.value.code == 2
    assert "--history" in capsys.readouterr().err


def test_wiki_success_prints_one_summary_line_on_stdout(cli, tmp_path, capsys):
    target = tmp_path / "wiki"

    assert cli.main(["wiki", str(target)]) == 0

    captured = capsys.readouterr()
    assert captured.out == f"Wrote {len(ENTRIES)} pages to {target} (removed 0 stale files)\n"
    assert captured.err == ""
    assert (target / "index.md").is_file()


def test_wiki_history_failure_exits_zero_and_names_the_key(cli, tmp_path, capsys):
    cli.state["transport"] = transport_for(history={"solo": [not_found()]})

    assert cli.main(["wiki", str(tmp_path / "wiki")]) == 0

    captured = capsys.readouterr()
    assert captured.out.startswith("Wrote ")
    assert "warning: history unavailable for 1 key: solo" in captured.err


def test_wiki_refusal_exits_one(cli, tmp_path, capsys):
    (tmp_path / "notes.md").write_text("mine")

    assert cli.main(["wiki", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "bilinc: error:" in captured.err and "not a Bilinc wiki folder" in captured.err


def test_wiki_list_failure_exits_one(cli, tmp_path, capsys):
    transport = transport_for()
    transport.list_pages[0] = error_for_response(401, {"error": "invalid_api_key", "message": "Invalid API key"})
    cli.state["transport"] = transport

    assert cli.main(["wiki", str(tmp_path / "wiki")]) == 1

    assert "Invalid API key" in capsys.readouterr().err
    assert not (tmp_path / "wiki").exists()


def test_wiki_passes_prefix_and_history(cli, tmp_path, capsys):
    assert cli.main(["wiki", str(tmp_path / "wiki"), "--prefix", "project:", "--history", "0"]) == 0

    transport = cli.state["transport"]
    assert transport.total_history_calls() == 0
    assert {body.get("prefix") for body in transport.list_bodies()} == {"project:"}


def test_wiki_progress_only_on_a_tty(cli, tmp_path, capsys, monkeypatch):
    class TtyErr(io.StringIO):
        def isatty(self):
            return True

    fake_err = TtyErr()
    monkeypatch.setattr("sys.stderr", fake_err)

    assert cli.main(["wiki", str(tmp_path / "wiki")]) == 0

    assert f"\rhistory {len(ENTRIES)}/{len(ENTRIES)}" in fake_err.getvalue()
    assert capsys.readouterr().out.startswith("Wrote ")


def test_wiki_keyboard_interrupt_exits_130(cli, tmp_path, capsys, monkeypatch):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "export_wiki", interrupted)

    assert cli.main(["wiki", str(tmp_path / "wiki")]) == 130
    assert "cancelled" in capsys.readouterr().err


def test_existing_commands_are_unchanged():
    from bilinc.cli.main import build_parser

    parser = build_parser()
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))

    assert set(subparsers.choices) == EXISTING_COMMANDS | {"wiki"}
