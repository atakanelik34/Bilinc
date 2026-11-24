"""IMP-003: network failures after a request was sent reach SDK callers as Bilinc errors.

urllib wraps only send-time failures in ``URLError``; a timeout or a dropped connection while waiting for or
reading the answer arrived raw. The network is faked by replacing ``client._open``, as the other SDK tests do.
"""
from __future__ import annotations

import email.message
import http.client
import io
import os
import ssl
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from bilinc import client as client_module
from bilinc.client import (
    READ_RETRY_ATTEMPTS,
    BilincCloudError,
    BilincConnectionError,
    BilincRateLimitError,
    BilincRuntimeUnavailableError,
    CloudClient,
    _default_transport,
)

class _Response:
    """Stands in for the object ``_open`` returns; ``read`` returns ``body`` or raises it."""

    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        if isinstance(self._body, BaseException):
            raise self._body
        return self._body


def _http_error(status, body=b"{}"):
    return urllib.error.HTTPError("https://bilinc.space/x", status, "error", email.message.Message(), io.BytesIO(body))


def _patch_open(monkeypatch, *outcomes):
    """Each call to ``_open`` takes the next outcome: an exception is raised, anything else is the body."""
    calls = []

    def fake_open(request, *, timeout, context):
        outcome = outcomes[min(len(calls), len(outcomes) - 1)]
        calls.append(request.full_url)
        if isinstance(outcome, BaseException) and not isinstance(outcome, _ReadFails):
            raise outcome
        return _Response(outcome.exc if isinstance(outcome, _ReadFails) else outcome)

    monkeypatch.setattr(client_module, "_open", fake_open)
    return calls


class _ReadFails(Exception):
    """Marker: the status line arrives, then ``read()`` raises ``exc``."""

    def __init__(self, exc):
        super().__init__(repr(exc))
        self.exc = exc


def _no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(client_module.time, "sleep", sleeps.append)
    return sleeps


def _transport():
    return _default_transport("POST", "https://bilinc.space/x", headers={}, body=b"{}", timeout=1.0)


# 1 ----------------------------------------------------------------------------------------------
RAW = [
    TimeoutError("timed out"),
    ConnectionResetError("reset"),
    http.client.RemoteDisconnected("closed"),
    http.client.IncompleteRead(b""),
    ssl.SSLError("bad record"),
]


@pytest.mark.parametrize("raw", RAW, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("where", ["waiting", "reading"])
def test_raw_failures_after_sending_become_connection_errors(monkeypatch, raw, where):
    _patch_open(monkeypatch, raw if where == "waiting" else _ReadFails(raw))
    with pytest.raises(BilincConnectionError) as caught:
        _transport()
    error = caught.value
    assert (error.code, error.retryable) == ("connection_failed", True)
    assert error.__cause__ is raw
    assert "may have reached Bilinc Cloud" in str(error)


# 2 ----------------------------------------------------------------------------------------------
def test_existing_mappings_are_unchanged(monkeypatch):
    _patch_open(monkeypatch, _http_error(429, b'{"error":"rate_limited"}'))
    with pytest.raises(BilincRateLimitError):
        _transport()

    _patch_open(monkeypatch, urllib.error.URLError("refused"))
    with pytest.raises(BilincConnectionError) as caught:
        _transport()
    assert str(caught.value) == "Bilinc Cloud request failed: refused"
    assert caught.value.code == "connection_failed"

    redirect = urllib.error.HTTPError(
        "https://bilinc.space/x", 302, "Found", email.message.Message(), io.BytesIO(b"")
    )
    redirect.headers["Location"] = "https://elsewhere.example/x"
    _patch_open(monkeypatch, redirect)
    with pytest.raises(BilincConnectionError) as caught:
        _default_transport("GET", "https://bilinc.space/x", headers={}, body=None, timeout=1.0)
    assert caught.value.code == "cross_origin_redirect"


# 3 ----------------------------------------------------------------------------------------------
def test_a_read_that_times_out_once_is_retried(monkeypatch):
    sleeps = _no_sleep(monkeypatch)
    calls = _patch_open(monkeypatch, TimeoutError("timed out"), b'{"ok": true}')
    assert CloudClient(api_key="bil_live_example").status() == {"ok": True}
    assert len(calls) == 2 and len(sleeps) == 1


# 4 ----------------------------------------------------------------------------------------------
def test_a_write_that_times_out_is_not_retried(monkeypatch):
    _no_sleep(monkeypatch)
    calls = _patch_open(monkeypatch, _ReadFails(TimeoutError("timed out")))
    with pytest.raises(BilincConnectionError) as caught:
        CloudClient(api_key="bil_live_example").commit("team.k", "v")
    assert len(calls) == 1
    assert "may have reached Bilinc Cloud" in str(caught.value)


# 5 ----------------------------------------------------------------------------------------------
def _action(n):
    return {"op": "confirm", "key": f"team.item_{n}", "expected_version": f"v{n}",
            "reason": "still accurate", "evidence_keys": [f"team.item_{n}"]}


def test_dream_apply_keeps_its_partial_results_on_a_timeout(monkeypatch):
    import json

    actions = [_action(n) for n in range(30)]                 # two pages: 25 + 5
    first_page = {"dream_id": "drm_1", "status": "open", "forgets_reserved": 0, "forget_cap": 6,
                  "contradictions_left": 0,
                  "results": [{"n": i + 1, "key": a["key"], "op": "confirm", "result": "applied"}
                              for i, a in enumerate(actions[:25])]}
    _patch_open(monkeypatch, json.dumps(first_page).encode(), _ReadFails(TimeoutError("timed out")))
    with pytest.raises(BilincConnectionError) as caught:
        CloudClient(api_key="bil_live_example").dream_apply("drm_1", actions)
    assert caught.value.partial["pages_done"] == 1
    assert len(caught.value.partial["results"]) == 25


# 6 ----------------------------------------------------------------------------------------------
def test_cli_reports_a_timeout_as_an_error_line(monkeypatch, tmp_path, capsys):
    from bilinc.cli.main import main

    sleeps = _no_sleep(monkeypatch)
    monkeypatch.setenv("BILINC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("BILINC_API_KEY", "bil_live_example")
    monkeypatch.delenv("BILINC_BASE_URL", raising=False)
    calls = _patch_open(monkeypatch, TimeoutError("timed out"))
    assert main(["status"]) == 1
    err = capsys.readouterr().err
    assert "bilinc: error:" in err and "Traceback" not in err
    assert len(calls) == READ_RETRY_ATTEMPTS == 3
    assert len(sleeps) == 2


# 7 ----------------------------------------------------------------------------------------------
def test_python_dash_m_bilinc_cli_returns_the_exit_code(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {                                                   # built from scratch: no real key can leak in
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "HOME": str(home),
        "BILINC_CONFIG_DIR": str(home / "bilinc-config"),
        "LANG": "C",
    }
    done = subprocess.run([sys.executable, "-m", "bilinc.cli", "commit", "--key", "k", "--value", "v"],
                          env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 1, done.stderr


# 8 ----------------------------------------------------------------------------------------------
def test_invalid_json_is_still_invalid_response(monkeypatch):
    _patch_open(monkeypatch, b"not json")
    with pytest.raises(BilincCloudError) as caught:
        _transport()
    assert caught.value.code == "invalid_response"
    assert not isinstance(caught.value, BilincConnectionError)


# 9 ----------------------------------------------------------------------------------------------
def test_a_missing_ca_bundle_is_not_a_connection_error(monkeypatch, tmp_path):
    sleeps = _no_sleep(monkeypatch)
    monkeypatch.setenv("BILINC_CA_BUNDLE", str(tmp_path / "missing.pem"))
    client_module._ssl_context_for.cache_clear()
    _patch_open(monkeypatch, b"{}")
    try:
        with pytest.raises(FileNotFoundError):
            CloudClient(api_key="bil_live_example").status()
    finally:
        client_module._ssl_context_for.cache_clear()
    assert sleeps == []


# 10 ---------------------------------------------------------------------------------------------
class _SlowBody(io.BytesIO):
    def read(self, *args):
        raise TimeoutError("timed out reading the error body")


def test_an_error_body_that_times_out_keeps_the_status_mapping(monkeypatch):
    error = urllib.error.HTTPError("https://bilinc.space/x", 503, "down", email.message.Message(), _SlowBody())
    _patch_open(monkeypatch, error)
    with pytest.raises(BilincRuntimeUnavailableError):
        _transport()
