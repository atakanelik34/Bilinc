"""Tenant isolation of the hosted runtime on PostgreSQL.

The unit tests always run. The integration tests need a disposable PostgreSQL
with pgvector and run only when BILINC_TEST_POSTGRES_DSN is set, for example:

    docker run -d --rm -p 127.0.0.1:55461:5432 -e POSTGRES_PASSWORD=test pgvector/pgvector:pg16
    BILINC_TEST_POSTGRES_DSN=postgresql://postgres:test@127.0.0.1:55461/postgres pytest tests/test_cloud_postgres_tenancy.py
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from bilinc.storage.postgres_tenancy import project_schema, search_path_sql, validate_schema_name

DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
needs_postgres = pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set")


def test_project_schema_is_a_safe_identifier_derived_from_the_uuid():
    project_id = "0f8fad5b-d9cb-469f-a165-70867728950e"
    assert project_schema(project_id) == "bilinc_p_0f8fad5bd9cb469fa16570867728950e"
    assert project_schema(project_id.upper()) == project_schema(project_id)
    with pytest.raises(ValueError):
        project_schema("../../etc")


@pytest.mark.parametrize("bad", ["public", "pg_catalog", 'x"; DROP TABLE t; --', "A_upper", "", "a" * 64, "1abc"])
def test_schema_names_outside_the_safe_pattern_are_rejected(bad):
    with pytest.raises(ValueError):
        validate_schema_name(bad)


def test_search_path_puts_the_tenant_schema_first():
    assert search_path_sql("bilinc_p_abc") == 'SET search_path TO "bilinc_p_abc", public'


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def postgres_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("BILINC_POSTGRES_DSN", DSN or "")
    from bilinc.cloud.runtime import ProjectRuntimeManager

    return ProjectRuntimeManager(tmp_path)


async def _count(sql: str, *args):
    import asyncpg

    conn = await asyncpg.connect(DSN)
    try:
        return await conn.fetchval(sql, *args)
    finally:
        await conn.close()


@needs_postgres
def test_two_projects_never_see_or_overwrite_each_other(postgres_runtime):
    manager = postgres_runtime
    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    async def scenario():
        public_before = await _count(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'bilinc_entries'"
        )
        await manager.commit(a, key="customer.secret", value="A private note")
        await manager.commit(b, key="customer.secret", value="B private note")
        await manager.commit(b, key="only.in.b", value="B only")

        plane_a = await manager.get_plane(a)
        plane_b = await manager.get_plane(b)
        assert (await plane_a.backend.load("customer.secret")).value == "A private note"
        assert (await plane_b.backend.load("customer.secret")).value == "B private note"
        assert await plane_a.backend.load("only.in.b") is None

        recalled_a = await manager.recall(a, query="private note only", profile="balanced", limit=10)
        keys_a = {item["key"]: item["value"] for item in recalled_a["results"]}
        assert keys_a.get("customer.secret") == "A private note"
        assert "only.in.b" not in keys_a
        assert "B private note" not in keys_a.values()

        # Create-only writes are per project: B holding a key doesn't block A.
        await manager.commit(a, key="only.in.b", value="A's own", if_absent=True)
        with pytest.raises(ValueError, match="memory_exists"):
            await manager.commit(b, key="only.in.b", value="again", if_absent=True)

        await manager.forget(a, key="customer.secret", reason="test")
        assert (await plane_b.backend.load("customer.secret")).value == "B private note"

        # Each project has its own schema, its own rows and its own audit chain.
        for project_id, expected_rows in ((a, 1), (b, 2)):
            schema = project_schema(project_id)
            rows = await _count(f'SELECT COUNT(*) FROM "{schema}".bilinc_entries')
            assert rows == expected_rows
            assert await _count(f'SELECT COUNT(*) FROM "{schema}".audit_log') >= 1

        # Nothing was written to shared tables.
        if public_before:
            assert await _count("SELECT COUNT(*) FROM public.bilinc_entries") == 0

        # A fresh manager (process restart) reloads only the project's own beliefs.
        await manager.close()

    _run(scenario())


@needs_postgres
def test_snapshots_and_diffs_only_contain_the_project_itself(postgres_runtime, tmp_path):
    manager = postgres_runtime
    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    async def scenario():
        await manager.commit(a, key="a.one", value=1)
        await manager.commit(b, key="b.one", value=1)
        await manager.commit(b, key="b.two", value=2)
        snap_a = await manager.create_snapshot(a, label="a")
        snap_b = await manager.create_snapshot(b, label="b")
        assert snap_a.total_entries == 1
        assert snap_b.total_entries == 2
        await manager.close()

    _run(scenario())


@needs_postgres
def test_pool_stays_small_per_project(postgres_runtime):
    manager = postgres_runtime
    project = str(uuid.uuid4())

    async def scenario():
        await manager.commit(project, key="k", value="v")
        plane = await manager.get_plane(project)
        assert plane.backend.pool.get_max_size() == 4
        assert plane.backend.schema == project_schema(project)
        await manager.close()

    _run(scenario())


def test_search_path_setting_survives_reset_all_as_the_session_default():
    from bilinc.storage.postgres_tenancy import search_path_setting

    assert search_path_setting("bilinc_p_abc") == "bilinc_p_abc,public"
    with pytest.raises(ValueError):
        search_path_setting("public")


@needs_postgres
def test_released_connections_keep_the_tenant_schema(postgres_runtime):
    manager = postgres_runtime
    project = str(uuid.uuid4())

    async def scenario():
        await manager.commit(project, key="k", value="v")
        plane = await manager.get_plane(project)
        for _ in range(3):
            async with plane.backend.pool.acquire() as conn:
                assert await conn.fetchval("SELECT current_schema()") == project_schema(project)
                await conn.execute("RESET ALL")
            async with plane.backend.pool.acquire() as conn:
                assert await conn.fetchval("SELECT current_schema()") == project_schema(project)
        await manager.close()

    _run(scenario())


@needs_postgres
def test_audit_entries_are_committed_and_visible_to_other_sessions(postgres_runtime):
    manager = postgres_runtime
    project = str(uuid.uuid4())

    async def scenario():
        await manager.commit(project, key="k", value="v")
        await manager.commit(project, key="k", value="v2")
        plane = await manager.get_plane(project)
        assert plane.audit.conn.info.transaction_status.name == "IDLE"
        assert await _count(f'SELECT COUNT(*) FROM "{project_schema(project)}".audit_log') >= 2
        await manager.close()

    _run(scenario())
