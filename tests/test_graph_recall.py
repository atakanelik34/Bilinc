"""Neutral tests for bounded graph-assisted retrieval."""

import pytest

from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend


@pytest.mark.asyncio
async def test_recall_intelligent_expands_from_entity_seed_without_global_broadening(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_GRAPH_RECALL", "1")
    backend = SQLiteBackend(str(tmp_path / "graph-recall.sqlite"))
    plane = StatePlane(backend=backend)
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()

    await plane.commit_with_agm_async(
        "mem_a",
        "ReARC builds Atlas.",
        memory_type="semantic",
        importance=0.8,
    )
    await plane.commit_with_agm_async(
        "mem_b",
        "Atlas hosts Bilinc.",
        memory_type="semantic",
        importance=0.8,
    )
    await plane.commit_with_agm_async(
        "mem_unrelated",
        "Orion measures latency.",
        memory_type="semantic",
        importance=0.8,
    )

    results = await plane.recall_intelligent("ReARC", limit=3)
    keys = [item["key"] for item in results]

    assert "mem_a" in keys
    assert "mem_b" in keys
    assert "mem_unrelated" not in keys
    assert any(item["signals"].get("graph", 0.0) > 0 for item in results if item["key"] == "mem_b")

    await backend.close()
