"""PostgreSQL integration tests for Bilinc persistence parity."""

from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import pytest
import pytest_asyncio

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.storage.postgres import PostgresBackend


TEST_DSN = os.environ.get("BILINC_TEST_POSTGRES_DSN") or os.environ.get("BILINC_DB_URL")


def _require_postgres_env() -> None:
    if not TEST_DSN:
        pytest.skip("BILINC_TEST_POSTGRES_DSN or BILINC_DB_URL is not set")
    pytest.importorskip("asyncpg")
    pytest.importorskip("pgvector")


@pytest_asyncio.fixture
async def backend():
    _require_postgres_env()
    backend = PostgresBackend(dsn=TEST_DSN)
    await backend.init()
    await _truncate(backend)
    yield backend
    await _truncate(backend)
    await backend.close()


async def _truncate(backend: PostgresBackend) -> None:
    async with backend.pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE bilinc_entries")


@pytest.mark.asyncio
async def test_postgres_init_records_schema_version(backend: PostgresBackend):
    stats = await backend.stats()
    assert stats["schema_version"] == 1
    assert stats["dsn"].startswith("postgresql://")
    assert TEST_DSN not in stats["dsn"]
    parsed = urlparse(TEST_DSN)
    if parsed.username and parsed.password:
        assert f"{parsed.username}:{parsed.password}@" not in stats["dsn"]
        assert f"{parsed.username}:***@" in stats["dsn"]


@pytest.mark.asyncio
async def test_postgres_save_load_delete_roundtrip(backend: PostgresBackend):
    entry = MemoryEntry(key="pg_key", value={"hello": "postgres"}, memory_type=MemoryType.SEMANTIC)
    assert await backend.save(entry) is True

    loaded = await backend.load("pg_key")
    assert loaded is not None
    assert loaded.value == {"hello": "postgres"}

    removed = await backend.delete("pg_key")
    assert removed is True
    assert await backend.load("pg_key") is None


@pytest.mark.asyncio
async def test_postgres_load_by_type(backend: PostgresBackend):
    await backend.save(MemoryEntry(key="ep1", value="v1", memory_type=MemoryType.EPISODIC))
    await backend.save(MemoryEntry(key="ep2", value="v2", memory_type=MemoryType.EPISODIC))
    await backend.save(MemoryEntry(key="sem1", value="v3", memory_type=MemoryType.SEMANTIC))

    episodic = await backend.load_by_type(MemoryType.EPISODIC)
    assert {entry.key for entry in episodic} == {"ep1", "ep2"}


@pytest.mark.asyncio
async def test_postgres_stats_shape_matches_contract(backend: PostgresBackend):
    await backend.save(MemoryEntry(key="stats_sem", value="v1", memory_type=MemoryType.SEMANTIC))
    await backend.save(MemoryEntry(key="stats_epi", value="v2", memory_type=MemoryType.EPISODIC))

    stats = await backend.stats()

    assert stats["total_entries"] == 2
    assert stats["schema_version"] == 1
    assert stats["by_type"]["semantic"] == 1
    assert stats["by_type"]["episodic"] == 1


@pytest.mark.asyncio
async def test_postgres_persistence_across_backend_instances():
    _require_postgres_env()
    backend_a = PostgresBackend(dsn=TEST_DSN)
    await backend_a.init()
    await _truncate(backend_a)
    await backend_a.save(
        MemoryEntry(
            key="cross_backend",
            value={"saved_at": time.time()},
            memory_type=MemoryType.SEMANTIC,
        )
    )
    await backend_a.close()

    backend_b = PostgresBackend(dsn=TEST_DSN)
    await backend_b.init()
    loaded = await backend_b.load("cross_backend")
    assert loaded is not None
    assert loaded.key == "cross_backend"
    await _truncate(backend_b)
    await backend_b.close()
