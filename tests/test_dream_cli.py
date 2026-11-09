"""`bilinc dream start|apply|undo|show`: output and exit codes."""

from __future__ import annotations

import io
import json

import pytest


START = {
    "dream_id": "drm_1",
    "since": "2026-11-02T00:00:00Z",
    "candidate_count": 2,
    "forget_cap": 1,
    "undo_window_days": 7,
    "truncated": False,
    "candidates": [
        {
            "key": "team.deploy_day",
            "memory_type": "semantic",
            "importance": 0.8,
            "source": "claude",
            "updated_at": "2026-11-08T12:00:02.000Z",
            "entry_version": "v3_abc",
            "value": "thursday",
        },
        {
            "key": "team.deploy_time",
            "memory_type": "working",
            "importance": 0.5,
            "source": None,
            "updated_at": "2026-11-07T09:00:00.000Z",
            "entry_version": "v1_def",
            "value": "10:00",
        },
    ],
}

ACTIONS = [
    {
        "op": "forget",
        "key": "team.deploy_time",
        "expected_version": "v1_def",
        "reason": "duplicate of team.deploy_day",
        "evidence_keys": ["team.deploy_day"],
    },
    {
        "op": "confirm",
        "key": "team.deploy_day",
        "expected_version": "v3_abc",
        "reason": "still accurate",
        "evidence_keys": ["team.deploy_day"],
    },
]

APPLY = {
    "dream_id": "drm_1",
    "status": "finished",
    "forgets_reserved": 1,
    "forget_cap": 1,
    "contradictions_left": 0,
    "results": [
        {"n": 1, "key": "team.deploy_time", "op": "forget", "result": "applied", "before_version": "v1_def"},
        {"n": 2, "key": "team.deploy_day", "op": "confirm", "result": "conflict", "error": "version changed"},
    ],
}

UNDO = {
    "dream_id": "drm_1",
    "status": "undone",
    "restored": [
        {"n": 1, "key": "team.deploy_time", "op": "forget", "metadata_restored": False},
        {"n": 3, "key": "team.city", "op": "revise"},
    ],
    "conflicts": [],
    "kept": [{"n": 2, "key": "team.deploy_day"}],
}


class FakeClient:
    instances: list["FakeClient"] = []
    start_result: dict = START
    apply_error: Exception | None = None
    undo_result: dict = UNDO

    def __init__(self, api_key=None, base_url="https://bilinc.space", timeout=30.0):
        self.calls = []
        FakeClient.instances.append(self)

    def dream_start(self, **kwargs):
        self.calls.append(("start", kwargs))
        return FakeClient.start_result

    def dream_apply(self, dream_id, actions, *, report=None):
        self.calls.append(("apply", dream_id, actions, report))
        if FakeClient.apply_error is not None:
            raise FakeClient.apply_error
        return APPLY

    def dream_undo(self, dream_id):
        self.calls.append(("undo", dream_id))
        return FakeClient.undo_result

    def dream_show(self, dream_id):
        self.calls.append(("show", dream_id))
        return {"index": {"dream_id": dream_id, "status": "finished"}, "changes": [{"n": 1}]}


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    from bilinc.cli import main as cli_main

    FakeClient.instances = []
    FakeClient.start_result = START
    FakeClient.apply_error = None
    FakeClient.undo_result = UNDO
    monkeypatch.setenv("BILINC_API_KEY", "bil_live_cli_test")
    monkeypatch.setenv("BILINC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(cli_main, "CloudClient", FakeClient)
    return cli_main


def test_dream_start_prints_summary_and_candidates(cli, capsys):
    assert cli.main(["dream", "start", "--prefix", "team.", "--since", "2026-11-01T00:00:00Z", "--limit", "50"]) == 0
    out = capsys.readouterr().out

    assert "dream drm_1: 2 candidates, forget cap 1, undo window 7 days" in out
    assert "team.deploy_day  [semantic]  2026-11-08 12:00:02  v3_abc" in out
    assert "team.deploy_time  [working]  2026-11-07 09:00:00  v1_def" in out
    assert FakeClient.instances[0].calls == [
        ("start", {"prefix": "team.", "since": "2026-11-01T00:00:00Z", "limit": 50})
    ]


def test_dream_start_json(cli, capsys):
    assert cli.main(["dream", "start", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == START
    assert FakeClient.instances[0].calls == [("start", {"prefix": None, "since": None, "limit": 200})]


def test_dream_start_nothing_changed(cli, capsys):
    FakeClient.start_result = {**START, "dream_id": None, "candidate_count": 0, "candidates": []}

    assert cli.main(["dream", "start"]) == 0
    assert capsys.readouterr().out.strip() == "Nothing changed since 2026-11-02T00:00:00Z; no dream started."


def test_dream_apply_reads_prompt_output_from_file(cli, capsys, tmp_path):
    report = {"summary": "one duplicate removed"}
    path = tmp_path / "actions.json"
    path.write_text(json.dumps({"actions": ACTIONS, "report": report}), encoding="utf-8")

    assert cli.main(["dream", "apply", "drm_1", "--file", str(path)]) == 0
    out = capsys.readouterr().out

    assert FakeClient.instances[0].calls == [("apply", "drm_1", ACTIONS, report)]
    assert "1  forget  team.deploy_time  applied" in out
    assert "2  confirm  team.deploy_day  conflict version changed" in out
    assert "applied 1, conflicts 1, errors 0, skipped 0" in out


def test_dream_apply_reads_bare_list_from_stdin(cli, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(ACTIONS)))

    assert cli.main(["dream", "apply", "drm_1"]) == 0
    assert FakeClient.instances[0].calls == [("apply", "drm_1", ACTIONS, None)]
    assert "applied 1, conflicts 1" in capsys.readouterr().out


@pytest.mark.parametrize("content", ["{not json", '"a string"', '{"report": {}}'])
def test_dream_apply_bad_json_exits_2(cli, capsys, tmp_path, content):
    path = tmp_path / "actions.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(SystemExit) as caught:
        cli.main(["dream", "apply", "drm_1", "--file", str(path)])

    assert caught.value.code == 2
    err = capsys.readouterr().err
    assert "error:" in err and "Traceback" not in err
    assert all(not instance.calls for instance in FakeClient.instances)


def test_dream_apply_partial_failure_prints_rows_then_error_exit_1(cli, capsys, tmp_path):
    from bilinc.client import error_for_response

    error = error_for_response(409, {"error": "forget_cap", "message": "forget cap reached"})
    error.partial = {"results": APPLY["results"][:1], "pages_done": 1}
    FakeClient.apply_error = error
    path = tmp_path / "actions.json"
    path.write_text(json.dumps(ACTIONS), encoding="utf-8")

    assert cli.main(["dream", "apply", "drm_1", "--file", str(path)]) == 1
    captured = capsys.readouterr()

    assert "1  forget  team.deploy_time  applied" in captured.out
    assert "bilinc: error: Bilinc Cloud request failed: forget cap reached" in captured.err
    assert "Traceback" not in captured.err


def test_dream_undo_marks_metadata_not_restored(cli, capsys):
    assert cli.main(["dream", "undo", "drm_1"]) == 0
    out = capsys.readouterr().out

    assert "restored" in out and "kept" in out and "conflicts" in out
    assert "1  forget  team.deploy_time  (metadata not restored)" in out
    revise_line = next(line for line in out.splitlines() if "team.city" in line)
    assert "metadata not restored" not in revise_line
    assert "2  team.deploy_day" in out
    assert FakeClient.instances[0].calls == [("undo", "drm_1")]


def test_dream_undo_partially_undone_exits_0(cli, capsys):
    FakeClient.undo_result = {
        **UNDO,
        "status": "partially_undone",
        "conflicts": [{"n": 2, "key": "team.deploy_day", "reason": "changed after the dream"}],
    }

    assert cli.main(["dream", "undo", "drm_1"]) == 0
    out = capsys.readouterr().out
    assert "partially_undone" in out
    assert "2  team.deploy_day  changed after the dream" in out


def test_dream_undo_json(cli, capsys):
    assert cli.main(["dream", "undo", "drm_1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == UNDO


def test_dream_show_json(cli, capsys):
    assert cli.main(["dream", "show", "drm_1", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["index"]["dream_id"] == "drm_1"
    assert FakeClient.instances[0].calls == [("show", "drm_1")]


def test_dream_help_renders(capsys):
    from bilinc.cli.main import main

    with pytest.raises(SystemExit) as caught:
        main(["dream", "--help"])
    assert caught.value.code == 0
    out = capsys.readouterr().out
    for name in ("start", "apply", "undo", "show"):
        assert name in out

    with pytest.raises(SystemExit) as caught:
        main(["dream", "apply", "--help"])
    assert caught.value.code == 0
    assert "--file" in capsys.readouterr().out


def test_dream_without_subcommand_is_a_usage_error(cli, capsys):
    assert cli.main(["dream"]) == 2
