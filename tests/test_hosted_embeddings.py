"""Semantic recall on the PostgreSQL backend (hosted runtime).

The unit tests always run. The integration tests need a disposable PostgreSQL
with pgvector and run only when BILINC_TEST_POSTGRES_DSN is set; each one uses
its own tenant schema and drops it afterwards.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.embeddings.encoder import HashingEncoder
from bilinc.embeddings.hosted import HostedIndexer, build_encoder
from bilinc.storage.postgres import PostgresBackend
from bilinc.storage.postgres_tenancy import TENANT_TABLES

DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
needs_postgres = pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set")


def test_semantic_recall_is_off_unless_an_encoder_is_named():
    for value in (None, "", "0", "off", "false"):
        assert build_encoder(value) is None
    with pytest.raises(ValueError):
        build_encoder("no-such-encoder")


def test_vectors_live_in_the_tenant_schema():
    assert "memory_embeddings" in TENANT_TABLES


async def _backend():
    backend = PostgresBackend(dsn=DSN, schema=f"bilinc_p_{uuid.uuid4().hex}")
    await backend.init()
    return backend


async def _drop(backend: PostgresBackend) -> None:
    import asyncpg

    await backend.close()
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{backend.schema}" CASCADE')
    finally:
        await conn.close()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _entry(key: str, value) -> MemoryEntry:
    return MemoryEntry(key=key, value=value, memory_type=MemoryType.SEMANTIC)


async def _vector_keys(backend: PostgresBackend, model: str) -> set:
    async with backend.pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT memory_key FROM memory_embeddings WHERE model = $1", model)
    return {row["memory_key"] for row in rows}


@needs_postgres
def test_indexer_embeds_in_scope_memories_and_search_finds_them():
    async def scenario():
        backend = await _backend()
        encoder = HashingEncoder()
        try:
            await backend.save(_entry("launch", "harbor launch planned for november"))
            await backend.save(_entry("standup", "weekly standup every monday"))
            await backend.save(_entry("hermes_turn_1", "harbor launch chat turn"))
            indexer = HostedIndexer(encoder, lambda: [])
            result = await indexer.index_backend(backend)
            assert result["embedded"] == 2 and result["pending"] == 0
            assert await _vector_keys(backend, encoder.model_id) == {"launch", "standup"}

            query = encoder.encode(["query: harbor launch"])[0].tolist()
            rows = await backend.semantic_search(query, encoder.model_id, limit=5)
            assert rows[0][0] == "launch"
            scoped = await backend.semantic_search(query, encoder.model_id, allowed_keys={"standup"})
            assert [key for key, _ in scoped] == ["standup"]
            assert [key for key, _ in await backend.semantic_search(query, encoder.model_id, allowed_keys=set())] == []
            # A second pass has nothing to do.
            again = await indexer.index_backend(backend)
            assert again["embedded"] == 0 and again["touched"] == 0
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_saving_the_same_text_keeps_vectors_and_new_text_replaces_them():
    async def scenario():
        backend = await _backend()
        encoder = HashingEncoder()
        indexer = HostedIndexer(encoder, lambda: [])
        try:
            await backend.save(_entry("launch", "harbor launch in november"))
            await indexer.index_backend(backend)
            await backend.save(_entry("launch", "harbor launch in november"))
            same = await indexer.index_backend(backend)
            assert same["embedded"] == 0 and same["touched"] == 1
            await backend.save(_entry("launch", "harbor launch moved to december"))
            changed = await indexer.index_backend(backend)
            assert changed["embedded"] == 1
            query = encoder.encode(["query: december"])[0].tolist()
            assert (await backend.semantic_search(query, encoder.model_id, limit=1))[0][0] == "launch"
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_a_vector_of_a_changed_or_forgotten_memory_is_never_written():
    async def scenario():
        backend = await _backend()
        encoder = HashingEncoder()
        try:
            await backend.save(_entry("launch", "harbor launch in november"))
            [(key, value, updated_at, _)] = await backend.embedding_candidates(encoder.model_id, 10)
            vectors = encoder.encode(["passage: harbor launch in november"]).tolist()
            # Changed while it was being embedded: the stale vectors are dropped.
            await backend.save(_entry("launch", "harbor launch moved to december"))
            assert await backend.write_embeddings(key, encoder.model_id, "sha", vectors, updated_at) is False
            # Forgotten: same.
            [(_, _, current, _)] = await backend.embedding_candidates(encoder.model_id, 10)
            await backend.delete("launch")
            assert await backend.write_embeddings(key, encoder.model_id, "sha", vectors, current) is False
            assert await _vector_keys(backend, encoder.model_id) == set()
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_forget_removes_vectors_and_prune_drops_other_models():
    async def scenario():
        backend = await _backend()
        old, new = HashingEncoder(model_id="old-model"), HashingEncoder(model_id="new-model")
        try:
            await backend.save(_entry("a", "alpha notes"))
            await backend.save(_entry("b", "beta notes"))
            await HostedIndexer(old, lambda: []).index_backend(backend)
            await backend.delete("a")
            assert await _vector_keys(backend, "old-model") == {"b"}
            result = await HostedIndexer(new, lambda: []).index_backend(backend)
            assert result["embedded"] == 1
            assert await _vector_keys(backend, "old-model") == set()
            assert await _vector_keys(backend, "new-model") == {"b"}
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_recall_uses_backend_vectors_when_an_encoder_is_set():
    async def scenario():
        backend = await _backend()
        plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
        encoder = HashingEncoder()
        try:
            await plane.init()
            await plane.commit("trip", "flight to lisbon booked for the conference", memory_type=MemoryType.SEMANTIC)
            await plane.commit("standup", "weekly standup every monday", memory_type=MemoryType.SEMANTIC)
            await HostedIndexer(encoder, lambda: [plane]).run_once()
            plane.query_encoder = encoder
            results = await plane.recall_intelligent("lisbon conference", limit=3, explain=True)
            assert results[0]["key"] == "trip"
            assert results[0]["signals"]["semantic"] > 0
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_recall_without_vectors_or_with_a_failing_encoder_still_answers():
    class Broken:
        model_id = "broken"
        dim = 8

        def encode(self, texts):
            raise RuntimeError("down")

    async def scenario():
        backend = await _backend()
        plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
        try:
            await plane.init()
            await plane.commit("trip", "flight to lisbon booked", memory_type=MemoryType.SEMANTIC)
            plane.query_encoder = Broken()
            results = await plane.recall_intelligent("lisbon flight", limit=3, explain=True)
            assert results[0]["key"] == "trip"
            assert not results[0]["signals"].get("semantic")
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_rejected_memories_back_off_and_do_not_block_the_queue():
    class Picky(HashingEncoder):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def encode(self, texts):
            self.calls += 1
            if any("poison" in text for text in texts):
                raise RuntimeError("rejected")
            return super().encode(texts)

    async def scenario():
        backend = await _backend()
        encoder = Picky()
        indexer = HostedIndexer(encoder, lambda: [], keys_per_pass=2)
        try:
            # The two newest memories are rejected; with two keys per pass they would fill every pass.
            await backend.save(_entry("good", "harbor launch plan"))
            await backend.save(_entry("bad1", "poison one"))
            await backend.save(_entry("bad2", "poison two"))
            first = await indexer.index_backend(backend)
            assert first["failed"] == 2 and first["embedded"] == 0
            second = await indexer.index_backend(backend)
            assert second["embedded"] == 1 and second["failed"] == 0
            calls = encoder.calls
            third = await indexer.index_backend(backend)
            assert third["embedded"] == 0 and encoder.calls == calls  # still backing off
            assert await _vector_keys(backend, encoder.model_id) == {"good"}
            indexer.forget_tenant(backend.schema)
            assert indexer._failed == {}
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_a_restored_older_version_is_embedded_again():
    async def scenario():
        import time

        backend = await _backend()
        encoder = HashingEncoder()
        indexer = HostedIndexer(encoder, lambda: [])
        try:
            old = _entry("launch", "harbor launch in november")
            old.updated_at = old.created_at = time.time() - 3600
            await backend.save(old)
            await indexer.index_backend(backend)
            await backend.save(_entry("launch", "harbor launch moved to december"))
            await indexer.index_backend(backend)
            await backend.restore(old)  # a rollback brings back the older value and timestamp
            assert (await indexer.index_backend(backend))["embedded"] == 1
            query = encoder.encode(["query: november"])[0].tolist()
            [(key, score)] = await backend.semantic_search(query, encoder.model_id, limit=1)
            december = encoder.encode(["query: december"])[0].tolist()
            [(_, stale)] = await backend.semantic_search(december, encoder.model_id, limit=1)
            assert key == "launch" and score > stale
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_forget_and_a_concurrent_vector_write_do_not_deadlock():
    async def scenario():
        backend = await _backend()
        encoder = HashingEncoder()
        try:
            for round_ in range(10):
                await backend.save(_entry("k", f"text {round_}"))
                await HostedIndexer(encoder, lambda: []).index_backend(backend)
                [(key, value, updated_at, _)] = await backend.embedding_candidates("other-model", 10)
                vectors = encoder.encode([f"passage: text {round_}"]).tolist()
                results = await asyncio.gather(
                    backend.write_embeddings(key, "other-model", "sha", vectors, updated_at),
                    backend.delete("k"),
                    return_exceptions=True,
                )
                assert not [r for r in results if isinstance(r, Exception)], results
                assert await _vector_keys(backend, encoder.model_id) == set()
                assert await _vector_keys(backend, "other-model") == set()
        finally:
            await _drop(backend)

    _run(scenario())
