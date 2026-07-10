"""Metric-contract tests for component benchmark helpers."""

import pytest

from benchmarks.longmemeval_bench import evaluate


def test_longmemeval_reports_hit_at_k_not_recall() -> None:
    hit_at_k, ndcg = evaluate([1, 0], {"a", "b"}, ["a", "c"], k=1)

    assert hit_at_k == 0.0
    assert ndcg == 0.0


def test_longmemeval_ndcg_is_normalized_against_all_relevant_items() -> None:
    hit_at_k, ndcg = evaluate([0, 2, 1], {"a", "b"}, ["a", "c", "b"], k=3)

    assert hit_at_k == 1.0
    assert 0.0 <= ndcg <= 1.0
    assert ndcg == pytest.approx(1.0)
