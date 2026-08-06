"""Neutral regression tests for entity continuity in episodic memory."""

import pytest

from bilinc.core.entities import extract_entities_from_entry
from bilinc.core.knowledge_graph import KnowledgeGraph
from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend


def test_episodic_entity_projection_is_conservative_and_deterministic():
    entry = MemoryEntry(
        key="episode:caroline",
        value="Caroline met Melanie after discussing PostgreSQL migration.",
        memory_type=MemoryType.EPISODIC,
    )

    mentions = extract_entities_from_entry(entry)

    assert {mention.mention_text for mention in mentions} >= {"Caroline", "Melanie", "PostgreSQL"}
    assert all(mention.memory_key == entry.key for mention in mentions)


def test_knowledge_graph_links_episodic_memories_by_shared_entity():
    graph = KnowledgeGraph()
    first = MemoryEntry(
        key="episode:first",
        value="Caroline discussed a migration plan with Melanie.",
        memory_type=MemoryType.EPISODIC,
    )
    second = MemoryEntry(
        key="episode:second",
        value="Caroline later confirmed the PostgreSQL migration was complete.",
        memory_type=MemoryType.EPISODIC,
    )

    first_result = graph.ingest_memory_entry(first)
    second_result = graph.ingest_memory_entry(second)

    assert first_result["entities_created"] > 0
    assert second_result["relations_created"] > 0
    assert "episode:first" in graph.query_memories_by_entity("Caroline")
    assert "episode:second" in graph.query_memories_by_entity("Caroline")
    assert graph.compute_entity_overlap_boost("What did Caroline confirm?", "episode:second") > 0


def test_common_participant_does_not_swamp_rare_entity_signal():
    plane = StatePlane()
    graph = plane.init_knowledge_graph()
    candidates = {}
    for index in range(20):
        entry = MemoryEntry(
            key=f"episode:{index}",
            value=(
                "Caroline discussed PostgreSQL migration."
                if index == 0
                else f"Caroline discussed topic {index}."
            ),
            memory_type=MemoryType.EPISODIC,
        )
        candidates[entry.key] = entry
        graph.ingest_memory_entry(entry)

    boosts = plane._compute_entity_boosts("What did Caroline say about PostgreSQL?", candidates)

    assert boosts["episode:0"] > 0
    assert boosts["episode:0"] > boosts.get("episode:1", 0.0)


def test_bounded_graph_bridge_recovers_cross_memory_continuity():
    plane = StatePlane()
    graph = plane.init_knowledge_graph(enable_graph_bridge_recall=True)
    entries = [
        MemoryEntry(
            key="episode:seed",
            value="Caroline discussed a PostgreSQL migration plan with Melanie.",
            memory_type=MemoryType.EPISODIC,
        ),
        MemoryEntry(
            key="episode:bridge",
            value="Melanie confirmed the PostgreSQL migration was complete.",
            memory_type=MemoryType.EPISODIC,
        ),
        MemoryEntry(
            key="episode:unrelated",
            value="Caroline discussed the weather with Jordan.",
            memory_type=MemoryType.EPISODIC,
        ),
        MemoryEntry(
            key="episode:other-a",
            value="Jordan planned a hiking trip with Taylor.",
            memory_type=MemoryType.EPISODIC,
        ),
        MemoryEntry(
            key="episode:other-b",
            value="Taylor prefers quiet mornings in winter.",
            memory_type=MemoryType.EPISODIC,
        ),
    ]
    for entry in entries:
        graph.ingest_memory_entry(entry)

    boosts = plane._compute_entity_boosts(
        "What did Caroline discuss?",
        {entry.key: entry for entry in entries},
    )

    assert boosts["episode:seed"] > 0
    assert boosts["episode:bridge"] > 0
    assert boosts["episode:bridge"] < boosts["episode:seed"]

    protected = plane._compute_entity_boosts(
        "What did Caroline discuss?",
        {entry.key: entry for entry in entries},
        bridge_protected_keys={"episode:bridge"},
    )
    assert protected["episode:bridge"] == 0


def test_graph_bridge_is_bounded_for_common_entities():
    graph = KnowledgeGraph(max_cross_memory_links_per_entity=2, max_cross_memory_links_per_entry=3)
    for index in range(8):
        graph.ingest_memory_entry(
            MemoryEntry(
                key=f"episode:{index}",
                value=f"Caroline discussed topic {index} with Melanie.",
                memory_type=MemoryType.EPISODIC,
            )
        )

    cross_edges = [
        edge for edge in graph._edges
        if edge.metadata.get("cross_memory") is True
    ]
    assert len(cross_edges) <= 8 * 3


def test_stateplane_graph_supports_index_only_materialization():
    plane = StatePlane()
    graph = plane.init_knowledge_graph(materialize_cross_memory_links=False)

    assert graph.max_cross_memory_links_per_entity == 0
    assert graph.max_cross_memory_links_per_entry == 0
    assert plane.enable_graph_bridge_recall is False

    graph.ingest_memory_entry(
        MemoryEntry(
            key="episode:one",
            value="Caroline discussed Bilinc with Melanie.",
            memory_type=MemoryType.EPISODIC,
        )
    )
    graph.ingest_memory_entry(
        MemoryEntry(
            key="episode:two",
            value="Melanie confirmed Bilinc was ready.",
            memory_type=MemoryType.EPISODIC,
        )
    )

    assert graph.query_memories_by_entity("Melanie") == ["episode:one", "episode:two"]
    assert not any(edge.metadata.get("cross_memory") for edge in graph._edges)


@pytest.mark.asyncio
async def test_stateplane_projects_episodic_entities_to_graph_and_sqlite(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "episodic-entities.sqlite"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()

    await plane.commit_with_agm_async(
        key="episode:caroline",
        value="Caroline prefers PostgreSQL for durable state.",
        memory_type="episodic",
        metadata={"session_id": "session-a"},
        source="neutral-test",
    )

    assert "Caroline" in plane.knowledge_graph.memory_entities("episode:caroline")
    mentions = await backend.list_entity_mentions(memory_key="episode:caroline")
    assert {mention.mention_text for mention in mentions} >= {"Caroline", "PostgreSQL"}

    results = await plane.recall_intelligent("What does Caroline prefer?", limit=5)
    assert results
    assert results[0]["key"] == "episode:caroline"


@pytest.mark.asyncio
async def test_stateplane_updates_explicit_graph_without_agm(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "episodic-entities-no-agm.sqlite"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    plane.init_knowledge_graph()

    await plane.commit_with_agm_async(
        key="episode:caroline",
        value="Caroline prefers PostgreSQL for durable state.",
        memory_type="episodic",
        source="neutral-test",
    )

    assert "Caroline" in plane.knowledge_graph.memory_entities("episode:caroline")
    results = await plane.recall_intelligent("What does Caroline prefer?", limit=5)
    assert results
    assert results[0]["key"] == "episode:caroline"
