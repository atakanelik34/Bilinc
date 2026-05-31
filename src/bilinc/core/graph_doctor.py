"""Read-only graph projection diagnostics for Bilinc memories.

This module deliberately does not mutate ``KnowledgeGraph`` or any backend.  It
turns memory entries into deterministic candidate nodes/edges so operators can
see what a richer graph projection would produce before approving backfills or
schema changes.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from bilinc.core.models import MemoryEntry, MemoryType


def _normalize_name(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _dedupe_key(value: Any) -> str:
    return _normalize_name(value).casefold()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _timestamp_in_past(value: Any, now: float | None) -> bool:
    if now is None:
        return False
    if value is None:
        return False
    try:
        return float(value) < now
    except (TypeError, ValueError):
        return False


def _extract_capitalized_entities(text: Any) -> list[str]:
    tokens = re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", str(text or ""))
    stop = {"the", "and", "for", "that", "this", "with", "from", "have"}
    seen: set[str] = set()
    entities: list[str] = []
    for token in tokens:
        if _looks_sensitive_token(token):
            continue
        normalized = token.casefold()
        if normalized in stop or normalized in seen:
            continue
        seen.add(normalized)
        entities.append(token)
    return entities


def _looks_sensitive_token(token: str) -> bool:
    """Suppress obvious credential/opaque-ID candidates from preview output."""
    cleaned = str(token or "").strip()
    upper = cleaned.upper()
    lowered = cleaned.lower()
    sensitive_markers = ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "PRIVATE_KEY", "BEARER")
    if any(marker in upper for marker in sensitive_markers):
        return True
    if upper.startswith(("AKIA", "ASIA", "SK_", "PYPI_")):
        return True
    if len(cleaned) >= 16 and re.fullmatch(r"[A-Za-z0-9_-]+", cleaned):
        has_alpha = any(ch.isalpha() for ch in cleaned)
        has_digit = any(ch.isdigit() for ch in cleaned)
        mostly_upper = sum(1 for ch in cleaned if ch.isupper()) >= max(8, len(cleaned) // 2)
        if has_alpha and (has_digit or mostly_upper):
            return True
    return lowered.startswith(("secret", "token", "password"))


def _claim_items(metadata: dict[str, Any]) -> list[Any]:
    raw_claims = metadata.get("claims", []) if isinstance(metadata, dict) else []
    if isinstance(raw_claims, dict):
        return [raw_claims]
    if isinstance(raw_claims, list):
        return raw_claims
    return []


class _PreviewBuilder:
    def __init__(self, now: float | None):
        self.now = now
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
        self._node_keys: set[tuple[str, str, str]] = set()
        self._edge_keys: set[tuple[str, str, str, str]] = set()
        self._names_by_norm: dict[str, set[str]] = {}
        self.claim_count = 0
        self.memories_with_projection = 0
        self.memories_without_projection = 0

    def node(self, name: Any, node_type: str, source: str, metadata: dict[str, Any] | None = None) -> None:
        normalized_name = _normalize_name(name)
        if not normalized_name:
            return
        normalized_key = _dedupe_key(normalized_name)
        self._names_by_norm.setdefault(normalized_key, set()).add(normalized_name)
        key = (normalized_key, node_type, source)
        if key in self._node_keys:
            return
        self._node_keys.add(key)
        self.nodes.append({
            "name": normalized_name,
            "node_type": node_type,
            "source": source,
            "metadata": metadata or {},
        })

    def edge(
        self,
        source: Any,
        target: Any,
        relation_type: str,
        source_label: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        normalized_source = _normalize_name(source)
        normalized_target = _normalize_name(target)
        if not normalized_source or not normalized_target:
            return
        key = (_dedupe_key(normalized_source), _dedupe_key(normalized_target), relation_type, source_label)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.edges.append({
            "source": normalized_source,
            "target": normalized_target,
            "relation_type": relation_type,
            "metadata": {"source": source_label, **(metadata or {})},
        })

    def duplicate_alias_issues(self) -> None:
        for names in self._names_by_norm.values():
            if len(names) <= 1:
                continue
            self.issues.append({
                "type": "possible_duplicate_entity",
                "names": sorted(names),
                "reason": "case_or_whitespace_alias_collision",
            })


def preview_projection(entries: Iterable[MemoryEntry], now: float | None = None) -> dict[str, Any]:
    """Preview deterministic graph projection candidates for memory entries.

    The function is intentionally read-only. It returns candidate nodes, edges,
    and doctor issues that a later apply/backfill path can inspect.
    """

    timestamp = None if now is None else float(now)
    builder = _PreviewBuilder(now=timestamp)
    materialized = list(entries or [])

    for entry in materialized:
        before_nodes = len(builder.nodes)
        before_edges = len(builder.edges)
        metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
        memory_key = _normalize_name(entry.key)
        memory_metadata = {
            "memory_key": memory_key,
            "memory_type": entry.memory_type.value if hasattr(entry.memory_type, "value") else str(entry.memory_type),
            "source": entry.source,
            "importance": entry.importance,
        }

        if entry.memory_type == MemoryType.SEMANTIC and memory_key:
            builder.node(memory_key, "fact", "memory_key", memory_metadata)

        for product in _as_list(metadata.get("product")):
            product_name = _normalize_name(product)
            if not product_name or not memory_key:
                continue
            builder.node(product_name, "entity", "metadata.product", {"memory_key": memory_key})
            builder.edge(memory_key, product_name, "related_to", "metadata.product", {"memory_key": memory_key})

        for concern in _as_list(metadata.get("concerns")):
            concern_name = _normalize_name(concern)
            if not concern_name or not memory_key:
                continue
            builder.node(concern_name, "entity", "metadata.concerns", {"memory_key": memory_key})
            builder.edge(memory_key, concern_name, "related_to", "metadata.concerns", {"memory_key": memory_key})

        for raw_entity in _as_list(metadata.get("entities")):
            entity_name = ""
            entity_source = "metadata.entities"
            if isinstance(raw_entity, dict):
                entity_name = _normalize_name(raw_entity.get("canonical_name") or raw_entity.get("name") or raw_entity.get("entity"))
            else:
                entity_name = _normalize_name(raw_entity)
            if not entity_name or not memory_key:
                continue
            builder.node(entity_name, "entity", entity_source, {"memory_key": memory_key})
            builder.edge(memory_key, entity_name, "related_to", entity_source, {"memory_key": memory_key})

        if entry.memory_type == MemoryType.SEMANTIC:
            for entity_name in _extract_capitalized_entities(entry.value):
                if not memory_key:
                    continue
                builder.node(entity_name, "entity", "value.capitalized", {"memory_key": memory_key})
                builder.edge(memory_key, entity_name, "related_to", "value.capitalized", {"memory_key": memory_key})

        for index, raw_claim in enumerate(_claim_items(metadata)):
            if not isinstance(raw_claim, dict):
                builder.issues.append({
                    "type": "malformed_claim",
                    "memory_key": memory_key,
                    "claim_index": index,
                    "reason": "claim is not an object",
                })
                continue
            holder = _normalize_name(raw_claim.get("holder"))
            subject = _normalize_name(raw_claim.get("subject") or raw_claim.get("entity"))
            claim_text = _normalize_name(raw_claim.get("claim") or raw_claim.get("text"))
            if not holder or not subject or not claim_text:
                builder.issues.append({
                    "type": "malformed_claim",
                    "memory_key": memory_key,
                    "claim_index": index,
                    "reason": "missing holder/subject/claim",
                })
                continue

            builder.claim_count += 1
            provenance_id = _normalize_name(raw_claim.get("provenance_id") or memory_key)
            active = not _timestamp_in_past(raw_claim.get("invalid_at"), timestamp)
            claim_metadata = {
                "memory_key": memory_key,
                "provenance_id": provenance_id,
                "claim": claim_text,
                "kind": _normalize_name(raw_claim.get("kind") or "fact"),
                "confidence": raw_claim.get("confidence", 0.5),
                "valid_at": raw_claim.get("valid_at"),
                "invalid_at": raw_claim.get("invalid_at"),
                "active": active,
            }
            builder.node(holder, "entity", "claim.holder", {"memory_key": memory_key})
            builder.node(subject, "entity", "claim.subject", {"memory_key": memory_key})
            builder.edge(holder, subject, "supports" if active else "related_to", "metadata.claims", claim_metadata)
            if provenance_id:
                builder.node(provenance_id, "fact", "claim.provenance_id", {"memory_key": memory_key})
                builder.edge(provenance_id, subject, "supports", "claim.provenance_id", claim_metadata)
            if not active:
                builder.issues.append({
                    "type": "expired_claim",
                    "memory_key": memory_key,
                    "claim_index": index,
                    "invalid_at": raw_claim.get("invalid_at"),
                    "reason": "claim invalid_at is in the past",
                })

        if len(builder.nodes) == before_nodes and len(builder.edges) == before_edges:
            builder.memories_without_projection += 1
            builder.issues.append({
                "type": "no_projection_candidates",
                "memory_key": memory_key,
                "reason": "no deterministic metadata, claim, entity, or semantic projection candidates",
            })
        else:
            builder.memories_with_projection += 1

    builder.duplicate_alias_issues()
    return {
        "read_only": True,
        "memory_count": len(materialized),
        "candidate_nodes": builder.nodes,
        "candidate_edges": builder.edges,
        "issues": builder.issues,
        "stats": {
            "candidate_node_count": len(builder.nodes),
            "candidate_edge_count": len(builder.edges),
            "claim_count": builder.claim_count,
            "memories_with_projection": builder.memories_with_projection,
            "memories_without_projection": builder.memories_without_projection,
        },
    }
