"""Additive SDK changes for the wiki export: Retry-After and per-client read retries."""

from __future__ import annotations

import dataclasses
import email.message
import io
import urllib.error

import pytest

from bilinc import client as client_module
from bilinc.client import (
    READ_RETRY_ATTEMPTS,
    BilincRateLimitError,
    BilincRuntimeUnavailableError,
    BilincValidationError,
    CloudClient,
    _default_transport,
    error_for_response,
)


def _http_error(status, headers, body=b'{"error":"rate_limited"}'):
    message = email.message.Message()
    for name, value in headers.items():
        message[name] = value
    return urllib.error.HTTPError("https://bilinc.space/x", status, "error", message, io.BytesIO(body))


@pytest.mark.parametrize(
    "header,expected",
    [
        ("7", 7.0),
        ("0", 0.0),
        ("2.5", 2.5),
        ("-1", None),
        ("nan", None),
        ("inf", None),
        ("Wed, 21 Oct 2015 07:28:00 GMT", None),
        (None, None),
    ],
)
def test_default_transport_parses_retry_after(monkeypatch, header, expected):
    headers = {"Retry-After": header} if header is not None else {}

    def fake_urlopen(request, *, timeout, context):
        raise _http_error(429, headers)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(BilincRateLimitError) as caught:
        _default_transport("POST", "https://bilinc.space/x", headers={}, body=b"{}", timeout=1.0)

    assert caught.value.retry_after == expected


def test_default_client_retry_behaviour_unchanged(monkeypatch):
    sleeps = []
    monkeypatch.setattr(client_module.time, "sleep", sleeps.append)
    calls = []

    def transport(method, url, *, headers, body, timeout):
        calls.append(url)
        raise error_for_response(503, {"error": "cloud_runtime_unavailable", "message": "down"})

    client = CloudClient(api_key="bil_live_example", transport=transport)

    with pytest.raises(BilincRuntimeUnavailableError) as caught:
        client.history("team.deploy_day")

    assert READ_RETRY_ATTEMPTS == 3
    assert len(calls) == 3
    assert sleeps == [0.25, 0.5]
    error = caught.value
    assert str(error) == "Bilinc Cloud request failed: down"
    assert (error.code, error.status, error.retryable, error.retry_after) == (
        "cloud_runtime_unavailable",
        503,
        True,
        None,
    )


def test_read_retry_attempts_one_makes_a_single_call(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: pytest.fail("no sleep expected"))
    calls = []

    def transport(method, url, *, headers, body, timeout):
        calls.append(url)
        raise error_for_response(429, {"error": "rate_limited"})

    client = dataclasses.replace(CloudClient(api_key="bil_live_example", transport=transport), read_retry_attempts=1)

    with pytest.raises(BilincRateLimitError):
        client.history("k")

    assert len(calls) == 1


@pytest.mark.parametrize("attempts", [0, -1, True, 1.5])
def test_read_retry_attempts_must_be_a_positive_integer(attempts):
    with pytest.raises(BilincValidationError):
        CloudClient(api_key="bil_live_example", read_retry_attempts=attempts)


def test_error_for_response_keeps_positional_signature():
    error = error_for_response(429, {"error": "rate_limited"})

    assert isinstance(error, BilincRateLimitError)
    assert error.retry_after is None
    assert error_for_response(429, {}, retry_after="3").retry_after == 3.0
