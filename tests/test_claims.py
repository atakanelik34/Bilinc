import json

import pytest

from bilinc.core.stateplane import StatePlane
from bilinc.core.claims import claim_id_for, extract_claims_from_entry, normalize_claim_kind
from bilinc.core.models import Claim, ClaimKind, MemoryEntry, MemoryType
from bilinc.mcp_server.server_v2 import (
    _handle_claim_contradictions,
    _handle_claims_for_entity,
    _handle_claims_list,
    _handle_claims_search,
    _handle_commit_mem,
    _handle_revise,
)
from bilinc.storage.postgres import PostgresBackend
from bilinc.storage.sqlite import SQLiteBackend


async def make_temp_plane(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "test.db"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()
    return plane


def text_payload(result):
    return json.loads(result[0].text)


def test_claim_model_defaults():
    claim = Claim(
        memory_key="mem:1",
        holder="atakan",
        subject="Bilinc",
        claim="Bilinc is a verifiable agent brain",
        kind=ClaimKind.FACT,
        confidence=0.9,
        source="test",
        provenance_id="mem:1",
    )

    assert claim.id
    assert claim.active is True
    assert claim.superseded_by is None
    assert claim.valid_at is None
    assert claim.invalid_at is None
    assert claim.metadata == {}
    assert claim.created_at <= claim.updated_at


def test_claim_kind_normalization():
    assert normalize_claim_kind("fact") == ClaimKind.FACT
    assert normalize_claim_kind("PREFERENCE") == ClaimKind.PREFERENCE
    assert normalize_claim_kind("invalid") is None


def test_claim_id_is_stable():
    first = claim_id_for("mem:1", "ReARC uses Bilinc", "atakan", "ReARC")
    second = claim_id_for("mem:1", "ReARC uses Bilinc", "atakan", "ReARC")

    assert first == second
    assert len(first) >= 16


@pytest.mark.asyncio
async def test_claims_table_exists(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "claims.db"))
    await backend.init()

    row = backend._get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='claims'"
    ).fetchone()

    assert row is not None


@pytest.mark.asyncio
async def test_save_list_search_claims(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "claims.db"))
    await backend.init()
    claim = Claim(memory_key="mem:1", holder="atakan", subject="ReARC", claim="ReARC uses Bilinc", kind=ClaimKind.FACT)

    await backend.save_claim(claim)

    listed = await backend.list_claims(holder="atakan")
    searched = await backend.search_claims("Bilinc")

    assert [c.id for c in listed] == [claim.id]
    assert [c.id for c in searched] == [claim.id]


@pytest.mark.asyncio
async def test_search_claims_excludes_inactive_and_expired_by_default(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "claims.db"))
    await backend.init()
    active = Claim(memory_key="mem:active", holder="atakan", subject="ReARC", claim="ReARC current claim", kind=ClaimKind.FACT)
    inactive = Claim(memory_key="mem:inactive", holder="atakan", subject="ReARC", claim="ReARC stale inactive", kind=ClaimKind.FACT, active=False)
    expired = Claim(memory_key="mem:expired", holder="atakan", subject="ReARC", claim="ReARC stale expired", kind=ClaimKind.FACT, invalid_at=1.0)
    await backend.save_claim(active)
    await backend.save_claim(inactive)
    await backend.save_claim(expired)

    listed = await backend.list_claims(subject="ReARC")
    searched = await backend.search_claims("ReARC")

    assert [claim.id for claim in listed] == [active.id]
    assert [claim.id for claim in searched] == [active.id]


@pytest.mark.asyncio
async def test_rollback_reprojects_claims_to_restored_memory_state(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "rollback.db"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=True)
    await plane.init()
    await plane.commit("mem:rollback", "source", MemoryType.SEMANTIC)
    snapshot = await plane.snapshot()
    await plane.commit(
        "mem:rollback",
        "source",
        MemoryType.SEMANTIC,
        metadata={"claims": [{"holder": "atakan", "subject": "Bilinc", "claim": "rollback stale claim", "kind": "fact"}]},
    )
    assert len(await plane.backend.list_claims(subject="Bilinc")) == 1

    await plane.rollback(snapshot["timestamp"])

    assert await plane.backend.list_claims(subject="Bilinc", active=True) == []
    assert await plane.backend.list_claims(subject="Bilinc", active=False) == []


@pytest.mark.asyncio
async def test_supersede_claim_marks_old_inactive(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "claims.db"))
    await backend.init()
    old = Claim(memory_key="mem:1", holder="atakan", subject="ReARC", claim="old", kind=ClaimKind.FACT)
    new = Claim(memory_key="mem:2", holder="atakan", subject="ReARC", claim="new", kind=ClaimKind.FACT)
    await backend.save_claim(old)

    await backend.supersede_claim(old.id, new)

    active = await backend.list_claims(subject="ReARC", active=True)
    inactive = await backend.list_claims(subject="ReARC", active=False)
    assert [c.id for c in active] == [new.id]
    assert inactive[0].id == old.id
    assert inactive[0].superseded_by == new.id


def test_extract_claims_from_metadata():
    entry = MemoryEntry(
        key="mem:1",
        value="source text",
        memory_type=MemoryType.SEMANTIC,
        metadata={
            "claims": [
                {"holder": "atakan", "subject": "ReARC", "claim": "ReARC uses Bilinc", "kind": "fact", "confidence": 0.9}
            ]
        },
    )

    claims = extract_claims_from_entry(entry)

    assert len(claims) == 1
    assert claims[0].memory_key == "mem:1"
    assert claims[0].kind == ClaimKind.FACT
    assert claims[0].confidence == 0.9


def test_extract_claims_from_value_envelope_skips_invalid_kind():
    good = MemoryEntry(
        key="good",
        value={"holder": "user", "subject": "Atakan", "claim": "Atakan prefers concise answers", "kind": "preference"},
        memory_type=MemoryType.SEMANTIC,
    )
    bad = MemoryEntry(
        key="bad",
        value={"holder": "user", "subject": "Atakan", "claim": "bad", "kind": "nonsense"},
        memory_type=MemoryType.SEMANTIC,
    )

    assert extract_claims_from_entry(good)[0].kind == ClaimKind.PREFERENCE
    assert extract_claims_from_entry(bad) == []


def test_extract_claims_skips_only_malformed_confidence():
    entry = MemoryEntry(
        key="mem:confidence",
        value="source",
        memory_type=MemoryType.SEMANTIC,
        metadata={
            "claims": [
                {"holder": "atakan", "subject": "Bilinc", "claim": "bad confidence", "kind": "fact", "confidence": "bad"},
                {"holder": "atakan", "subject": "Bilinc", "claim": "valid confidence", "kind": "fact", "confidence": 0.8},
            ]
        },
    )

    claims = extract_claims_from_entry(entry)

    assert len(claims) == 1
    assert claims[0].claim == "valid confidence"


@pytest.mark.asyncio
async def test_commit_projects_metadata_claims_without_duplicates(tmp_path):
    plane = await make_temp_plane(tmp_path)
    metadata = {
        "claims": [
            {"holder": "atakan", "subject": "ReARC", "claim": "ReARC uses Bilinc", "kind": "fact", "confidence": 0.9}
        ]
    }

    await plane.commit("mem:1", "source", MemoryType.SEMANTIC, metadata=metadata)
    await plane.commit("mem:1", "source", MemoryType.SEMANTIC, metadata=metadata)

    claims = await plane.backend.list_claims(subject="ReARC")
    assert len(claims) == 1
    assert claims[0].memory_key == "mem:1"


@pytest.mark.asyncio
async def test_commit_update_deactivates_stale_claims_for_same_memory(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit(
        "mem:1",
        "source",
        MemoryType.SEMANTIC,
        metadata={"claims": [{"holder": "atakan", "subject": "Bilinc", "claim": "Bilinc tier paid", "kind": "fact"}]},
    )
    await plane.commit(
        "mem:1",
        "source",
        MemoryType.SEMANTIC,
        metadata={"claims": [{"holder": "atakan", "subject": "Bilinc", "claim": "Bilinc tier free", "kind": "fact"}]},
    )

    active = await plane.backend.list_claims(subject="Bilinc", active=True)
    inactive = await plane.backend.list_claims(subject="Bilinc", active=False)

    assert [claim.claim for claim in active] == ["Bilinc tier free"]
    assert [claim.claim for claim in inactive] == ["Bilinc tier paid"]


@pytest.mark.asyncio
async def test_forget_deletes_projected_claims(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit(
        "mem:forget",
        "source",
        MemoryType.SEMANTIC,
        metadata={"claims": [{"holder": "atakan", "subject": "Bilinc", "claim": "Bilinc stores claims", "kind": "fact"}]},
    )

    assert len(await plane.backend.list_claims(subject="Bilinc", active=True)) == 1
    assert await plane.backend.delete("mem:forget") is True

    assert await plane.backend.list_claims(subject="Bilinc", active=True) == []
    assert await plane.backend.list_claims(subject="Bilinc", active=False) == []


@pytest.mark.asyncio
async def test_mcp_commit_mem_projects_claims(tmp_path):
    plane = await make_temp_plane(tmp_path)

    payload = text_payload(await _handle_commit_mem(
        plane,
        {
            "key": "mem:mcp",
            "value": "source",
            "memory_type": "semantic",
            "metadata": {
                "claims": [{"holder": "atakan", "subject": "Bilinc", "claim": "MCP projects claims", "kind": "fact"}]
            },
        },
    ))
    claims = await plane.backend.list_claims(subject="Bilinc")

    assert payload["success"] is True
    assert [claim.claim for claim in claims] == ["MCP projects claims"]


@pytest.mark.asyncio
async def test_mcp_revise_reprojects_claims_and_deactivates_stale_claims(tmp_path):
    plane = await make_temp_plane(tmp_path)

    seed = text_payload(await _handle_commit_mem(
        plane,
        {
            "key": "mem:mcp-revise",
            "value": "source",
            "memory_type": "semantic",
            "importance": 0.2,
            "metadata": {
                "claims": [{"holder": "atakan", "subject": "Bilinc", "claim": "Bilinc tier paid", "kind": "fact"}]
            },
        },
    ))
    assert seed["success"] is True

    revised = text_payload(await _handle_revise(
        plane,
        {
            "key": "mem:mcp-revise",
            "value": "source revised",
            "importance": 0.3,
            "strategy": "recency",
            "metadata": {
                "claims": [{"holder": "atakan", "subject": "Bilinc", "claim": "Bilinc tier free", "kind": "fact"}]
            },
        },
    ))

    active = await plane.backend.list_claims(subject="Bilinc", active=True)
    inactive = await plane.backend.list_claims(subject="Bilinc", active=False)

    assert revised["success"] is True
    assert [claim.claim for claim in active] == ["Bilinc tier free"]
    assert [claim.claim for claim in inactive] == ["Bilinc tier paid"]


@pytest.mark.asyncio
async def test_mcp_revise_same_value_reprojects_explicit_metadata_claims(tmp_path):
    plane = await make_temp_plane(tmp_path)

    seed = text_payload(await _handle_commit_mem(
        plane,
        {
            "key": "mem:mcp-revise-same",
            "value": "source",
            "memory_type": "semantic",
            "importance": 0.2,
            "metadata": {
                "claims": [{"holder": "atakan", "subject": "Bilinc", "claim": "Bilinc tier paid", "kind": "fact"}]
            },
        },
    ))
    assert seed["success"] is True

    revised = text_payload(await _handle_revise(
        plane,
        {
            "key": "mem:mcp-revise-same",
            "value": "source",
            "importance": 0.3,
            "strategy": "recency",
            "metadata": {
                "claims": [{"holder": "atakan", "subject": "Bilinc", "claim": "Bilinc tier free", "kind": "fact"}],
                "custom": "updated",
            },
        },
    ))

    active = await plane.backend.list_claims(subject="Bilinc", active=True)
    inactive = await plane.backend.list_claims(subject="Bilinc", active=False)
    stored = await plane.backend.load("mem:mcp-revise-same")

    assert revised["success"] is True
    assert [claim.claim for claim in active] == ["Bilinc tier free"]
    assert [claim.claim for claim in inactive] == ["Bilinc tier paid"]
    assert stored.metadata["custom"] == "updated"


@pytest.mark.asyncio
async def test_mcp_claim_tools_list_search_and_entity(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit(
        "mem:1",
        "source",
        MemoryType.SEMANTIC,
        metadata={"claims": [{"holder": "atakan", "subject": "Bilinc", "claim": "Bilinc stores claims", "kind": "fact"}]},
    )

    listed = text_payload(await _handle_claims_list(plane, {"holder": "atakan"}))
    searched = text_payload(await _handle_claims_search(plane, {"query": "stores"}))
    entity = text_payload(await _handle_claims_for_entity(plane, {"entity": "Bilinc"}))

    assert listed["success"] is True
    assert listed["count"] == 1
    assert searched["claims"][0]["claim"] == "Bilinc stores claims"
    assert entity["claims"][0]["subject"] == "Bilinc"


@pytest.mark.asyncio
async def test_mcp_claim_contradictions_reports_read_only_findings(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit(
        "mem:active",
        "source",
        MemoryType.SEMANTIC,
        metadata={
            "claims": [
                {
                    "holder": "atakan",
                    "subject": "Bilinc",
                    "claim": "Bilinc tier paid",
                    "kind": "fact",
                    "metadata": {"predicate": "tier", "object": "paid"},
                }
            ]
        },
    )
    await plane.commit(
        "mem:free",
        "source",
        MemoryType.SEMANTIC,
        metadata={
            "claims": [
                {
                    "holder": "atakan",
                    "subject": "Bilinc",
                    "claim": "Bilinc tier free",
                    "kind": "fact",
                    "metadata": {"predicate": "tier", "object": "free"},
                }
            ]
        },
    )

    payload = text_payload(await _handle_claim_contradictions(plane, {"subject": "Bilinc"}))

    assert payload["success"] is True
    assert payload["tool"] == "claim_contradictions"
    assert payload["count"] == 1
    assert payload["findings"][0]["predicate"] == "tier"
    assert payload["read_only"] is True


def test_postgres_backend_exposes_claim_storage_methods():
    backend = PostgresBackend(dsn="postgresql://example.invalid/bilinc")

    assert callable(backend.save_claim)
    assert callable(backend.list_claims)
    assert callable(backend.search_claims)
    assert callable(backend.supersede_claim)
    assert callable(backend.record_eval_candidate)
    assert callable(backend.list_eval_candidates)


def test_postgres_row_to_claim_roundtrip_shape():
    backend = PostgresBackend(dsn="postgresql://example.invalid/bilinc")
    claim = backend._row_to_claim({
        "id": "claim_1",
        "memory_key": "mem:1",
        "holder": "atakan",
        "subject": "Bilinc",
        "claim": "Bilinc stores claims",
        "kind": "fact",
        "confidence": 0.9,
        "valid_at": None,
        "invalid_at": None,
        "source": "test",
        "provenance_id": "mem:1",
        "active": True,
        "superseded_by": None,
        "metadata": {"predicate": "stores", "object": "claims"},
        "created_at": 1.0,
        "updated_at": 2.0,
    })

    assert claim.subject == "Bilinc"
    assert claim.metadata["predicate"] == "stores"
