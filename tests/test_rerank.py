import asyncio

import pytest

from bilinc.core import rerank
from bilinc.core.models import MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend


class KeywordCrossEncoder:
    """Scores a pair by whether the document contains the word 'postgres'."""

    def __init__(self):
        self.calls = 0

    def predict(self, pairs, **_kwargs):
        self.calls += 1
        return [1.0 if "postgres" in doc.lower() else 0.0 for _query, doc in pairs]


@pytest.fixture(autouse=True)
def _clear_model_cache():
    rerank._clear_model_cache()
    yield
    rerank._clear_model_cache()


def test_rerank_is_off_without_model(monkeypatch):
    monkeypatch.delenv("BILINC_RERANK_MODEL", raising=False)
    order, scores = rerank.rerank_keys("q", ["a", "b"], lambda k: k, limit=2)
    assert order == ["a", "b"] and scores == {}


def test_rerank_reorders_head_and_keeps_tail(monkeypatch):
    monkeypatch.setenv("BILINC_RERANK_MODEL", "fake/cross-encoder")
    monkeypatch.setenv("BILINC_RERANK_DEPTH", "3")
    model = KeywordCrossEncoder()
    monkeypatch.setattr(rerank, "_load_rerank_model", lambda *_args: model)
    texts = {"a": "sqlite", "b": "redis", "c": "postgres", "d": "postgres tail"}
    order, scores = rerank.rerank_keys("which db", ["a", "b", "c", "d"], texts.__getitem__, limit=2)
    assert order == ["c", "a", "b", "d"]  # ties keep fused order; "d" is below the depth
    assert set(scores) == {"a", "b", "c"}


def test_rerank_falls_back_when_model_missing(monkeypatch):
    monkeypatch.setenv("BILINC_RERANK_MODEL", "fake/cross-encoder")
    monkeypatch.setattr(rerank, "_load_rerank_model", lambda *_args: None)
    order, scores = rerank.rerank_keys("q", ["a", "b"], lambda k: k, limit=1)
    assert order == ["a", "b"] and scores == {}


def test_recall_uses_rerank_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("BILINC_RERANK_MODEL", "fake/cross-encoder")
    monkeypatch.setattr(rerank, "_load_rerank_model", lambda *_args: KeywordCrossEncoder())

    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "r.sqlite")), enable_verification=False, enable_audit=False)
        await plane.init()
        await plane.commit("m1", "The team discussed which database to use for the app.", MemoryType.EPISODIC)
        await plane.commit("m2", "We picked Postgres as the database.", MemoryType.EPISODIC)
        await plane.commit("m3", "Database backups run nightly.", MemoryType.EPISODIC)
        return await plane.recall_intelligent("which database did we pick", limit=3)

    results = asyncio.run(go())
    assert results[0]["key"] == "m2"
    assert "rerank_score" in results[0]


def test_failed_model_load_is_logged_and_retried_later(monkeypatch, caplog):
    import sys
    import types

    attempts = []

    class Boom:
        def __init__(self, *args, **kwargs):
            attempts.append(1)
            raise OSError("download interrupted")

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(CrossEncoder=Boom))
    assert rerank._load_rerank_model("m", "cpu", "") is None
    assert rerank._load_rerank_model("m", "cpu", "") is None  # within the retry window: no new attempt
    assert len(attempts) == 1 and "could not be loaded" in caplog.text
    monkeypatch.setattr(rerank, "RETRY_AFTER_SECONDS", 0.0)
    assert rerank._load_rerank_model("m", "cpu", "") is None
    assert len(attempts) == 2


def test_reranked_results_carry_scores_in_result_order(monkeypatch, tmp_path):
    monkeypatch.setenv("BILINC_RERANK_MODEL", "fake/cross-encoder")
    monkeypatch.setattr(rerank, "_load_rerank_model", lambda *_args: KeywordCrossEncoder())

    async def go():
        plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "o.sqlite")), enable_verification=False, enable_audit=False)
        await plane.init()
        await plane.commit("m1", "The team discussed which database to use for the app.", MemoryType.EPISODIC)
        await plane.commit("m2", "We picked Postgres as the database.", MemoryType.EPISODIC)
        await plane.commit("m3", "Database backups run nightly.", MemoryType.EPISODIC)
        return await plane.recall_intelligent("which database did we pick", limit=3)

    results = asyncio.run(go())
    scores = [r["score"] for r in results]
    assert results[0]["key"] == "m2" and scores == sorted(scores, reverse=True)
