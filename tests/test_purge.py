"""Purging: forget(purge=True) and workspace purge on the hosted runtime.

The audit-chain tests run on SQLite. The Postgres tests need a disposable
PostgreSQL with pgvector and run only when BILINC_TEST_POSTGRES_DSN is set.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import uuid

import pytest

from bilinc.core.audit import AuditTrail, OpType

DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
needs_postgres = pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set")
PRIVATE = "Harbor launch moved to the 12th; call Dana on her private line"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _trail(tmp_path) -> AuditTrail:
    trail = AuditTrail(str(tmp_path / "audit.db"))
    _run(trail.init())
    return trail


def test_chain_verifies_after_a_purge_and_values_are_gone(tmp_path):
    trail = _trail(tmp_path)
    trail.log(OpType.CREATE, "plan", after_value={"value": PRIVATE})
    trail.log(OpType.CREATE, "other", after_value={"value": "kept"})
    trail.log(OpType.UPDATE, "plan", before_value={"value": PRIVATE}, after_value={"value": PRIVATE + "!"})
    trail.log(OpType.FORGET, "plan", before_value={"value": PRIVATE + "!"})

    assert trail.purge_key("plan", metadata={"reason": "erasure request"}) == 3
    check = trail.verify_integrity()
    assert check["valid"] is True and check["purged_rows"] == 3

    dump = "\n".join(str(tuple(row)) for row in trail.conn.execute("SELECT * FROM audit_log"))
    assert PRIVATE not in dump
    assert "kept" in dump
    # A second purge finds nothing left and writes no new receipt.
    assert trail.purge_key("plan") == 0
    assert trail.verify_integrity()["valid"] is True


def test_emptying_a_row_without_a_receipt_still_breaks_the_chain(tmp_path):
    trail = _trail(tmp_path)
    trail.log(OpType.CREATE, "plan", after_value={"value": PRIVATE})
    trail.log(OpType.CREATE, "other", after_value={"value": "kept"})
    trail.purge_key("plan")
    assert trail.verify_integrity()["valid"] is True

    # Tamper: empty a row nobody purged and stamp it as purged.
    trail.conn.execute(
        "UPDATE audit_log SET after_value = NULL, metadata = ? WHERE key = 'other'",
        (json.dumps({"purged_at": 1}),),
    )
    trail.conn.commit()
    check = trail.verify_integrity()
    assert check["valid"] is False
    assert "Data hash mismatch" in check["first_error"]


def test_a_forged_receipt_naming_the_wrong_hash_does_not_cover_a_row(tmp_path):
    trail = _trail(tmp_path)
    trail.log(OpType.CREATE, "plan", after_value={"value": PRIVATE})
    row_id = trail.conn.execute("SELECT id FROM audit_log WHERE key = 'plan'").fetchone()[0]
    trail.log(OpType.PURGE, "plan", after_value={"purged": [{"id": row_id, "data_hash": "0" * 64}]})
    trail.conn.execute("UPDATE audit_log SET after_value = NULL WHERE id = ?", (row_id,))
    trail.conn.commit()
    assert trail.verify_integrity()["valid"] is False


def _manager(tmp_path):
    from bilinc.cloud.runtime import ProjectRuntimeManager

    return ProjectRuntimeManager(tmp_path)


def _files_text(directory) -> str:
    texts = []
    for path in directory.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".db"}:
            if path.suffix == ".db":
                conn = sqlite3.connect(path)
                for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
                    texts.extend(str(row) for row in conn.execute(f'SELECT * FROM "{name}"'))
                conn.close()
            else:
                texts.append(path.read_text(encoding="utf-8"))
    return "\n".join(texts)


def test_forget_with_purge_removes_values_from_history_and_snapshots(tmp_path):
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())

    async def scenario():
        await manager.commit(project, key="plan", value=PRIVATE)
        await manager.commit(project, key="other", value="kept")
        snapshot = await manager.create_snapshot(project, label="before")
        result = await manager.forget(project, key="plan", reason="erasure request", purge=True)
        assert result["removed"] is True and result["success"] is True
        assert result["purged"]["audit_rows"] >= 2
        assert result["purged"]["snapshots"] == 1

        plane = await manager.get_plane(project)
        assert plane.audit.verify_integrity()["valid"] is True
        history = await manager.history(project, key="plan")
        assert history["entries"][0]["op"] == "purge"
        assert history["entries"][0]["purged_rows"] == result["purged"]["audit_rows"]
        assert PRIVATE not in json.dumps(history)

        # Rolling back to the snapshot taken before the purge cannot bring it back.
        await manager.rollback_execute(
            project, snapshot_id=snapshot.id, reason="restore", expected_current_root=None
        )
        assert await plane.backend.load("plan") is None
        assert (await plane.backend.load("other")).value == "kept"
        await manager.close()
        assert PRIVATE not in _files_text(manager.project_dir(project))

    _run(scenario())


def test_purge_works_on_a_memory_forgotten_earlier(tmp_path):
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())

    async def scenario():
        await manager.commit(project, key="plan", value=PRIVATE)
        await manager.forget(project, key="plan", reason="no longer true")
        plane = await manager.get_plane(project)
        assert PRIVATE in json.dumps([tuple(row) for row in plane.audit.get_history(key="plan")])

        result = await manager.forget(project, key="plan", reason="erasure request", purge=True)
        assert result["removed"] is False and result["success"] is True
        assert result["purged"]["audit_rows"] >= 1
        assert PRIVATE not in json.dumps([tuple(row) for row in plane.audit.get_history(key="plan")])

        with pytest.raises(ValueError, match="memory_not_found"):
            await manager.forget(project, key="never-existed", reason="x", purge=True)
        with pytest.raises(ValueError, match="memory_not_found"):
            await manager.forget(project, key="plan", reason="again")
        await manager.close()

    _run(scenario())


def test_plain_forget_keeps_the_audit_values(tmp_path):
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())

    async def scenario():
        await manager.commit(project, key="plan", value=PRIVATE)
        result = await manager.forget(project, key="plan", reason="no longer true")
        assert "purged" not in result
        plane = await manager.get_plane(project)
        assert plane.audit.verify_integrity()["valid"] is True
        assert PRIVATE in json.dumps([tuple(row) for row in plane.audit.get_history(key="plan")])
        await manager.close()

    _run(scenario())


def test_project_purge_is_refused_by_default_and_dry_run_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("BILINC_PURGE_ENABLED", raising=False)
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())

    async def scenario():
        await manager.commit(project, key="plan", value=PRIVATE)
        await manager.create_snapshot(project, label="s")
        with pytest.raises(ValueError, match="purge_disabled"):
            await manager.purge_project(project)
        receipt = await manager.purge_project(project, dry_run=True)
        assert receipt == {"project_id": project, "dry_run": True, "schema": False, "files": True, "snapshots": 1}
        assert manager.project_dir(project).exists()
        assert (await (await manager.get_plane(project)).backend.load("plan")).value == PRIVATE
        await manager.close()

    _run(scenario())


def test_project_purge_removes_only_the_target_project(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_PURGE_ENABLED", "1")
    manager = _manager(tmp_path)
    target, other = str(uuid.uuid4()), str(uuid.uuid4())

    async def scenario():
        await manager.commit(target, key="plan", value=PRIVATE)
        await manager.commit(other, key="plan", value="other project")
        receipt = await manager.purge_project(target)
        assert receipt["purged"] is True and receipt["files"] is True
        assert not manager.project_dir(target).exists()
        assert (await (await manager.get_plane(other)).backend.load("plan")).value == "other project"
        # Purging again is a no-op that still succeeds.
        again = await manager.purge_project(target)
        assert again["files"] is False and again["purged"] is True
        await manager.close()

    _run(scenario())


def test_sidecar_routes_and_capabilities(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from bilinc.cloud.service import create_app

    monkeypatch.delenv("BILINC_PURGE_ENABLED", raising=False)
    headers = {"X-Bilinc-Sidecar-Token": "secret"}
    with TestClient(create_app(runtime_dir=tmp_path, sidecar_token="secret")) as client:
        project = str(uuid.uuid4())
        client.post(f"/v1/projects/{project}/commit", headers=headers, json={"key": "plan", "value": PRIVATE})
        forgot = client.post(
            f"/v1/projects/{project}/forget",
            headers=headers,
            json={"key": "plan", "reason": "erasure", "purge": True},
        )
        assert forgot.status_code == 200 and forgot.json()["purged"]["audit_rows"] >= 1
        refused = client.delete(f"/v1/projects/{project}", headers=headers)
        assert refused.status_code == 403 and refused.json()["detail"] == "purge_disabled"
        dry = client.delete(f"/v1/projects/{project}?dry_run=true", headers=headers)
        assert dry.status_code == 200 and dry.json()["dry_run"] is True
        assert client.delete(f"/v1/projects/{project}").status_code in {401, 403}
        capabilities = client.get("/health", headers=headers).json()["capabilities"]
        assert {"memory_purge", "project_purge"} <= set(capabilities)


def test_sdk_refuses_to_report_a_purge_the_server_did_not_confirm():
    from bilinc import CloudClient
    from bilinc.client import BilincCloudError

    sent = []

    def transport(method, url, *, headers, body, timeout):
        sent.append(json.loads(body.decode("utf-8")))
        return {"success": True, "removed": True}

    client = CloudClient(api_key="bil_live_example", transport=transport)
    assert client.forget("plan", reason="no longer true") == {"success": True, "removed": True}
    assert "purge" not in sent[-1]
    with pytest.raises(BilincCloudError, match="did not confirm the purge"):
        client.forget("plan", reason="erasure", purge=True)
    assert sent[-1]["purge"] is True


@needs_postgres
def test_postgres_purge_keeps_the_chain_valid_and_drops_only_the_target_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("BILINC_POSTGRES_DSN", DSN)
    monkeypatch.setenv("BILINC_PURGE_ENABLED", "1")
    from bilinc.storage.postgres_tenancy import project_schema

    manager = _manager(tmp_path)
    target, other = str(uuid.uuid4()), str(uuid.uuid4())

    async def scenario():
        import asyncpg

        await manager.commit(target, key="plan", value=PRIVATE)
        await manager.commit(target, key="keep", value="kept")
        await manager.commit(other, key="plan", value="other project")
        result = await manager.forget(target, key="plan", reason="erasure", purge=True)
        assert result["purged"]["audit_rows"] >= 2
        plane = await manager.get_plane(target)
        assert plane.audit.verify_integrity()["valid"] is True

        conn = await asyncpg.connect(DSN)
        try:
            schema = project_schema(target)
            audit_text = await conn.fetchval(
                f"SELECT string_agg(COALESCE(before_value, '') || COALESCE(after_value, ''), ' ') FROM \"{schema}\".audit_log"
            )
            assert PRIVATE not in (audit_text or "")
            receipt = await manager.purge_project(target)
            assert receipt["schema"] is True and receipt["purged"] is True
            assert not await conn.fetchval("SELECT 1 FROM information_schema.schemata WHERE schema_name = $1", schema)
            assert await conn.fetchval(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = $1", project_schema(other)
            )
        finally:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{project_schema(other)}" CASCADE')
            await conn.close()
        await manager.close()

    _run(scenario())
