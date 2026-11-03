"""C9b: the contradiction probe reads the claims it needs, not the newest 1000 claims."""
from __future__ import annotations

import os
import time
import uuid

import pytest

from bilinc.core.models import Claim, ClaimKind, MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.eval.contradictions import probe_claim_contradictions_for_queries
from bilinc.storage.postgres import PostgresBackend
from bilinc.storage.sqlite import SQLiteBackend

FILLERS = 1100
_DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
needs_postgres = pytest.mark.skipif(not _DSN, reason="BILINC_TEST_POSTGRES_DSN not set")


def _claim(memory_key, subject, obj, *, predicate="tier", **kwargs) -> Claim:
    return Claim(memory_key=memory_key, holder="atakan", subject=subject, claim=f"{subject} {predicate} {obj}",
                 kind=ClaimKind.FACT, metadata={"predicate": predicate, "object": obj}, **kwargs)


async def _fill(backend, count=FILLERS):
    for i in range(count):  # written last, so they are the newest claims
        await backend.save_claim(_claim(f"fill:{i}", f"S{i}", "o", predicate="p"))


async def _sqlite_backend(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "c9b.db"))
    await backend.init()
    return backend


# ---- backend method -----------------------------------------------------------------------------

async def _check_method(backend):
    now = time.time()
    await backend.save_claim(_claim("m1", "Alpha", "a", updated_at=now - 30))
    await backend.save_claim(_claim("m2", "Alpha", "b"))
    await backend.save_claim(_claim("m3", "Beta", "c"))
    await backend.save_claim(_claim("m4", "Gamma", "d"))
    await backend.save_claim(_claim("m5", "Alpha", "inactive", active=False))
    await backend.save_claim(_claim("m6", "Alpha", "expired", invalid_at=1.0))

    found = await backend.list_claims_for_subjects(["Alpha", "Beta", "Alpha", "nobody"])
    assert {c.memory_key for c in found} == {"m1", "m2", "m3"}          # active and valid only, no other subject
    assert [c.updated_at for c in found] == sorted((c.updated_at for c in found), reverse=True)
    inactive = await backend.list_claims_for_subjects(["Alpha"], active=False)
    assert "m5" in {c.memory_key for c in inactive}
    assert await backend.list_claims_for_subjects([]) == []
    assert await backend.list_claims_for_subjects([None]) == []


async def _check_no_cap(backend):
    for i in range(1100):
        await backend.save_claim(_claim(f"big:{i}", "Big", f"v{i}", predicate=f"p{i}"))
    assert len(await backend.list_claims_for_subjects(["Big"])) == 1100


@pytest.mark.asyncio
async def test_sqlite_list_claims_for_subjects(tmp_path):
    backend = await _sqlite_backend(tmp_path)
    await _check_method(backend)
    await _check_no_cap(backend)


@needs_postgres
@pytest.mark.asyncio
async def test_postgres_list_claims_for_subjects_and_isolation():
    schema = "bilinc_p_" + uuid.uuid4().hex
    other = "bilinc_p_" + uuid.uuid4().hex
    backend, neighbour = PostgresBackend(_DSN, schema=schema), PostgresBackend(_DSN, schema=other)
    await backend.init()
    await neighbour.init()
    try:
        await neighbour.save_claim(_claim("n1", "Alpha", "secret-of-another-project"))
        await _check_method(backend)
        assert "n1" not in {c.memory_key for c in await backend.list_claims_for_subjects(["Alpha"])}
        await _check_no_cap(backend)
    finally:
        await backend.close()
        await neighbour.close()


# ---- the probe ---------------------------------------------------------------------------------

async def _plane(backend) -> StatePlane:
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    return plane


async def _scenario(plane):
    """Two contradicting claims on subject S: one on the recalled memory, one on another memory; then 1100 newer claims."""
    await plane.commit("mem:paid", "Bilinc tier paid", MemoryType.SEMANTIC)
    await plane.backend.save_claim(_claim("mem:paid", "Bilinc", "paid"))
    await plane.backend.save_claim(_claim("mem:other", "Bilinc", "free"))     # same subject, not recalled itself
    await _fill(plane.backend)
    report = await probe_claim_contradictions_for_queries(plane, ["Bilinc tier paid"], top_k=1)
    return report.to_dict()


@pytest.mark.asyncio
async def test_probe_finds_a_contradiction_older_than_the_newest_1000_claims(tmp_path):
    payload = await _scenario(await _plane(await _sqlite_backend(tmp_path)))
    assert payload["count"] == 1 and payload["queries_with_contradiction"] == 1


@needs_postgres
@pytest.mark.asyncio
async def test_probe_finds_the_same_contradiction_on_postgres(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("BILINC_POSTGRES_DSN", _DSN)
    monkeypatch.delenv("BILINC_CLOUD_EMBEDDINGS", raising=False)
    from bilinc.cloud.runtime import ProjectRuntimeManager

    manager = ProjectRuntimeManager(tmp_path)
    try:
        plane = await manager.get_plane(str(uuid.uuid4()))
        payload = await _scenario(plane)
        assert payload["count"] == 1 and payload["queries_with_contradiction"] == 1
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_a_small_project_gets_the_same_report(tmp_path):
    plane = await _plane(await _sqlite_backend(tmp_path))
    await plane.commit("mem:paid", "Bilinc tier paid", MemoryType.SEMANTIC)
    await plane.commit("mem:free", "Bilinc tier free", MemoryType.SEMANTIC)
    await plane.backend.save_claim(_claim("mem:paid", "Bilinc", "paid"))
    await plane.backend.save_claim(_claim("mem:free", "Bilinc", "free"))
    report = (await probe_claim_contradictions_for_queries(plane, ["Bilinc tier"], top_k=2)).to_dict()
    assert report["count"] == 1 and report["queries_evaluated"] == 1
    pair = report["findings"][0]
    assert {pair["left_claim_id"], pair["right_claim_id"]} == {
        c.id for c in await plane.backend.list_claims(active=True, limit=10)}


# ---- stub backends ------------------------------------------------------------------------------

class _Stub:
    def __init__(self, *, keyed=True, subjects=True, fail=False):
        self.calls = []
        self.fail = fail
        if keyed:
            self.list_claims_for_memory_keys = self._keyed
        if subjects:
            self.list_claims_for_subjects = self._subjects

    async def _keyed(self, keys, active=True, limit=None):
        self.calls.append(("keys", sorted(keys)))
        if self.fail:
            raise RuntimeError("backend down")
        return [_claim("k1", "S", "a")] if "k1" in keys else []

    async def _subjects(self, subjects, active=True, limit=None):
        self.calls.append(("subjects", sorted(subjects)))
        return [_claim("k1", "S", "a"), _claim("k2", "S", "b")]

    async def list_claims(self, **kwargs):
        self.calls.append(("list", kwargs))
        return [_claim("k1", "S", "a"), _claim("k2", "S", "b")]


class _PlaneStub:
    def __init__(self, backend, keys):
        self.backend = backend
        self.keys = keys

    async def recall_intelligent(self, query, limit=5):
        return [{"key": key} for key in self.keys]


@pytest.mark.asyncio
async def test_no_recalled_keys_means_no_claim_read():
    stub = _Stub()
    report = await probe_claim_contradictions_for_queries(_PlaneStub(stub, []), ["q"])
    assert stub.calls == [] and report.to_dict()["count"] == 0


@pytest.mark.asyncio
async def test_keys_and_subjects_are_read_once_across_queries():
    stub = _Stub()
    report = await probe_claim_contradictions_for_queries(_PlaneStub(stub, ["k1"]), ["q1", "q2", "q3"])
    assert stub.calls == [("keys", ["k1"]), ("subjects", ["S"])]
    assert report.to_dict()["queries_with_contradiction"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("keyed,subjects", [(True, False), (False, True), (False, False)])
async def test_without_both_keyed_methods_the_old_global_read_is_kept(keyed, subjects):
    stub = _Stub(keyed=keyed, subjects=subjects)
    report = await probe_claim_contradictions_for_queries(_PlaneStub(stub, ["k1"]), ["q"])
    assert stub.calls == [("list", {"active": True, "limit": 1000})]
    assert report.to_dict()["count"] == 1


@pytest.mark.asyncio
async def test_a_backend_error_is_not_swallowed():
    with pytest.raises(RuntimeError, match="backend down"):
        await probe_claim_contradictions_for_queries(_PlaneStub(_Stub(fail=True), ["k1"]), ["q"])
