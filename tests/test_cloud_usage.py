import pytest

from bilinc.cloud.usage import evaluate_quota


def test_quota_warns_at_eighty_percent():
    decision = evaluate_quota(used=79, limit=100, requested=1)

    assert decision.allowed
    assert decision.remaining == 20
    assert decision.threshold == "warning_80"


def test_quota_hard_stops_past_limit():
    decision = evaluate_quota(used=100, limit=100, requested=1)

    assert not decision.allowed
    assert decision.reason == "quota_exceeded"
    assert decision.threshold == "hard_stop"


def test_unlimited_quota_allows_usage():
    decision = evaluate_quota(used=1_000_000, limit=None, requested=50)

    assert decision.allowed
    assert decision.remaining is None
    assert decision.reason == "unlimited"


def test_invalid_requested_quantity_rejected():
    with pytest.raises(ValueError):
        evaluate_quota(used=0, limit=10, requested=0)
