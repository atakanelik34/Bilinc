"""Neutral regression tests for safe hybrid query parsing."""

import asyncio

import pytest

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core import vector_search
from bilinc.core.vector_search import HybridSearch, VectorStore, expand_query
from bilinc.storage.sqlite import SQLiteBackend


def test_expand_query_is_deterministic_and_ignores_punctuation():
    first = expand_query("What database do we use?")
    second = expand_query("What database do we use?")

    assert first == second
    assert "?" not in first
    assert first.split()[:5] == ["what", "database", "do", "we", "use"]


def test_hybrid_search_handles_natural_question_punctuation(tmp_path):
    async def scenario():
        backend = SQLiteBackend(str(tmp_path / "vector-search.sqlite"))
        await backend.init()
        await backend.restore(
            MemoryEntry(
                key="memory:database",
                value="The service uses PostgreSQL for durable storage.",
                memory_type=MemoryType.SEMANTIC,
            )
        )
        await backend.restore(
            MemoryEntry(
                key="memory:frontend",
                value="The dashboard uses React for the web interface.",
                memory_type=MemoryType.SEMANTIC,
            )
        )

        search = HybridSearch(backend._get_conn(), VectorStore(backend._get_conn()))
        keyword_results = search.keyword_search("Which database do we use?", top_k=5)
        reranked = search.search_with_reranking("Which database do we use?", top_k=5)

        assert keyword_results
        assert reranked
        assert reranked[0][2]["key"] == "memory:database"
        await backend.close()

    asyncio.run(scenario())


def test_hybrid_search_can_restrict_the_candidate_union(tmp_path):
    async def scenario():
        backend = SQLiteBackend(str(tmp_path / "vector-scope.sqlite"))
        await backend.init()
        await backend.restore(
            MemoryEntry(
                key="memory:allowed",
                value="database uses postgres",
                memory_type=MemoryType.SEMANTIC,
            )
        )
        await backend.restore(
            MemoryEntry(
                key="memory:excluded",
                value="database uses sqlite",
                memory_type=MemoryType.EPISODIC,
            )
        )

        search = HybridSearch(backend._get_conn(), VectorStore(backend._get_conn()))
        results = search.search_with_reranking(
            "database uses",
            top_k=10,
            allowed_keys={"memory:allowed"},
        )

        assert results
        assert {metadata["key"] for _, _, metadata in results} == {"memory:allowed"}
        await backend.close()

    asyncio.run(scenario())


def test_semantic_search_is_explicitly_opt_in(monkeypatch, tmp_path):
    async def scenario():
        monkeypatch.delenv("BILINC_SEMANTIC_MODEL", raising=False)
        backend = SQLiteBackend(str(tmp_path / "semantic-search.sqlite"))
        await backend.init()
        search = HybridSearch(backend._get_conn(), VectorStore(backend._get_conn()))

        assert search.semantic_search("a paraphrase query", top_k=5) == []
        await backend.close()

    asyncio.run(scenario())


def test_semantic_search_ranks_by_normalized_local_embeddings(monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")

    class FakeSemanticModel:
        def encode_document(self, texts, **kwargs):
            return np.asarray(
                [
                    [1.0, 0.0] if text.startswith("memory:database") else [0.0, 1.0]
                    for text in texts
                ]
            )

        def encode_query(self, texts, **kwargs):
            assert texts == ["Which database stores state?"]
            return np.asarray([[1.0, 0.0]])

    async def scenario():
        monkeypatch.setenv("BILINC_SEMANTIC_MODEL", "test/local-model")
        monkeypatch.setattr(vector_search, "_load_semantic_model", lambda *_args: FakeSemanticModel())
        backend = SQLiteBackend(str(tmp_path / "semantic-ranking.sqlite"))
        await backend.init()
        await backend.restore(
            MemoryEntry(
                key="memory:database",
                value="PostgreSQL stores durable state.",
                memory_type=MemoryType.SEMANTIC,
            )
        )
        await backend.restore(
            MemoryEntry(
                key="memory:frontend",
                value="React renders the dashboard.",
                memory_type=MemoryType.SEMANTIC,
            )
        )

        search = HybridSearch(backend._get_conn(), VectorStore(backend._get_conn()))
        results = search.semantic_search("Which database stores state?", top_k=2)

        assert results[0][0] == 1
        assert results[0][1] > results[1][1]
        await backend.close()

    asyncio.run(scenario())
