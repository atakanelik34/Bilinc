"""Deterministic entity/backlink projection utilities."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from bilinc.core.models import MemoryEntry


@dataclass
class Entity:
    """Canonical entity projection derived from explicit memory metadata."""

    canonical_name: str
    entity_type: str = "unknown"
    aliases: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.canonical_name = str(self.canonical_name).strip()
        self.entity_type = str(self.entity_type or "unknown").strip() or "unknown"
        self.aliases = _dedupe([str(alias).strip() for alias in self.aliases if str(alias).strip()])
        if not self.id:
            self.id = entity_id_for(self.canonical_name)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Entity":
        return cls(**{k: v for k, v in dict(data).items() if k in cls.__dataclass_fields__})


@dataclass
class EntityMention:
    """A source-memory backlink for an entity."""

    entity_id: str
    memory_key: str
    mention_text: str
    source: str = ""
    confidence: float = 0.5
    id: str = ""
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.entity_id = str(self.entity_id).strip()
        self.memory_key = str(self.memory_key).strip()
        self.mention_text = str(self.mention_text).strip()
        self.source = str(self.source or "").strip()
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if not self.id:
            self.id = entity_mention_id_for(self.entity_id, self.memory_key, self.mention_text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EntityMention":
        return cls(**{k: v for k, v in dict(data).items() if k in cls.__dataclass_fields__})


def _normalize_name(name: str) -> str:
    return " ".join(str(name).strip().lower().split())


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = _normalize_name(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def entity_id_for(canonical_name: str) -> str:
    material = _normalize_name(canonical_name)
    return "ent_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def entity_mention_id_for(entity_id: str, memory_key: str, mention_text: str) -> str:
    material = "\x1f".join([str(entity_id), str(memory_key), _normalize_name(mention_text)])
    return "ement_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def entity_from_raw(raw: Any) -> Entity | None:
    if isinstance(raw, str):
        name = raw.strip()
        return Entity(canonical_name=name) if name else None
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or raw.get("canonical_name") or raw.get("entity") or "").strip()
    if not name:
        return None
    raw_aliases = raw.get("aliases")
    aliases: list[Any] = raw_aliases if isinstance(raw_aliases, list) else []
    raw_metadata = raw.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    return Entity(
        canonical_name=name,
        entity_type=str(raw.get("type") or raw.get("entity_type") or "unknown"),
        aliases=[str(alias) for alias in aliases],
        metadata=metadata,
    )


def _relation_entity_names(rel: Any) -> list[str]:
    names: list[str] = []
    if isinstance(rel, dict):
        for field_name in ("source", "target", "subject", "object", "entity"):
            value = rel.get(field_name)
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
    elif isinstance(rel, (list, tuple)):
        for value in rel[1:3]:
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
    return names


def _claim_entity_names(claim: Any) -> list[str]:
    if not isinstance(claim, dict):
        return []
    names: list[str] = []
    for field_name in ("holder", "subject", "entity"):
        value = claim.get(field_name)
        if isinstance(value, str) and value.strip():
            names.append(value.strip())
    return names


_CAPITALIZED_PHRASE_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,3}\b")
_STOP_PHRASES = {
    "The",
    "A",
    "An",
    "And",
    "Or",
    "But",
    "This",
    "That",
    "These",
    "Those",
    "I",
    "What",
    "When",
    "Where",
    "Why",
    "How",
    "Which",
    "Who",
    "Would",
    "Could",
    "Can",
    "Did",
    "Does",
    "Do",
    "Is",
    "Are",
    "Was",
    "Were",
    "Has",
    "Have",
}


def _safe_capitalized_phrases(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    phrases: list[str] = []
    for match in _CAPITALIZED_PHRASE_RE.findall(value):
        phrase = match.strip()
        if phrase in _STOP_PHRASES:
            continue
        if len(phrase) < 3:
            continue
        phrases.append(phrase)
    return phrases[:10]


def extract_entities_from_entry(entry: MemoryEntry) -> list[EntityMention]:
    """Extract conservative entity mentions from explicit structures plus safe proper nouns."""
    metadata = entry.metadata or {}
    entities: dict[str, Entity] = {}

    raw_entities = metadata.get("entities", [])
    if isinstance(raw_entities, (str, dict)):
        raw_entities = [raw_entities]
    if isinstance(raw_entities, list):
        for raw in raw_entities:
            entity = entity_from_raw(raw)
            if entity:
                entities[entity.id] = entity

    raw_relations = metadata.get("relations", [])
    if isinstance(raw_relations, dict):
        raw_relations = [raw_relations]
    if isinstance(raw_relations, list):
        for rel in raw_relations:
            for name in _relation_entity_names(rel):
                entity = Entity(canonical_name=name, entity_type="relation")
                entities.setdefault(entity.id, entity)

    raw_claims = metadata.get("claims", [])
    if isinstance(raw_claims, dict):
        raw_claims = [raw_claims]
    if isinstance(raw_claims, list):
        for claim in raw_claims:
            for name in _claim_entity_names(claim):
                entity = Entity(canonical_name=name, entity_type="claim")
                entities.setdefault(entity.id, entity)

    # Heuristic extraction is intentionally conservative and used for semantic
    # and episodic text without explicit structured entity, relation, or claim
    # hints. Episodic continuity needs the same entity backlinks as durable
    # facts, while the capitalized-phrase and count limits keep extraction
    # bounded and deterministic.
    if entry.memory_type.value in {"semantic", "episodic"} and not raw_entities and not raw_claims and not raw_relations:
        for name in _safe_capitalized_phrases(entry.value):
            entity = Entity(canonical_name=name, entity_type="proper_noun")
            entities.setdefault(entity.id, entity)

    heuristic_only = not raw_entities and not raw_claims and not raw_relations
    return [
        EntityMention(
            entity_id=entity.id,
            memory_key=entry.key,
            mention_text=entity.canonical_name,
            source="proper_noun_projection" if heuristic_only else "entity_projection",
            confidence=0.9 if entity.entity_type != "proper_noun" else 0.6,
        )
        for entity in entities.values()
    ]
