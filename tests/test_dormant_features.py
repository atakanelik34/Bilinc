"""C10: characterization of features that exist but are dormant or only partly wired.

These tests pin what the code does today, so a change to any of it is a conscious one. They are not a
statement that the behaviour is wanted; the product decisions are the blocked-owner row C10-DECIDE.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from bilinc.adaptive.forgetting_engine import ForgettingEngine
from bilinc.core.knowledge_graph import EdgeType, KnowledgeGraph
from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend


async def _plane(tmp_path, *, verification=False) -> StatePlane:
    plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "dormant.db")), enable_verification=verification,
                       enable_audit=True)
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()
    return plane


# ---- knowledge graph contradictions ---------------------------------------------------------

def test_ingesting_conflicting_memories_creates_no_contradiction_edge():
    kg = KnowledgeGraph()
    kg.ingest_memory_entry(MemoryEntry(
        key="mem:open", value="Apollo Launch Program status: open. Houston Control confirmed it.",
        memory_type=MemoryType.SEMANTIC))
    kg.ingest_memory_entry(MemoryEntry(
        key="mem:closed", value="Apollo Launch Program status: closed. Houston Control cancelled it.",
        memory_type=MemoryType.SEMANTIC))
    assert kg._edges, "the example must create edges, or the check below proves nothing"
    assert {edge.relation_type for edge in kg._edges} <= {EdgeType.RELATED_TO, EdgeType.SUPPORTS}
    assert kg.find_contradictions() == []


def test_only_an_explicit_contradicts_edge_is_reported():
    kg = KnowledgeGraph()
    kg.add_entity("A")
    kg.add_entity("B")
    kg.add_relation("A", "B", EdgeType.CONTRADICTS)
    assert [item["type"] for item in kg.find_contradictions()] == ["direct_contradiction"]


# ---- valid_at --------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_commit_never_sets_valid_at(tmp_path):
    plane = await _plane(tmp_path)
    await plane.commit("note", "text", MemoryType.SEMANTIC)
    assert (await plane.backend.load("note")).valid_at is None
    await plane.commit("note", "changed text", MemoryType.SEMANTIC)  # a revise writes none either
    assert (await plane.backend.load("note")).valid_at is None


@pytest.mark.asyncio
async def test_hosted_commit_never_sets_valid_at_or_superseded_by(tmp_path, monkeypatch):
    from bilinc.cloud.runtime import ProjectRuntimeManager

    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "sqlite")
    manager = ProjectRuntimeManager(tmp_path)
    project = str(uuid.uuid4())
    try:
        await manager.commit(project, key="note", value="one")
        await manager.commit(project, key="note", value="two")
        stored = await (await manager.get_plane(project)).backend.load("note")
        assert stored.valid_at is None and stored.superseded_by is None
    finally:
        await manager.close()


# ---- superseded_by ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_revise_through_commit_leaves_superseded_by_empty(tmp_path):
    plane = await _plane(tmp_path)
    await plane.commit("note", "one", MemoryType.SEMANTIC)
    await plane.commit("note", "two", MemoryType.SEMANTIC)
    stored = await plane.backend.load("note")
    assert stored.value == "two" and stored.superseded_by is None


# ---- verification_score ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verification_score_is_a_fixed_pass_or_fail_value(tmp_path):
    plane = await _plane(tmp_path, verification=True)
    passing = plane._apply_entry_verification(MemoryEntry(key="ok", value="fine", importance=0.5))
    assert (passing.is_verified, passing.verification_score) == (True, 0.8)
    failing = plane._apply_entry_verification(MemoryEntry(key="bad", value="fine", importance=-1.0))
    assert (failing.is_verified, failing.verification_score) == (False, 0.0)
    assert failing.metadata["verification_failed"]


@pytest.mark.asyncio
async def test_without_verification_the_score_stays_zero(tmp_path):
    plane = await _plane(tmp_path, verification=False)
    await plane.commit("note", "text", MemoryType.SEMANTIC)
    stored = await plane.backend.load("note")
    assert (stored.is_verified, stored.verification_score) == (False, 0.0)


@pytest.mark.asyncio
async def test_a_verified_commit_keeps_the_fixed_score_through_storage(tmp_path):
    plane = await _plane(tmp_path, verification=True)
    await plane.commit("note", "text", MemoryType.SEMANTIC)
    assert (await plane.backend.load("note")).verification_score == 0.8


# ---- StatePlane.verify -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plane_verify_works_but_has_its_own_result_shape(tmp_path):
    plane = await _plane(tmp_path, verification=True)
    await plane.commit("note", "text", MemoryType.SEMANTIC)
    result = await plane.verify("note")
    assert result["exists"] is True and result["integrity_valid"] is True
    assert {"audit_entries", "invariant_checks", "root_hash", "value"} <= set(result)
    assert await plane.verify("missing") == {
        "key": "missing", "exists": False, "audit_entries": [], "invariant_checks": []}


# ---- ForgettingEngine.forget_by_contradiction --------------------------------------------------

@pytest.mark.asyncio
async def test_forget_by_contradiction_finds_nothing_on_a_key_unique_store(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "forget.db"))
    await backend.init()
    await backend.save(MemoryEntry(key="a", value="one"))
    await backend.save(MemoryEntry(key="a", value="two"))   # an upsert: still one row
    result = await ForgettingEngine(backend).forget_by_contradiction()
    assert (result.entries_processed, result.entries_forgotten) == (0, 0)


class _TwoRowsOneKey:
    """A stub store that returns two rows with the same key, which a real store never does."""

    def __init__(self):
        winner = MemoryEntry(key="k", value="winner", importance=0.5, verification_score=0.8)
        loser = MemoryEntry(key="k", value="loser", importance=0.3, verification_score=0.1, access_count=0)
        self.rows = [winner, loser]
        self.saved = []

    async def list_all(self):
        return self.rows

    async def save(self, entry):
        self.saved.append(entry)


@pytest.mark.asyncio
@pytest.mark.xfail(strict=True, reason="forget_by_contradiction writes a self-pointing superseded_by")
async def test_forget_by_contradiction_points_the_loser_at_something_else():
    backend = _TwoRowsOneKey()
    result = await ForgettingEngine(backend).forget_by_contradiction()
    assert result.entries_forgotten == 1          # the loser is not protected and was written
    assert backend.saved[0].superseded_by != backend.saved[0].key


# ---- Postgres (gated): the same facts through the hosted runtime --------------------------------

_DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")


@pytest.mark.skipif(not _DSN, reason="BILINC_TEST_POSTGRES_DSN not set")
def test_hosted_postgres_keeps_valid_at_empty_and_the_fixed_scores(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("BILINC_POSTGRES_DSN", _DSN)
    monkeypatch.delenv("BILINC_CLOUD_EMBEDDINGS", raising=False)
    from bilinc.cloud.runtime import ProjectRuntimeManager

    project = str(uuid.uuid4())

    async def scenario():
        manager = ProjectRuntimeManager(tmp_path)
        try:
            await manager.commit(project, key="note", value="one")
            await manager.commit(project, key="note", value="two")
            stored = await (await manager.get_plane(project)).backend.load("note")
            assert stored.value == "two"
            assert stored.valid_at is None and stored.superseded_by is None
            assert (stored.is_verified, stored.verification_score) == (True, 0.8)
            plane = await manager.get_plane(project)
            failing = plane._apply_entry_verification(MemoryEntry(key="bad", value="x", importance=-1.0))
            await plane.backend.save(failing)           # a failed check: score 0.0 must survive the round trip too
            reloaded = await plane.backend.load("bad")
            assert (reloaded.is_verified, reloaded.verification_score) == (False, 0.0)
        finally:
            await manager.close()

    asyncio.run(scenario())
