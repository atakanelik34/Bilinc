import pytest

from bilinc.core.stateplane import StatePlane
from bilinc.core.entities import (
    Entity,
    EntityMention,
    entity_id_for,
    extract_entities_from_entry,
)
from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.storage.sqlite import SQLiteBackend


async def make_temp_plane(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "entities.db"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    return plane


def test_entity_id_is_stable():
    assert entity_id_for("ReARC Labs") == entity_id_for("rearc labs")
    assert entity_id_for("ReARC Labs").startswith("ent_")


def test_entity_models_defaults():
    entity = Entity(canonical_name="Bilinc", entity_type="product", aliases=["bilinc"])
    mention = EntityMention(entity_id=entity.id, memory_key="mem:1", mention_text="Bilinc", confidence=0.9)

    assert entity.id
    assert entity.metadata == {}
    assert mention.id
    assert mention.source == ""


@pytest.mark.asyncio
async def test_entities_tables_exist(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "entities.db"))
    await backend.init()

    conn = backend._get_conn()
    entities = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='entities'").fetchone()
    mentions = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='entity_mentions'").fetchone()

    assert entities is not None
    assert mentions is not None


@pytest.mark.asyncio
async def test_save_find_entity_add_alias_and_mentions(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "entities.db"))
    await backend.init()
    entity = Entity(canonical_name="ReARC Labs", entity_type="company", aliases=["ReARC"])
    mention = EntityMention(entity_id=entity.id, memory_key="mem:1", mention_text="ReARC", source="metadata")

    await backend.save_entity(entity)
    await backend.add_entity_alias(entity.id, "Rearclabs")
    await backend.save_entity_mention(mention)

    found = await backend.find_entity("rearclabs")
    mentions = await backend.list_entity_mentions(entity_id=entity.id)
    memories = await backend.list_memories_for_entity("ReARC Labs")

    assert found is not None
    assert found.id == entity.id
    assert "Rearclabs" in found.aliases
    assert [m.memory_key for m in mentions] == ["mem:1"]
    assert memories == ["mem:1"]


def test_extract_entities_from_metadata_and_relations():
    entry = MemoryEntry(
        key="mem:entities",
        value="source",
        memory_type=MemoryType.SEMANTIC,
        metadata={
            "entities": [
                {"name": "Bilinc", "type": "product", "aliases": ["bilinc memory"]},
                "ReARC Labs",
            ],
            "relations": [{"source": "Bilinc", "target": "ARES", "type": "related_to"}],
        },
    )

    mentions = extract_entities_from_entry(entry)
    names = {mention.mention_text for mention in mentions}

    assert {"Bilinc", "ReARC Labs", "ARES"}.issubset(names)
    assert all(mention.memory_key == "mem:entities" for mention in mentions)


def test_extract_entities_from_claim_subject_and_holder():
    entry = MemoryEntry(
        key="mem:claim",
        value="source",
        memory_type=MemoryType.SEMANTIC,
        metadata={"claims": [{"holder": "Atakan", "subject": "Bilinc", "claim": "Bilinc has recall profiles"}]},
    )

    names = {mention.mention_text for mention in extract_entities_from_entry(entry)}

    assert "Atakan" in names
    assert "Bilinc" in names


def test_extract_entities_ignores_boring_lowercase_text():
    entry = MemoryEntry(key="mem:boring", value="this is just lowercase prose", memory_type=MemoryType.SEMANTIC)

    assert extract_entities_from_entry(entry) == []


@pytest.mark.asyncio
async def test_commit_projects_entities_and_cleans_stale_mentions(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit("mem:1", "source", MemoryType.SEMANTIC, metadata={"entities": ["Bilinc"]})
    await plane.commit("mem:1", "source", MemoryType.SEMANTIC, metadata={"entities": ["ARES"]})

    bilinc_mentions = await plane.backend.list_memories_for_entity("Bilinc")
    ares_mentions = await plane.backend.list_memories_for_entity("ARES")

    assert bilinc_mentions == []
    assert ares_mentions == ["mem:1"]


@pytest.mark.asyncio
async def test_delete_removes_entity_mentions(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit("mem:delete", "source", MemoryType.SEMANTIC, metadata={"entities": ["Bilinc"]})

    assert await plane.backend.list_memories_for_entity("Bilinc") == ["mem:delete"]
    assert await plane.backend.delete("mem:delete") is True
    assert await plane.backend.list_memories_for_entity("Bilinc") == []
    assert await plane.backend.find_entity("Bilinc") is None


@pytest.mark.asyncio
async def test_commit_update_prunes_orphaned_entity_rows(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit(
        "mem:secret",
        "source",
        MemoryType.SEMANTIC,
        metadata={"entities": [{"name": "Old Secret", "aliases": ["OS"], "metadata": {"private": "token-123"}}]},
    )
    await plane.commit("mem:secret", "source", MemoryType.SEMANTIC, metadata={"entities": ["New Public"]})

    assert await plane.backend.find_entity("Old Secret") is None
    assert await plane.backend.find_entity("OS") is None
    assert await plane.backend.list_memories_for_entity("New Public") == ["mem:secret"]


@pytest.mark.asyncio
async def test_delete_prunes_orphaned_entity_metadata(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit(
        "mem:private-entity",
        "source",
        MemoryType.SEMANTIC,
        metadata={"entities": [{"name": "Secret Customer X", "aliases": ["SCX"], "metadata": {"private": "token-123"}}]},
    )

    assert await plane.backend.delete("mem:private-entity") is True

    assert await plane.backend.find_entity("Secret Customer X") is None
    assert await plane.backend.find_entity("SCX") is None


@pytest.mark.asyncio
async def test_entity_recall_returns_memory_through_metadata_entity_seed(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit(
        "mem:opaque",
        "zzzz qqqq hidden payload",
        MemoryType.SEMANTIC,
        metadata={"entities": [{"name": "Aperture Labs", "type": "company"}]},
    )

    results = await plane.recall_intelligent("Aperture Labs", limit=3)

    assert results[0]["key"] == "mem:opaque"
    assert results[0]["signals"]["entity"] > 0


def test_explicit_relations_suppress_proper_noun_fallback_noise():
    entry = MemoryEntry(
        key="mem:relations",
        value="Deploy The Test Harness On Monday",
        memory_type=MemoryType.SEMANTIC,
        metadata={"relations": [{"source": "Bilinc", "target": "ARES", "type": "related_to"}]},
    )

    names = {mention.mention_text for mention in extract_entities_from_entry(entry)}

    assert names == {"Bilinc", "ARES"}
