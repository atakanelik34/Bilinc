"""SDK surface for the dream pass: CloudClient.dream_* and commit(if_absent=)."""

from __future__ import annotations

import json

import pytest


class RecordingTransport:
    """Capture outbound SDK calls (with timeout) and replay canned responses in order."""

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


def _client(transport, **kwargs):
    from bilinc import CloudClient

    return CloudClient(api_key="bil_live_example", transport=transport, **kwargs)


def _action(n, op="confirm"):
    action = {
        "op": op,
        "key": f"team.item_{n}",
        "expected_version": f"v{n}",
        "reason": "still accurate",
        "evidence_keys": [f"team.item_{n}"],
    }
    if op == "revise":
        action["new_value"] = f"value {n}"
    return action


def _page_response(actions, start=1, status="open"):
    return {
        "dream_id": "drm_1",
        "status": status,
        "forgets_reserved": 0,
        "forget_cap": 6,
        "contradictions_left": 0,
        "results": [
            {"n": start + i, "key": a["key"], "op": a["op"], "result": "applied"} for i, a in enumerate(actions)
        ],
    }


# --- commit(if_absent=) ------------------------------------------------------


def test_commit_if_absent_sends_flag():
    transport = RecordingTransport({"success": True})
    client = _client(transport)

    client.commit("a", 1, if_absent=True)
    client.commit("a", 1, if_absent=False)

    assert transport.calls[0]["body"]["ifAbsent"] is True
    assert transport.calls[1]["body"]["ifAbsent"] is False


def test_commit_default_payload_unchanged():
    transport = RecordingTransport({"success": True})

    _client(transport).commit("a", 1)

    assert transport.calls[0]["body"] == {
        "key": "a",
        "value": 1,
        "memoryType": "semantic",
        "importance": 1.0,
        "metadata": {},
    }


# --- dream_start ---------------------------------------------------------------


def test_dream_start_posts_route_and_limits():
    from bilinc import BilincValidationError

    response = {"dream_id": "drm_1", "since": "2026-11-02T00:00:00Z", "candidate_count": 0, "candidates": []}
    transport = RecordingTransport(response)
    client = _client(transport)

    assert client.dream_start() == response
    client.dream_start(prefix="team.", since="2026-11-01T00:00:00Z", limit=50, agent="claude")

    first, second = transport.calls
    assert first["method"] == "POST"
    assert first["url"] == "https://bilinc.space/api/cloud/memory/dream/start"
    assert first["body"] == {"limit": 200}
    assert second["body"] == {
        "prefix": "team.",
        "since": "2026-11-01T00:00:00Z",
        "limit": 50,
        "agent": "claude",
    }
    assert "Idempotency-Key" not in first["headers"]

    for bad in (0, 201, True, "5"):
        with pytest.raises(BilincValidationError):
            client.dream_start(limit=bad)
    assert len(transport.calls) == 2


# --- dream_apply ---------------------------------------------------------------


def test_dream_apply_splits_60_actions_into_25_25_10_with_final_last():
    actions = [_action(n) for n in range(60)]
    transport = RecordingTransport(
        _page_response(actions[:25], 1),
        _page_response(actions[25:50], 26),
        _page_response(actions[50:], 51, status="finished"),
    )

    result = _client(transport).dream_apply("drm_1", actions)

    assert [len(call["body"]["actions"]) for call in transport.calls] == [25, 25, 10]
    assert [call["body"]["final"] for call in transport.calls] == [False, False, True]
    assert all(call["body"]["dreamId"] == "drm_1" for call in transport.calls)
    assert all(call["url"].endswith("/api/cloud/memory/dream/apply") for call in transport.calls)
    # Actions go out as given: snake_case fields, no renaming.
    assert transport.calls[0]["body"]["actions"][0] == actions[0]
    assert [row["n"] for row in result["results"]] == list(range(1, 61))
    assert result["status"] == "finished"
    assert result["dream_id"] == "drm_1"
    assert result["forget_cap"] == 6


def test_dream_apply_sends_report_on_last_page_only():
    actions = [_action(n) for n in range(30)]
    transport = RecordingTransport(_page_response(actions[:25]), _page_response(actions[25:], 26))
    report = {"summary": "merged two duplicates"}

    _client(transport).dream_apply("drm_1", actions, report=report)

    assert "report" not in transport.calls[0]["body"]
    assert transport.calls[1]["body"]["report"] == report

    single = RecordingTransport(_page_response(actions[:2]))
    _client(single).dream_apply("drm_1", actions[:2])
    assert "report" not in single.calls[0]["body"]
    assert single.calls[0]["body"]["final"] is True


def test_dream_apply_uses_90s_timeout_and_no_retry():
    from bilinc import BilincRuntimeUnavailableError
    from bilinc.client import error_for_response

    unavailable = error_for_response(503, {"error": "cloud_runtime_unavailable", "message": "busy"})
    assert unavailable.retryable is True
    transport = RecordingTransport(unavailable)

    with pytest.raises(BilincRuntimeUnavailableError):
        _client(transport).dream_apply("drm_1", [_action(1)])

    assert len(transport.calls) == 1
    assert transport.calls[0]["timeout"] == 90.0


def test_dream_apply_partial_failure_exposes_first_page_results():
    from bilinc import BilincConflictError
    from bilinc.client import error_for_response

    actions = [_action(n) for n in range(60)]
    failure = error_for_response(409, {"error": "forget_cap", "message": "forget cap reached"})
    transport = RecordingTransport(_page_response(actions[:25]), failure)

    with pytest.raises(BilincConflictError) as caught:
        _client(transport).dream_apply("drm_1", actions)

    assert len(transport.calls) == 2
    partial = caught.value.partial
    assert partial["pages_done"] == 1
    assert [row["n"] for row in partial["results"]] == list(range(1, 26))


@pytest.mark.parametrize(
    "bad",
    [
        "not a dict",
        {**_action(1), "op": "delete"},
        {**_action(1), "key": 5},
        {**_action(1), "key": ""},
        {**_action(1), "reason": ""},
        {**_action(1), "reason": None},
        {**_action(1), "evidence_keys": []},
        {**_action(1), "evidence_keys": "team.item_1"},
        {**_action(1), "evidence_keys": ["ok", 3]},
        {k: v for k, v in _action(1).items() if k != "expected_version"},
        {k: v for k, v in _action(1, "forget").items() if k != "expected_version"},
        {k: v for k, v in _action(1, "revise").items() if k != "new_value"},
    ],
)
def test_dream_apply_rejects_bad_actions_before_any_request(bad):
    from bilinc import BilincValidationError

    transport = RecordingTransport({})
    # The bad action sits on the second page: nothing at all may be sent.
    actions = [_action(n) for n in range(30)] + [bad]

    with pytest.raises(BilincValidationError):
        _client(transport).dream_apply("drm_1", actions)
    assert transport.calls == []


def test_dream_apply_rejects_empty_actions_and_missing_dream_id():
    from bilinc import BilincValidationError

    transport = RecordingTransport({})
    client = _client(transport)

    with pytest.raises(BilincValidationError):
        client.dream_apply("drm_1", [])
    with pytest.raises(BilincValidationError):
        client.dream_apply("", [_action(1)])
    with pytest.raises(BilincValidationError):
        client.dream_apply("drm_1", [_action(1)], report="text")
    assert transport.calls == []


def test_dream_apply_flag_needs_no_expected_version():
    action = {k: v for k, v in _action(1, "flag").items() if k != "expected_version"}
    transport = RecordingTransport(_page_response([action]))

    _client(transport).dream_apply("drm_1", [action])

    assert transport.calls[0]["body"]["actions"] == [action]


# --- dream_undo / dream_show ------------------------------------------------------


def test_dream_undo_and_show_routes():
    from bilinc import BilincRuntimeUnavailableError
    from bilinc.client import error_for_response

    undo = {"dream_id": "drm_1", "status": "undone", "restored": [], "conflicts": [], "kept": []}
    transport = RecordingTransport(undo, {"index": {}, "changes": []})
    client = _client(transport, read_retry_attempts=1)

    assert client.dream_undo("drm_1") == undo
    assert client.dream_show("drm_1") == {"index": {}, "changes": []}

    undo_call, show_call = transport.calls
    assert undo_call["url"] == "https://bilinc.space/api/cloud/memory/dream/undo"
    assert undo_call["body"] == {"dreamId": "drm_1"}
    assert undo_call["timeout"] == 90.0
    assert show_call["url"] == "https://bilinc.space/api/cloud/memory/dream/show"
    assert show_call["body"] == {"dreamId": "drm_1"}
    assert show_call["timeout"] == 30.0

    # Undo is a write: a retryable failure is raised, never retried.
    failing = RecordingTransport(error_for_response(503, {"error": "cloud_runtime_unavailable"}))
    with pytest.raises(BilincRuntimeUnavailableError):
        _client(failing).dream_undo("drm_1")
    assert len(failing.calls) == 1


def test_dream_show_retries_like_other_reads(monkeypatch):
    from bilinc import client as client_module
    from bilinc.client import error_for_response

    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)
    transport = RecordingTransport(
        error_for_response(503, {"error": "cloud_runtime_unavailable"}),
        {"index": {}, "changes": []},
    )

    assert _client(transport).dream_show("drm_1") == {"index": {}, "changes": []}
    assert len(transport.calls) == 2


def test_default_client_timeout_and_retries_unchanged():
    from bilinc.client import READ_RETRY_ATTEMPTS

    transport = RecordingTransport({"success": True})
    client = _client(transport)

    assert client.timeout == 30.0
    assert client.read_retry_attempts == READ_RETRY_ATTEMPTS == 3
    client.commit("a", 1)
    client.confirm("a")
    assert [call["timeout"] for call in transport.calls] == [30.0, 30.0]


def test_errors_carry_no_partial_by_default():
    from bilinc.client import error_for_response

    assert error_for_response(400, {"error": "invalid_request"}).partial is None


# --- review round 1 ------------------------------------------------------------


def test_dream_apply_rejects_revise_with_null_new_value():
    from bilinc import BilincValidationError

    transport = RecordingTransport({})
    action = {**_action(1, "revise"), "new_value": None}

    with pytest.raises(BilincValidationError):
        _client(transport).dream_apply("drm_1", [action])
    assert transport.calls == []


def test_dream_apply_resends_actions_the_deadline_skipped():
    actions = [_action(n) for n in range(1, 4)]
    first = _page_response(actions, status="applying")
    first["results"][1].update(result="skipped", error="deadline")
    first["results"][2].update(result="skipped", error="deadline")
    second = _page_response(actions[1:], start=4, status="applied")
    transport = RecordingTransport(first, second)

    result = _client(transport).dream_apply("drm_1", actions, report={"notes": "n"})

    assert len(transport.calls) == 2
    assert [a["key"] for a in transport.calls[1]["body"]["actions"]] == ["team.item_2", "team.item_3"]
    assert transport.calls[0]["body"]["final"] is True
    assert transport.calls[1]["body"]["final"] is True
    assert transport.calls[1]["body"]["report"] == {"notes": "n"}
    assert [r["result"] for r in result["results"]] == ["applied", "applied", "applied"]
    assert result["status"] == "applied"


def test_dream_undo_continues_while_the_service_says_undoing():
    paused = {"dream_id": "drm_1", "status": "undoing", "restored": [{"n": 2, "key": "b", "op": "revise"}], "conflicts": [], "kept": []}
    done = {"dream_id": "drm_1", "status": "undone", "restored": [{"n": 1, "key": "a", "op": "forget", "metadata_restored": False}], "conflicts": [], "kept": []}
    transport = RecordingTransport(paused, done)

    result = _client(transport).dream_undo("drm_1")

    assert len(transport.calls) == 2
    assert result["status"] == "undone"
    assert [r["key"] for r in result["restored"]] == ["b", "a"]
