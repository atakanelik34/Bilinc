import json

import pytest

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.mcp_server.server_v2 import _handle_bilinc_recall_smart
from bilinc.storage.sqlite import SQLiteBackend


async def make_temp_plane(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "recall-explain.db"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    return plane


@pytest.mark.asyncio
async def test_recall_intelligent_default_omits_explain_envelope(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit("mem:bilinc", "Bilinc recall explain envelope", MemoryType.SEMANTIC)

    results = await plane.recall_intelligent("Bilinc", limit=1)

    assert results
    assert "why_retrieved" not in results[0]
    assert "provenance" not in results[0]
    assert "risk_flags" not in results[0]
    assert "supporting_claims" not in results[0]


@pytest.mark.asyncio
async def test_recall_intelligent_explain_adds_safe_envelope_and_claim_support(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit(
        "mem:bilinc",
        "Opaque payload about Bilinc",
        MemoryType.SEMANTIC,
        metadata={
            "canonical": True,
            "source_hash": "sha256:abc123",
            "provenance_id": "123e4567-e89b-12d3-a456-426614174000",
            "sensitivity": "secret",
            "private": "token-123",
            "claims": [
                {
                    "holder": "Hermes",
                    "subject": "Bilinc",
                    "claim": "Bilinc has explainable recall",
                    "kind": "fact",
                    "confidence": 0.91,
                    "source": "internal/manual-note",
                    "provenance_id": "123e4567-e89b-12d3-a456-426614174000",
                    "metadata": {"private": "claim-token-456"},
                }
            ],
        },
    )
    result = (await plane.recall_intelligent("Bilinc", limit=1, explain=True))[0]

    assert result["key"] == "mem:bilinc"
    assert any("lexical" in reason for reason in result["why_retrieved"])
    assert any("canonical" in reason for reason in result["why_retrieved"])
    assert result["provenance"]["memory_key"] == "mem:bilinc"
    assert result["provenance"]["source_hash"] == "sha256:abc123"
    assert result["provenance"]["memory_type"] == "semantic"
    assert result["provenance"]["provenance_id"] == "[REDACTED]"
    assert "private" not in result["provenance"]
    assert "sensitive_metadata" in result["risk_flags"]
    assert "graph_effect" in result
    assert result["graph_effect"]["bounded_secondary_signal"] is True
    assert result["evidence"]["supporting_claim_count"] == 1
    assert result["evidence"]["provenance_reference_present"] is True
    assert result["supporting_claims"][0]["claim"] == "Bilinc has explainable recall"
    assert result["supporting_claims"][0]["source"] == "[REDACTED]"
    assert result["supporting_claims"][0]["provenance_id"] == "[REDACTED]"
    assert "metadata" not in result["supporting_claims"][0]
    serialized = json.dumps(result)
    assert "token-123" not in serialized
    assert "claim-token-456" not in serialized
    assert "internal/manual-note" not in serialized
    assert "123e4567" not in serialized


@pytest.mark.asyncio
async def test_recall_reflective_and_profiled_propagate_explain(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit("mem:rearc", "ReARC Bilinc memory", MemoryType.SEMANTIC)

    reflective = await plane.recall_reflective("ReARC", limit=1, max_reflections=0, explain=True)
    profiled = await plane.recall_profiled("ReARC", profile="fast", limit=1, explain=True)

    assert reflective["results"][0]["why_retrieved"]
    assert profiled["results"][0]["provenance"]["memory_key"] == "mem:rearc"


@pytest.mark.asyncio
async def test_mcp_recall_smart_accepts_explain_flag(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit("mem:mcp", "Bilinc MCP explain", MemoryType.SEMANTIC)

    result = await _handle_bilinc_recall_smart(plane, {"query": "Bilinc", "limit": 1, "explain": True})
    payload = json.loads(result[0].text)

    assert payload["success"] is True
    assert payload["results"][0]["why_retrieved"]
    assert payload["results"][0]["provenance"]["memory_key"] == "mem:mcp"


@pytest.mark.asyncio
async def test_mcp_recall_smart_string_false_does_not_enable_explain(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit("mem:mcp", "Bilinc MCP explain false", MemoryType.SEMANTIC)

    result = await _handle_bilinc_recall_smart(plane, {"query": "Bilinc", "limit": 1, "explain": "false"})
    payload = json.loads(result[0].text)

    assert payload["success"] is True
    assert "why_retrieved" not in payload["results"][0]


@pytest.mark.asyncio
async def test_mcp_recall_smart_propagates_point_in_time_cutoff(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.backend.restore(
        MemoryEntry(
            key="mem:past",
            value="deployment target was past-host",
            memory_type=MemoryType.SEMANTIC,
            metadata={"event_timestamp": "2024-01-01T00:00:00Z"},
        )
    )
    await plane.backend.restore(
        MemoryEntry(
            key="mem:future",
            value="deployment target is future-host",
            memory_type=MemoryType.SEMANTIC,
            metadata={"event_timestamp": "2024-02-01T00:00:00Z"},
        )
    )

    result = await _handle_bilinc_recall_smart(
        plane,
        {
            "query": "deployment target",
            "limit": 10,
            "max_reflections": 0,
            "query_timestamp": "2024-01-15T00:00:00Z",
        },
    )
    payload = json.loads(result[0].text)

    assert payload["success"] is True
    assert [item["key"] for item in payload["results"]] == ["mem:past"]


@pytest.mark.asyncio
async def test_explain_does_not_mutate_stored_entry_access_metadata(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit("mem:readonly", "Bilinc readonly explain", MemoryType.SEMANTIC)
    before = await plane.backend.load("mem:readonly")

    await plane.recall_intelligent("Bilinc", limit=1, explain=True)
    after = await plane.backend.load("mem:readonly")

    assert after.access_count == before.access_count
    assert after.last_accessed == before.last_accessed
