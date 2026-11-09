"""List and history fetching with one bounded retry layer (``bilinc.wiki.fetch``)."""

from __future__ import annotations

import threading
import time

import pytest

import bilinc.client
from bilinc.client import (
    BilincApiKeyRequired,
    BilincAuthError,
    BilincCloudError,
    BilincEntitlementError,
    BilincPaymentRequiredError,
)
from bilinc.wiki.fetch import (
    BACKOFF,
    FATAL_ERRORS,
    MAX_RETRIES,
    RETRY_AFTER_CAP,
    HistoryAbort,
    HistoryCancelled,
    fetch_entries,
    fetch_histories,
)
from bilinc.wiki.render import HISTORY_UNAVAILABLE
from tests.wiki_fakes import (
    RoutedTransport,
    auth_error,
    connection_error,
    entitlement_error,
    list_page,
    make_client,
    not_found,
    payment_required,
    rate_limited,
    unavailable,
)

WAIT = 10  # seconds a blocked fake waits before the test gives up


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    def fail(seconds):
        pytest.fail(f"real time.sleep({seconds}) called")

    monkeypatch.setattr(time, "sleep", fail)
    monkeypatch.setattr(bilinc.client.time, "sleep", fail)


def no_sleep(seconds):
    pytest.fail(f"injected sleep({seconds}) called")


def ok(key, *entries):
    return {"key": key, "entries": list(entries)}


# --- constants -------------------------------------------------------------------


def test_constants():
    assert MAX_RETRIES == 3
    assert RETRY_AFTER_CAP == 60.0
    assert BACKOFF == (1.0, 2.0, 4.0)
    assert FATAL_ERRORS == (
        BilincAuthError,
        BilincEntitlementError,
        BilincPaymentRequiredError,
        BilincApiKeyRequired,
    )


# --- fetch_entries -----------------------------------------------------------------


def test_fetch_entries_sorted_and_full_values():
    transport = RoutedTransport(
        [
            list_page([{"key": "zeta", "value": 1}, {"key": "alpha", "value": "a"}], "c1"),
            list_page([{"key": "mid", "value": {"x": 1}}]),
        ]
    )
    entries = fetch_entries(make_client(transport), prefix="team ")
    assert [entry["key"] for entry in entries] == ["alpha", "mid", "zeta"]
    bodies = transport.list_bodies()
    assert len(bodies) == 2
    assert all(body["values"] == "full" and body["prefix"] == "team " for body in bodies)
    assert bodies[1]["cursor"] == "c1"


def test_fetch_entries_without_prefix_sends_none():
    transport = RoutedTransport([list_page([])])
    assert fetch_entries(make_client(transport), prefix=None) == []
    assert "prefix" not in transport.list_bodies()[0]


@pytest.mark.parametrize(
    "entries",
    [
        [{"key": "a"}, {"key": "b"}, {"key": "a"}],
        [{"key": "a"}, {"value": 1}],
        [{"key": "a"}, "b"],
    ],
)
def test_fetch_entries_rejects_duplicate_or_malformed_entries(entries):
    transport = RoutedTransport([list_page(entries)])
    with pytest.raises(BilincCloudError) as info:
        fetch_entries(make_client(transport), prefix=None)
    assert info.value.code == "invalid_response"


def test_fetch_entries_propagates_list_errors():
    transport = RoutedTransport([list_page([{"key": "a"}], "c1"), auth_error()])
    with pytest.raises(BilincAuthError):
        fetch_entries(make_client(transport), prefix=None)


# --- retry layer ---------------------------------------------------------------------


def test_history_uses_single_retry_layer():
    transport = RoutedTransport([], {"k": [rate_limited(retry_after=2)] * 3 + [ok("k")]})
    sleeps = []
    client = make_client(transport)
    out = fetch_histories(client, ["k"], limit=5, sleep=sleeps.append)
    assert transport.history_calls("k") == 4
    assert sleeps == [2, 2, 2]
    assert out["k"]["entries"] == []
    assert client.read_retry_attempts == bilinc.client.READ_RETRY_ATTEMPTS


def test_history_request_body():
    transport = RoutedTransport([], {"k": [ok("k")]})
    fetch_histories(make_client(transport), ["k"], limit=7, sleep=no_sleep)
    assert transport.history_bodies() == [{"key": "k", "limit": 7, "values": "full"}]


def test_retry_after_is_capped():
    transport = RoutedTransport([], {"k": [rate_limited(retry_after=600)] * 2 + [ok("k")]})
    sleeps = []
    fetch_histories(make_client(transport), ["k"], limit=5, sleep=sleeps.append)
    assert sleeps == [60.0, 60.0]


def test_zero_retry_after_is_honoured():
    transport = RoutedTransport([], {"k": [rate_limited(retry_after=0)] + [ok("k")]})
    sleeps = []
    fetch_histories(make_client(transport), ["k"], limit=5, sleep=sleeps.append)
    assert sleeps == [0]


def test_fallback_backoff_without_retry_after():
    transport = RoutedTransport([], {"k": [unavailable()]})
    sleeps = []
    out = fetch_histories(make_client(transport), ["k"], limit=5, sleep=sleeps.append)
    assert sleeps == [1.0, 2.0, 4.0]
    assert out["k"] is HISTORY_UNAVAILABLE
    assert transport.history_calls("k") == 4


def test_connection_errors_are_retried_then_recover():
    transport = RoutedTransport(
        [], {"k": [connection_error(), connection_error(), ok("k", {"op": "x"})]}
    )
    sleeps = []
    out = fetch_histories(make_client(transport), ["k"], limit=5, sleep=sleeps.append)
    assert sleeps == [1.0, 2.0]
    assert out["k"] == ok("k", {"op": "x"})
    assert transport.history_calls("k") == 3


def test_non_retryable_error_marks_unavailable_without_retry():
    transport = RoutedTransport([], {"k": [not_found()], "j": [ok("j")]})
    out = fetch_histories(make_client(transport), ["k", "j"], limit=5, sleep=no_sleep)
    assert out["k"] is HISTORY_UNAVAILABLE
    assert out["j"] == ok("j")
    assert transport.history_calls("k") == 1


def test_non_object_payload_marks_unavailable():
    transport = RoutedTransport([], {"k": [["not", "a", "dict"]]})
    out = fetch_histories(make_client(transport), ["k"], limit=5, sleep=no_sleep)
    assert out["k"] is HISTORY_UNAVAILABLE


@pytest.mark.parametrize("factory", [auth_error, entitlement_error, payment_required])
def test_fatal_error_aborts(factory):
    transport = RoutedTransport([], {"b": [factory()]})
    with pytest.raises(HistoryAbort) as info:
        fetch_histories(make_client(transport), ["a", "b", "c"], limit=5, sleep=no_sleep)
    assert isinstance(info.value.error, FATAL_ERRORS)
    assert isinstance(info.value.__cause__, FATAL_ERRORS)
    assert transport.history_calls("b") == 1


def test_fatal_error_cancels_pending_work():
    keys = [f"k{index:02d}" for index in range(10)]
    transport = RoutedTransport([], {"k01": [auth_error()]})
    with pytest.raises(HistoryAbort):
        fetch_histories(make_client(transport), keys, limit=5, sleep=no_sleep, max_workers=1)
    assert transport.total_history_calls() == 2


def test_fatal_error_wakes_retry_waits():
    started = threading.Event()

    def on_history(key):
        if key == "fatal":
            assert started.wait(WAIT)

    transport = RoutedTransport(
        [], {"slow": [rate_limited(retry_after=50)], "fatal": [auth_error()]}, on_history=on_history
    )

    class SignallingStop(threading.Event):
        def wait(self, timeout=None):
            started.set()
            return super().wait(timeout)

    stop = SignallingStop()
    begin = time.monotonic()
    with pytest.raises(HistoryAbort):
        fetch_histories(
            make_client(transport), ["slow", "fatal"], limit=5, sleep=no_sleep, stop=stop
        )
    assert time.monotonic() - begin < WAIT
    assert stop.is_set()


# --- pool -------------------------------------------------------------------------------


def test_at_most_four_in_flight():
    barrier = threading.Barrier(4, timeout=WAIT)
    transport = RoutedTransport([], on_history=lambda key: barrier.wait())
    keys = [f"k{index:02d}" for index in range(12)]
    out = fetch_histories(make_client(transport), keys, limit=5, sleep=no_sleep, max_workers=4)
    assert transport.max_concurrency == 4
    assert list(out) == keys


def test_max_workers_is_capped_at_four():
    barrier = threading.Barrier(4, timeout=WAIT)
    transport = RoutedTransport([], on_history=lambda key: barrier.wait())
    keys = [f"k{index:02d}" for index in range(8)]
    fetch_histories(make_client(transport), keys, limit=5, sleep=no_sleep, max_workers=16)
    assert transport.max_concurrency == 4


def test_result_independent_of_completion_order():
    keys = ["a", "b", "c", "d"]
    scripts = {key: [ok(key, {"op": key})] for key in keys}
    sequential = fetch_histories(
        make_client(RoutedTransport([], scripts)), keys, limit=5, sleep=no_sleep, max_workers=1
    )

    condition = threading.Condition()
    finished: list[str] = []

    def release_in_reverse(key):
        later = keys[keys.index(key) + 1 :]
        with condition:
            assert condition.wait_for(lambda: all(other in finished for other in later), WAIT)
            finished.append(key)
            condition.notify_all()

    transport = RoutedTransport([], scripts, on_history=release_in_reverse)
    parallel = fetch_histories(make_client(transport), keys, limit=5, sleep=no_sleep, max_workers=4)
    assert transport.completed == ["d", "c", "b", "a"]
    assert parallel == sequential
    assert list(parallel) == list(sequential) == keys


def test_empty_keys():
    transport = RoutedTransport([])
    progress = []
    assert (
        fetch_histories(
            make_client(transport),
            [],
            limit=5,
            sleep=no_sleep,
            progress=lambda *a: progress.append(a),
        )
        == {}
    )
    assert transport.calls == []


def test_progress_reports_each_key():
    keys = [f"k{index}" for index in range(6)]
    transport = RoutedTransport([], {"k2": [not_found()]})
    progress = []
    fetch_histories(
        make_client(transport),
        keys,
        limit=5,
        sleep=no_sleep,
        progress=lambda done, total: progress.append((done, total)),
    )
    assert progress == [(index, 6) for index in range(1, 7)]


# --- interrupts -------------------------------------------------------------------------


class StopOnWait(threading.Event):
    """A stop event that is set by the first retry wait, as Ctrl-C would."""

    def __init__(self):
        super().__init__()
        self.waits = []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        self.set()
        return super().wait(0)


def test_stop_event_cancels_pending():
    keys = [f"k{index}" for index in range(8)]
    transport = RoutedTransport([], {"k0": [rate_limited(retry_after=5)]})
    stop = StopOnWait()
    with pytest.raises(HistoryCancelled):
        fetch_histories(
            make_client(transport), keys, limit=5, sleep=no_sleep, max_workers=1, stop=stop
        )
    assert stop.waits == [5]
    assert transport.total_history_calls() == 1


def test_stop_already_set_makes_no_requests():
    stop = threading.Event()
    stop.set()
    transport = RoutedTransport([])
    with pytest.raises(HistoryCancelled):
        fetch_histories(make_client(transport), ["a", "b"], limit=5, sleep=no_sleep, stop=stop)
    assert transport.calls == []


def test_stop_wait_used_instead_of_sleep():
    stop = threading.Event()
    waits = []
    original = stop.wait

    def recording_wait(timeout=None):
        waits.append(timeout)
        return original(0)

    stop.wait = recording_wait
    transport = RoutedTransport([], {"k": [unavailable(), ok("k")]})
    out = fetch_histories(make_client(transport), ["k"], limit=5, sleep=no_sleep, stop=stop)
    assert waits == [1.0]
    assert out["k"] == ok("k")
