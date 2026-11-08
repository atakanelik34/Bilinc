"""The wiki export through the real SDK client and a scripted transport (no network)."""

from __future__ import annotations

import json
import time

import pytest

from bilinc import client as client_module
from bilinc.client import BilincAuthError, error_for_response
from bilinc.wiki import export_wiki
from tests.test_wiki_export import FIRST, history_payload, public_entry
from tests.wiki_fakes import RoutedTransport, auth_error, list_page, make_client, rate_limited, unavailable


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    def fail(seconds):
        raise AssertionError(f"real sleep of {seconds}s")

    monkeypatch.setattr(time, "sleep", fail)
    monkeypatch.setattr(client_module.time, "sleep", fail)


def entries(count):
    return [public_entry(f"bulk:item{index:03d}", f"value {index}", minute=index % 60) for index in range(count)]


def paged(items, size=100):
    chunks = [items[i : i + size] for i in range(0, len(items), size)]
    return [list_page(chunk, f"c{n + 1}" if n + 1 < len(chunks) else None) for n, chunk in enumerate(chunks)]


def export(target, transport, sleeps=None, **kwargs):
    recorded = [] if sleeps is None else sleeps
    return export_wiki(make_client(transport), target, clock=lambda: FIRST, sleep=recorded.append, **kwargs)


def test_three_list_pages_are_all_exported(tmp_path):
    items = entries(250)
    transport = RoutedTransport(paged(items))

    result = export(tmp_path, transport)

    assert result.pages == 250
    assert [body.get("cursor") for body in transport.list_bodies()] == [None, "c1", "c2"]
    assert {body["limit"] for body in transport.list_bodies()} == {100}
    assert {body["values"] for body in transport.list_bodies()} == {"full"}
    assert transport.total_history_calls() == 250
    assert transport.max_concurrency <= 4
    manifest = json.loads((tmp_path / ".bilinc-wiki.json").read_text())
    assert len(manifest["keys"]) == 250
    assert (tmp_path / "bulk" / "item249.md").is_file()


def test_rate_limit_then_success(tmp_path):
    items = entries(3)
    key = items[1]["key"]
    transport = RoutedTransport(
        paged(items),
        {key: [rate_limited(retry_after=1), rate_limited(retry_after=1), history_payload(key)]},
    )
    sleeps = []

    result = export(tmp_path, transport, sleeps)

    assert sleeps == [1, 1]
    assert transport.history_calls(key) == 3
    assert result.history_unavailable == []
    assert "- update · 2026-11-08 12:05:00 UTC" in (tmp_path / "bulk" / "item001.md").read_text()


def test_partial_history_failure_still_writes_every_page(tmp_path):
    items = entries(5)
    key = items[2]["key"]
    transport = RoutedTransport(paged(items), {key: [unavailable()]})
    sleeps = []

    result = export(tmp_path, transport, sleeps)

    assert result.pages == 5
    assert result.history_unavailable == [key]
    assert sleeps == [1.0, 2.0, 4.0]
    assert transport.history_calls(key) == 4
    assert "History unavailable." in (tmp_path / "bulk" / "item002.md").read_text()
    assert "History unavailable." not in (tmp_path / "bulk" / "item001.md").read_text()


def test_auth_error_on_list_writes_nothing(tmp_path):
    transport = RoutedTransport([auth_error()])
    target = tmp_path / "wiki"

    with pytest.raises(BilincAuthError):
        export(target, transport)

    assert not target.exists()
    assert transport.total_history_calls() == 0


def test_auth_error_on_history_writes_nothing(tmp_path):
    items = entries(8)
    transport = RoutedTransport(paged(items), {items[5]["key"]: [auth_error()]})
    target = tmp_path / "wiki"

    with pytest.raises(BilincAuthError):
        export(target, transport)

    assert not target.exists()


def test_response_too_large_shrinks_the_list_pages(tmp_path):
    items = entries(30)
    inner = RoutedTransport(paged(items, size=10))
    too_large = error_for_response(
        400, {"error": "invalid_request", "details": {"reason": "response_too_large"}}
    )

    def transport(method, url, *, headers, body, timeout):
        payload = json.loads(body.decode("utf-8"))
        if url.endswith("/memory/list") and payload["limit"] == 100:
            raise too_large
        return inner(method, url, headers=headers, body=body, timeout=timeout)

    result = export(tmp_path, transport, history=0)

    assert result.pages == 30
    assert {body["limit"] for body in inner.list_bodies()} == {10}
