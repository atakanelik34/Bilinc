"""Both purge paths delete the capture rows that name the key, first, and fail closed (item A4r)."""
from __future__ import annotations

import asyncio
import json
import time
import uuid

import pytest

from bilinc.core.stateplane import StatePlane
from bilinc.eval.capture import EvalCaptureRow
from bilinc.mcp_server.server_v2 import _handle_forget
from bilinc.storage.sqlite import SQLiteBackend


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _row(query="q", keys=(), detail=None):
    return EvalCaptureRow(
        schema_version=1, tool_name="recall", query=query, retrieved_keys=list(keys),
        retrieved_scores=[0.5] * len(keys), memory_types=["semantic"] * len(keys),
        latency_ms=1, created_at=time.time(), detail=detail or {},
    )


async def _stdio_plane(tmp_path):
    plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "p.sqlite")), enable_verification=False, enable_audit=True)
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()
    return plane


def test_stdio_purge_deletes_capture_rows_that_name_the_key(tmp_path):
    async def scenario():
        plane = await _stdio_plane(tmp_path)
        await plane.commit_with_agm_async(key="plan", value="Quartz harbor", importance=0.9)
        await plane.backend.record_eval_candidate(_row("find it", keys=["plan"]))
        await plane.backend.record_eval_candidate(_row("plan", detail={"key": "plan"}))
        await plane.backend.record_eval_candidate(_row("other", keys=["other"]))
        payload = json.loads((await _handle_forget(plane, {"key": "plan", "purge": True}))[0].text)
        assert "purged" in payload
        return [r.query for r in await plane.backend.list_eval_candidates()]

    assert _run(scenario()) == ["other"]


def test_stdio_purge_fails_closed_and_a_retry_finishes_it(tmp_path):
    async def scenario():
        plane = await _stdio_plane(tmp_path)
        await plane.commit_with_agm_async(key="plan", value="Quartz harbor", importance=0.9)
        await plane.backend.record_eval_candidate(_row("find it", keys=["plan"]))
        real = plane.backend.purge_eval_candidates

        async def broken(key):
            raise RuntimeError("disk trouble")

        plane.backend.purge_eval_candidates = broken
        failed = json.loads((await _handle_forget(plane, {"key": "plan", "purge": True}))[0].text)
        assert failed["success"] is False and failed["error"] == "purge_incomplete" and "purged" not in failed
        assert "disk trouble" not in json.dumps(failed)

        plane.backend.purge_eval_candidates = real  # the forget is committed; the retry must still be admitted
        retry = json.loads((await _handle_forget(plane, {"key": "plan", "purge": True}))[0].text)
        assert retry.get("error") is None and "purged" in retry
        return await plane.backend.list_eval_candidates()

    assert _run(scenario()) == []


def test_capture_delete_runs_before_the_audit_and_index_steps(tmp_path):
    async def scenario():
        plane = await _stdio_plane(tmp_path)
        await plane.commit_with_agm_async(key="plan", value="Quartz harbor", importance=0.9)
        order = []
        for name in ("purge_eval_candidates", "purge_memory_event_payloads", "compact_search_index"):
            original = getattr(plane.backend, name)

            def wrap(original=original, name=name):
                async def call(*args, **kwargs):
                    order.append(name)
                    return await original(*args, **kwargs)
                return call

            setattr(plane.backend, name, wrap())
        original_purge = plane.audit.purge_key

        def audit_purge(*args, **kwargs):
            order.append("audit.purge_key")
            return original_purge(*args, **kwargs)

        plane.audit.purge_key = audit_purge
        await _handle_forget(plane, {"key": "plan", "purge": True})
        return order

    order = _run(scenario())
    assert order[0] == "purge_eval_candidates"
    assert order.index("purge_eval_candidates") < order.index("audit.purge_key") < order.index("compact_search_index")


def test_hosted_purge_deletes_capture_rows_and_a_failure_is_not_swallowed(tmp_path):
    from bilinc.cloud.runtime import ProjectRuntimeManager

    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid.uuid4())

    async def scenario():
        await manager.commit(project, key="plan", value="Quartz harbor", importance=1.0)
        plane = await manager.get_plane(project)
        await plane.backend.record_eval_candidate(_row("find it", keys=["plan"]))
        await plane.backend.record_eval_candidate(_row("other", keys=["other"]))
        real = plane.backend.purge_eval_candidates

        async def broken(key):
            raise RuntimeError("disk trouble")

        plane.backend.purge_eval_candidates = broken
        with pytest.raises(RuntimeError):
            await manager.forget(project, key="plan", reason="erasure", purge=True)

        plane.backend.purge_eval_candidates = real  # audit is on, so the gate admits the retry
        result = await manager.forget(project, key="plan", reason="erasure", purge=True)
        assert "purged" in result
        return [r.query for r in await plane.backend.list_eval_candidates()]

    assert _run(scenario()) == ["other"]
