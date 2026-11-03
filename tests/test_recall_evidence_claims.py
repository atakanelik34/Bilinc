"""C9: recall evidence loads the claims of the recalled keys, not just the newest 1000 claims."""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from bilinc.core.models import Claim, ClaimKind, MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend

FILLERS = 1100  # more than the old 1000-row window


def _claim_meta(subject: str, predicate: str, obj: str) -> dict:
    return {"claims": [{
        "holder": "atakan", "subject": subject, "claim": f"{subject} {predicate} {obj}",
        "kind": ClaimKind.FACT.value, "metadata": {"predicate": predicate, "object": obj},
    }]}


async def _plane(tmp_path) -> StatePlane:
    plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "c9.db")), enable_verification=False, enable_audit=False)
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()
    return plane


async def _commit_contradicting_pair(plane):
    await plane.commit("mem:paid", "Bilinc tier paid", MemoryType.SEMANTIC, metadata=_claim_meta("Bilinc", "tier", "paid"))
    await plane.commit("mem:free", "Bilinc tier free", MemoryType.SEMANTIC, metadata=_claim_meta("Bilinc", "tier", "free"))


async def _add_newer_claims_of_other_keys(backend, count=FILLERS):
    for i in range(count):  # written after the pair, so they are the newest claims
        await backend.save_claim(Claim(
            memory_key=f"fill:{i}", holder="x", subject=f"S{i}", claim=f"S{i} p o",
            kind=ClaimKind.FACT, metadata={"predicate": "p", "object": "o"},
        ))


@pytest.mark.asyncio
async def test_claims_of_a_recalled_key_survive_more_than_1000_newer_claims(tmp_path):
    plane = await _plane(tmp_path)
    await _commit_contradicting_pair(plane)
    await _add_newer_claims_of_other_keys(plane.backend)

    payload = await plane.recall_profiled("Bilinc tier", profile="verified", limit=5)

    keys = {claim["memory_key"] for claim in payload["evidence"]["claims"]}
    assert {"mem:paid", "mem:free"} <= keys
    assert not any(key.startswith("fill:") for key in keys)
    assert payload["evidence"]["contradictions"]["count"] == 1


@pytest.mark.asyncio
async def test_two_contradicting_active_claims_on_one_key_are_reported_after_the_window(tmp_path):
    # a normal commit keeps one extraction active per key, so these are written as claims
    plane = await _plane(tmp_path)
    await plane.commit("mem:tier", "Bilinc tier", MemoryType.SEMANTIC)
    for obj in ("paid", "free"):
        await plane.backend.save_claim(Claim(
            memory_key="mem:tier", holder="atakan", subject="Bilinc", claim=f"Bilinc tier {obj}",
            kind=ClaimKind.FACT, metadata={"predicate": "tier", "object": obj},
        ))
    await _add_newer_claims_of_other_keys(plane.backend)

    payload = await plane.recall_profiled("Bilinc tier", profile="verified", limit=5)

    assert len([c for c in payload["evidence"]["claims"] if c["memory_key"] == "mem:tier"]) == 2
    assert payload["evidence"]["contradictions"]["count"] == 1


@pytest.mark.asyncio
async def test_small_projects_get_the_same_evidence_in_the_same_order(tmp_path):
    plane = await _plane(tmp_path)
    await _commit_contradicting_pair(plane)
    payload = await plane.recall_profiled("Bilinc tier", profile="verified", limit=5)
    claims = payload["evidence"]["claims"]
    assert {c["memory_key"] for c in claims} == {"mem:paid", "mem:free"}
    assert [c["updated_at"] for c in claims] == sorted((c["updated_at"] for c in claims), reverse=True)
    assert payload["evidence"]["contradictions"]["count"] == 1


class _Stub:
    def __init__(self, keyed=True, fail=False):
        self.calls = []
        self.fail = fail
        if keyed:
            self.list_claims_for_memory_keys = self._keyed

    async def _keyed(self, keys, active=True, limit=None):
        self.calls.append(("keyed", list(keys), limit))
        if self.fail:
            raise RuntimeError("backend down")
        return []

    async def list_claims(self, **kwargs):
        self.calls.append(("list", kwargs))
        return []


def _plane_with(stub) -> StatePlane:
    plane = StatePlane(enable_verification=False, enable_audit=False)
    plane.backend = stub
    return plane


PROFILE = {"include_contradictions": True}


@pytest.mark.asyncio
async def test_no_recalled_keys_means_no_backend_call():
    stub = _Stub()
    evidence = await _plane_with(stub)._recall_profile_evidence([], PROFILE)
    assert stub.calls == [] and evidence["claims"] == []


@pytest.mark.asyncio
async def test_only_the_recalled_keys_are_asked_for_and_without_a_row_cap():
    stub = _Stub()
    await _plane_with(stub)._recall_profile_evidence([{"key": "b"}, {"key": "a"}, {"key": None}], PROFILE)
    assert stub.calls == [("keyed", ["a", "b"], None)]


@pytest.mark.asyncio
async def test_a_backend_without_the_keyed_read_keeps_the_old_path():
    stub = _Stub(keyed=False)
    await _plane_with(stub)._recall_profile_evidence([{"key": "a"}], PROFILE)
    assert stub.calls == [("list", {"active": True, "limit": 1000})]


@pytest.mark.asyncio
async def test_a_backend_error_is_not_swallowed():
    with pytest.raises(RuntimeError, match="backend down"):
        await _plane_with(_Stub(fail=True))._recall_profile_evidence([{"key": "a"}], PROFILE)


# ---- hosted runtime on Postgres ----------------------------------------------------------

_DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")


@pytest.mark.skipif(not _DSN, reason="BILINC_TEST_POSTGRES_DSN not set")
def test_hosted_verified_recall_keeps_old_claims_and_stays_inside_the_project(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("BILINC_POSTGRES_DSN", _DSN)
    from bilinc.cloud.runtime import ProjectRuntimeManager

    mine, other = str(uuid.uuid4()), str(uuid.uuid4())

    async def scenario():
        manager = ProjectRuntimeManager(tmp_path)
        try:
            for project, obj in ((mine, "paid"), (other, "secret-other-project")):
                await manager.commit(project, key="mem:tier", value=f"Bilinc tier {obj}",
                                     metadata=_claim_meta("Bilinc", "tier", obj))
            plane = await manager.get_plane(mine)
            await manager.commit(mine, key="mem:tier2", value="Bilinc tier free",
                                 metadata=_claim_meta("Bilinc", "tier", "free"))
            await _add_newer_claims_of_other_keys(plane.backend)
            recalled = await manager.recall(mine, query="Bilinc tier", profile="verified", limit=5)
            evidence = recalled["evidence"]
            keys = {c["memory_key"] for c in evidence["claims"]}
            assert {"mem:tier", "mem:tier2"} <= keys
            assert "secret-other-project" not in str(evidence)
            assert evidence["contradictions"]["count"] == 1
        finally:
            await manager.close()

    asyncio.run(scenario())
