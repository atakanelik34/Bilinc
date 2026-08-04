"""Neutral regression tests for safe hybrid query parsing."""

import asyncio

from bilinc.core.models import MemoryEntry, MemoryType
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
