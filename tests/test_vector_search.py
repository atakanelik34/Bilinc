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


def test_semantic_search_reuses_corpus_matrix_and_invalidates_on_text_change(monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")
    calls = {"documents": 0, "queries": 0}

    class CountingSemanticModel:
        def encode_document(self, texts, **kwargs):
            calls["documents"] += 1
            return np.asarray([
                [1.0, 0.0] if text.startswith("memory:database") else [0.0, 1.0]
                for text in texts
            ])

        def encode_query(self, texts, **kwargs):
            calls["queries"] += 1
            return np.asarray([[1.0, 0.0]])

    async def scenario():
        monkeypatch.setenv("BILINC_SEMANTIC_MODEL", "test/counting-model")
        monkeypatch.setattr(vector_search, "_load_semantic_model", lambda *_args: CountingSemanticModel())
        backend = SQLiteBackend(str(tmp_path / "semantic-cache.sqlite"))
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
        search.semantic_search("Which database stores state?", top_k=2)
        search.semantic_search("Which database stores state?", top_k=2)
        assert calls == {"documents": 1, "queries": 2}

        allowed = search.semantic_search(
            "Which database stores state?",
            top_k=2,
            allowed_keys={"memory:database"},
        )
        assert allowed[0][0] == 1
        frontend_only = search.semantic_search(
            "Which database stores state?",
            top_k=2,
            allowed_keys={"memory:frontend"},
        )
        assert frontend_only[0][0] == 2
        assert calls == {"documents": 1, "queries": 4}

        await backend.restore(
            MemoryEntry(
                key="memory:database",
                value="SQLite stores durable state.",
                memory_type=MemoryType.SEMANTIC,
            )
        )
        search.semantic_search("Which database stores state?", top_k=2)
        assert calls == {"documents": 2, "queries": 5}

        monkeypatch.setenv("BILINC_SEMANTIC_MODEL_REVISION", "revision-2")
        search.semantic_search("Which database stores state?", top_k=2)
        assert calls == {"documents": 3, "queries": 6}
        await backend.close()

    asyncio.run(scenario())


def test_semantic_document_vectors_are_reused_across_scoped_searches(monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")
    calls = {"documents": 0}

    class SharedSemanticModel:
        def encode_document(self, texts, **kwargs):
            calls["documents"] += 1
            return np.asarray([[1.0, 0.0] for _ in texts])

        def encode_query(self, texts, **kwargs):
            return np.asarray([[1.0, 0.0] for _ in texts])

    async def seed(path):
        backend = SQLiteBackend(str(path))
        await backend.init()
        await backend.restore(
            MemoryEntry(
                key="memory:shared",
                value="A shared source-preserving memory.",
                memory_type=MemoryType.EPISODIC,
            )
        )
        return backend

    async def scenario():
        model_name = f"test/shared-model-{tmp_path.name}"
        monkeypatch.setenv("BILINC_SEMANTIC_MODEL", model_name)
        monkeypatch.setenv("BILINC_SEMANTIC_CACHE_SIZE", "16")
        monkeypatch.setattr(vector_search, "_load_semantic_model", lambda *_args: SharedSemanticModel())
        vector_search._clear_semantic_document_cache()

        first = await seed(tmp_path / "first.sqlite")
        second = await seed(tmp_path / "second.sqlite")
        first_search = HybridSearch(first._get_conn(), VectorStore(first._get_conn()))
        second_search = HybridSearch(second._get_conn(), VectorStore(second._get_conn()))

        first_results = first_search.semantic_search("What is shared?", top_k=1)
        second_results = second_search.semantic_search("What is shared?", top_k=1)
        assert first_results == second_results
        assert calls["documents"] == 1
        assert "A shared source-preserving memory." not in repr(vector_search._semantic_document_cache)

        monkeypatch.setenv("BILINC_SEMANTIC_CACHE_SIZE", "0")
        third = await seed(tmp_path / "third.sqlite")
        third_search = HybridSearch(third._get_conn(), VectorStore(third._get_conn()))
        assert third_search.semantic_search("What is shared?", top_k=1)
        assert calls["documents"] == 2

        monkeypatch.setenv("BILINC_SEMANTIC_CACHE_SIZE", "16")
        fourth = await seed(tmp_path / "fourth.sqlite")
        fourth_search = HybridSearch(fourth._get_conn(), VectorStore(fourth._get_conn()))
        assert fourth_search.semantic_search("What is shared?", top_k=1)
        assert calls["documents"] == 3

        await first.close()
        await second.close()
        await third.close()
        await fourth.close()
        vector_search._clear_semantic_document_cache()

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
