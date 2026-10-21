"""Full-text recall on the PostgreSQL backend (hosted runtime).

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
from bilinc.storage.postgres import (
    FTS_MAX_QUERY_TERMS,
    FTS_METADATA_FIELDS,
    PostgresBackend,
    fts_document,
    fts_or_query,
)

DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
needs_postgres = pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set")


def test_fts_document_decodes_values_and_keeps_only_allowlisted_metadata():
    text = fts_document(
        "program:hasat",
        {"title": "Girişimci yarışması", "where": ["İstanbul", 2026]},
        {"timestamp": "2026-10-07", "internal_note": "never searchable"},
    )
    for expected in ("program:hasat", "Girişimci", "İstanbul", "2026", "2026-10-07", "title"):
        assert expected in text
    assert "never searchable" not in text
    assert "\\u" not in text


def test_fts_metadata_allowlist_matches_lexical_recall():
    assert FTS_METADATA_FIELDS == StatePlane.LEXICAL_RECALL_METADATA_FIELDS


def test_fts_or_query_ors_distinct_terms_and_carries_no_query_syntax():
    assert fts_or_query("Can't find 'plan' | plan & !draft_v2 (now)") == "Can | t | find | plan | draft | v2 | now"
    assert fts_or_query("!!! ...") == ""
    many = " ".join(f"term{i}" for i in range(FTS_MAX_QUERY_TERMS + 10))
    assert len(fts_or_query(many).split(" | ")) == FTS_MAX_QUERY_TERMS


def test_pg_fts_query_text_drops_stopwords_and_keeps_original_case():
    plane = StatePlane.__new__(StatePlane)
    assert plane._pg_fts_query_text("What is the İstanbul plan?") == "İstanbul plan"
    assert plane._pg_fts_query_text("Hasat başvurusu ne zaman gönderildi?") == "Hasat başvurusu zaman gönderildi"
    # A query made only of stopwords is kept rather than emptied.
    assert plane._pg_fts_query_text("what is the") == "what is the"


def test_pg_fts_ranking_is_skipped_for_backends_without_async_full_text():
    class SyncBackend:
        def fts_search(self, query, limit=10):
            raise AssertionError("must not be called")

    plane = StatePlane.__new__(StatePlane)
    plane.backend = SyncBackend()
    assert asyncio.new_event_loop().run_until_complete(plane._rank_pg_fts_keys("anything", top_k=5)) == []


async def _backend():
    schema = f"bilinc_p_{uuid.uuid4().hex}"
    backend = PostgresBackend(dsn=DSN, schema=schema)
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


def _entry(key: str, value, **kwargs) -> MemoryEntry:
    return MemoryEntry(key=key, value=value, memory_type=MemoryType.SEMANTIC, **kwargs)


@needs_postgres
def test_fts_search_orders_best_match_first():
    async def scenario():
        backend = await _backend()
        try:
            await backend.save(_entry("weak", "release notes"))
            await backend.save(_entry("strong", "release version release version release"))
            await backend.save(_entry("unrelated", "weekly stand-up on Monday"))
            rows = await backend.fts_search("release version", limit=5)
            assert [key for _, key, _ in rows] == ["strong", "weak"]
            assert rows[0][2] > rows[1][2]
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_fts_search_finds_turkish_text_although_value_is_stored_escaped():
    async def scenario():
        backend = await _backend()
        try:
            await backend.save(_entry("program:hasat", "Girişimci yarışması, Teknopark İstanbul"))
            async with backend.pool.acquire() as conn:
                raw = await conn.fetchval("SELECT value FROM bilinc_entries WHERE key = 'program:hasat'")
            assert "\\u" in raw  # stored with JSON escapes, as before schema v2
            for query in ("girişimci", "İstanbul", "ISTANBUL", "Yarışması"):
                assert [key for _, key, _ in await backend.fts_search(query)] == ["program:hasat"], query
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_fts_search_respects_allowed_keys():
    async def scenario():
        backend = await _backend()
        try:
            await backend.save(_entry("a", "launch date"))
            await backend.save(_entry("b", "launch date launch"))
            rows = await backend.fts_search("launch", allowed_keys={"a"})
            assert [key for _, key, _ in rows] == ["a"]
            assert await backend.fts_search("launch", allowed_keys=set()) == []
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_schema_v2_backfills_rows_written_before_it():
    async def scenario():
        backend = await _backend()
        try:
            await backend.save(_entry("legacy", "written by an older runtime"))
            async with backend.pool.acquire() as conn:
                await conn.execute("UPDATE bilinc_entries SET tsv = NULL")
            await backend.close()

            reopened = PostgresBackend(dsn=DSN, schema=backend.schema)
            await reopened.init()
            async with reopened.pool.acquire() as conn:
                assert await conn.fetchval("SELECT COUNT(*) FROM bilinc_entries WHERE tsv IS NULL") == 0
                assert await conn.fetchval("SELECT MAX(version) FROM schema_version") == 2
            assert [key for _, key, _ in await reopened.fts_search("older runtime")] == ["legacy"]
            backend.pool = reopened.pool
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_rows_saved_by_an_older_runtime_are_rebuilt_on_the_next_load():
    async def scenario():
        backend = await _backend()
        try:
            await backend.save(_entry("launch", "Harbor launches on Nov 12"))
            # A rolled-back runtime updates value and updated_at but not tsv.
            async with backend.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE bilinc_entries SET value = $1, updated_at = updated_at + 60 WHERE key = 'launch'",
                    '"Harbor launches in December"',
                )
            await backend.close()

            reopened = PostgresBackend(dsn=DSN, schema=backend.schema)
            await reopened.init()
            assert await reopened.fts_search("Nov") == []
            assert [key for _, key, _ in await reopened.fts_search("December")] == ["launch"]
            backend.pool = reopened.pool
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_save_keeps_the_index_current():
    async def scenario():
        backend = await _backend()
        try:
            await backend.save(_entry("launch", "Harbor launches on Nov 12"))
            assert [key for _, key, _ in await backend.fts_search("Nov 12")] == ["launch"]
            await backend.save(_entry("launch", "Harbor launches in December"))
            assert await backend.fts_search("Nov") == []
            assert [key for _, key, _ in await backend.fts_search("December")] == ["launch"]
        finally:
            await _drop(backend)

    _run(scenario())


@needs_postgres
def test_recall_intelligent_uses_pg_fts_in_postgres_mode():
    async def scenario():
        backend = await _backend()
        plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
        try:
            await plane.init()
            await plane.commit("program:hasat", "Girişimci yarışması başvurusu gönderildi", memory_type=MemoryType.SEMANTIC)
            await plane.commit("weekly:standup", "Stand-up every Monday at 10:00", memory_type=MemoryType.SEMANTIC)
            results = await plane.recall_intelligent("Girişimci başvurusu", limit=3, explain=True)
            assert results[0]["key"] == "program:hasat"
            assert results[0]["signals"]["hybrid"] > 0
            # Hosted recall has no vector channel and must not say it does.
            reasons = " ".join(results[0]["why_retrieved"])
            assert "full-text match" in reasons
            assert "vector" not in reasons
        finally:
            await _drop(backend)

    _run(scenario())
