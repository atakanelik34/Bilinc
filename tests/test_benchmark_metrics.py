"""Metric-contract tests for component benchmark helpers."""

import pytest

from benchmarks.longmemeval_bench import evaluate
from benchmarks.metrics import hit_at_k, ndcg_at_k, recall_at_k


def test_longmemeval_reports_hit_at_k_not_recall() -> None:
    hit_at_k, ndcg = evaluate([1, 0], {"a", "b"}, ["a", "c"], k=1)

    assert hit_at_k == 0.0
    assert ndcg == 0.0


def test_longmemeval_ndcg_is_normalized_against_all_relevant_items() -> None:
    hit_at_k, ndcg = evaluate([0, 2, 1], {"a", "b"}, ["a", "c", "b"], k=3)

    assert hit_at_k == 1.0
    assert 0.0 <= ndcg <= 1.0
    assert ndcg == pytest.approx(1.0)


def test_retrieval_metric_contract_distinguishes_hit_from_recall() -> None:
    retrieved = ["a", "noise", "b"]
    relevant = {"a", "b", "c"}

    assert hit_at_k(retrieved, relevant, 1) == 1.0
    assert recall_at_k(retrieved, relevant, 1) == pytest.approx(1 / 3)
    assert recall_at_k(retrieved, relevant, 3) == pytest.approx(2 / 3)


@pytest.mark.parametrize(
    ("retrieved", "relevant", "k"),
    [([], {"a"}, 1), (["noise"], {"a"}, 1), (["a", "b"], {"a", "b"}, 2)],
)
def test_ndcg_is_bounded(retrieved: list[str], relevant: set[str], k: int) -> None:
    assert 0.0 <= ndcg_at_k(retrieved, relevant, k) <= 1.0
