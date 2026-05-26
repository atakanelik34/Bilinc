"""
Knowledge Graph Layer

Lightweight, NetworkX-backed knowledge graph for semantic memory integration.
No external DB required — runs in-memory and serializes to JSON.

Node types: Entity, Fact, Event, Skill
Edge types: related_to, causes, contradicts, supports, temporal_before
"""

from __future__ import annotations

import json
import time
import re
from collections import defaultdict
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import networkx as nx
except ImportError:
    nx = None

from bilinc.core.models import MemoryEntry, MemoryType


# ─── Enums ─────────────────────────────────────────────────────

class NodeType(str, Enum):
    ENTITY = "entity"
    FACT = "fact"
    EVENT = "event"
    SKILL = "skill"


class EdgeType(str, Enum):
    RELATED_TO = "related_to"
    CAUSES = "causes"
    CONTRADICTS = "contradicts"
    SUPPORTS = "supports"
    TEMPORAL_BEFORE = "temporal_before"


# ─── Data Classes ──────────────────────────────────────────────

@dataclass
class KGNode:
    """A single node in the knowledge graph."""
    name: str
    node_type: NodeType
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "node_type": self.node_type.value,
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KGNode":
        return cls(
            name=data["name"],
            node_type=NodeType(data["node_type"]),
            properties=data.get("properties", {}),
        )


@dataclass
class KGEdge:
    """A relation between two nodes."""
    source: str
    target: str
    relation_type: EdgeType
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation_type": self.relation_type.value,
            "weight": self.weight,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KGEdge":
        return cls(
            source=data["source"],
            target=data["target"],
            relation_type=EdgeType(data["relation_type"]),
            weight=data.get("weight", 1.0),
            metadata=data.get("metadata", {}),
        )


# ─── Knowledge Graph ───────────────────────────────────────────

class KnowledgeGraph:
    """
    NetworkX-backed knowledge graph for Bilinc.
    
    - Lightweight: no external DB required
    - Serializable: export/import to JSON
    - Semantic aware: auto-creates entities from MemoryEntry commits
    - Contradiction-aware: flags conflicting edges
    """

    def __init__(self):
        self.graph = nx.MultiDiGraph()
        self._nodes: Dict[str, KGNode] = {}
        self._edges: List[KGEdge] = []
        self._entity_to_memories: Dict[str, Set[str]] = defaultdict(set)
        self._memory_to_entities: Dict[str, Set[str]] = defaultdict(set)
        self._created_at = time.time()
        self._updated_at = time.time()

    # ─── Node Operations ───────────────────────────────────────

    def add_entity(
        self,
        name: str,
        entity_type: NodeType = NodeType.ENTITY,
        properties: Optional[Dict[str, Any]] = None,
    ) -> KGNode:
        """Add a node to the graph."""
        if name in self._nodes:
            # Update existing
            node = self._nodes[name]
            if properties:
                node.properties.update(properties)
            # Update graph too
            if self.graph.has_node(name):
                self.graph.nodes[name]["properties"] = node.properties
        else:
            node = KGNode(name=name, node_type=entity_type, properties=properties or {})
            self._nodes[name] = node
            self.graph.add_node(name, **node.to_dict())

        self._updated_at = time.time()
        return node

    def query_entity(self, name: str) -> Optional[KGNode]:
        """Get a node by name."""
        return self._nodes.get(name)

    def remove_entity(self, name: str) -> bool:
        """Remove a node and all its edges."""
        if name not in self._nodes:
            return False
        node = self._nodes.pop(name)
        self.graph.remove_node(name)
        self._edges = [e for e in self._edges if e.source != name and e.target != name]
        self._updated_at = time.time()
        return True

    # ─── Edge Operations ───────────────────────────────────────

    def add_relation(
        self,
        source: str,
        target: str,
        relation_type: EdgeType = EdgeType.RELATED_TO,
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KGEdge:
        """Add a relation between two nodes."""
        # Auto-create nodes if missing
        if source not in self._nodes:
            self.add_entity(source, NodeType.ENTITY)
        if target not in self._nodes:
            self.add_entity(target, NodeType.ENTITY)

        edge = KGEdge(
            source=source,
            target=target,
            relation_type=relation_type,
            weight=weight,
            metadata=metadata or {},
        )
        self._edges.append(edge)
        self.graph.add_edge(source, target, **edge.to_dict())
        self._updated_at = time.time()
        return edge

    def _has_relation(
        self,
        source: str,
        target: str,
        relation_type: EdgeType,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> bool:
        for edge in self._edges:
            if edge.source != source or edge.target != target or edge.relation_type != relation_type:
                continue
            if not metadata_filter:
                return True
            if all(edge.metadata.get(k) == v for k, v in metadata_filter.items()):
                return True
        return False

    def _extract_entities_from_text(self, text: str) -> Set[str]:
        capitalized = set(re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", text))
        return {
            token
            for token in capitalized
            if token.lower() not in {"the", "and", "for", "that", "this", "with", "from", "have"}
        }

    def _extract_kv_pairs(self, text: str) -> List[Tuple[str, str]]:
        return re.findall(r"([a-z_]+)\s*[=:]\s*([^,\n]+)", text)

    def _index_memory_entities(self, memory_key: str, entities: Set[str]) -> None:
        if not memory_key or not entities:
            return
        self._memory_to_entities[memory_key].update(entities)
        for entity in entities:
            self._entity_to_memories[entity].add(memory_key)

    def query_memories_by_entity(self, entity: str, limit: int = 20) -> List[str]:
        """Return memory keys linked to an entity."""
        if not entity:
            return []
        keys = sorted(self._entity_to_memories.get(entity, set()))
        return keys[: max(limit, 0)]

    def memory_entities(self, memory_key: str) -> List[str]:
        """Return entities linked to a memory key."""
        if not memory_key:
            return []
        return sorted(self._memory_to_entities.get(memory_key, set()))

    def compute_entity_overlap_boost(
        self,
        query_text: str,
        memory_key: str,
        boost_per_match: float = 0.2,
        max_boost: float = 0.4,
    ) -> float:
        """
        Compute retrieval boost based on entity overlap between query and memory.
        Returns 0.0 when no overlap is found.
        """
        if not query_text or not memory_key:
            return 0.0
        query_entities = self._extract_entities_from_text(str(query_text))
        memory_entities = self._memory_to_entities.get(memory_key, set())
        overlap = query_entities.intersection(memory_entities)
        if not overlap:
            return 0.0
        return min(max_boost, len(overlap) * boost_per_match)

    def remove_relation(self, source: str, target: str, relation_type: Optional[EdgeType] = None) -> bool:
        """Remove a relation between two nodes."""
        removed = False
        if self.graph.has_edge(source, target):
            self.graph.remove_edge(source, target)
            self._edges = [
                e for e in self._edges
                if not (e.source == source and e.target == target and (relation_type is None or e.relation_type == relation_type))
            ]
            removed = True
            self._updated_at = time.time()
        return removed

    # ─── Query/Traversal ───────────────────────────────────────

    def traverse(
        self,
        start: str,
        max_depth: int = 3,
        relation_filter: Optional[List[EdgeType]] = None,
    ) -> Dict[str, Any]:
        """
        Traverse the graph from a starting node, up to max_depth.
        Returns subgraph as dict with nodes and edges.
        """
        if start not in self.graph:
            return {"nodes": [], "edges": []}

        # BFS with depth limit
        visited: Set[str] = set()
        queue: List[Tuple[str, int]] = [(start, 0)]
        found_nodes: List[str] = []
        found_edges: List[Dict[str, Any]] = []

        while queue:
            node, depth = queue.pop(0)
            if node in visited or depth > max_depth:
                continue
            visited.add(node)
            found_nodes.append(node)

            if depth < max_depth:
                for neighbor in self.graph.successors(node):
                    # Check relation filter
                    edge_data = self.graph[node][neighbor]
                    for edge_key, edge_attrs in edge_data.items():
                        if relation_filter:
                            etype = edge_attrs.get("relation_type")
                            if etype and EdgeType(etype) not in relation_filter:
                                continue
                        found_edges.append(edge_attrs)

                    if neighbor not in visited:
                        queue.append((neighbor, depth + 1))

        return {
            "nodes": [self._nodes[n].to_dict() for n in found_nodes if n in self._nodes],
            "edges": found_edges,
            "depth": max_depth,
            "start": start,
        }

    def get_relations(
        self,
        node_name: str,
        relation_filter: Optional[List[EdgeType]] = None,
    ) -> List[Dict[str, Any]]:
        """Get all relations for a specific node."""
        relations = []
        if node_name not in self.graph:
            return relations

        for neighbor in self.graph.successors(node_name):
            edge_data = self.graph[node_name][neighbor]
            for edge_key, edge_attrs in edge_data.items():
                if relation_filter:
                    etype = edge_attrs.get("relation_type")
                    if etype and EdgeType(etype) not in relation_filter:
                        continue
                relations.append(edge_attrs)

        return relations

    # ─── Contradiction Detection ───────────────────────────────

    def find_contradictions(self) -> List[Dict[str, Any]]:
        """
        Find all pairs of edges that contradict each other.
        
        Contradiction = same source->target pair with both
        'supports' AND 'contradicts', OR same entity with 
        conflicting property values.

        Uses an index dict keyed by (source, target) pair to avoid
        the previous O(n^2) nested scan over all edges.
        """
        from collections import defaultdict

        # Build index: O(n) single pass
        pair_index: Dict[Tuple[str, str], List[KGEdge]] = defaultdict(list)
        for edge in self._edges:
            pair_index[(edge.source, edge.target)].append(edge)

        contradictions: List[Dict[str, Any]] = []

        for pair_key, same_pair in pair_index.items():
            has_supports = any(e.relation_type == EdgeType.SUPPORTS for e in same_pair)
            has_contradicts = any(e.relation_type == EdgeType.CONTRADICTS for e in same_pair)

            if has_supports and has_contradicts:
                contradictions.append({
                    "type": "relation_conflict",
                    "source": pair_key[0],
                    "target": pair_key[1],
                    "edges": [e.to_dict() for e in same_pair],
                })
            elif has_contradicts:
                contradictions.append({
                    "type": "direct_contradiction",
                    "source": pair_key[0],
                    "target": pair_key[1],
                    "edges": [e.to_dict() for e in same_pair],
                })

        return contradictions

    # ─── Semantic Memory Integration ───────────────────────────

    def ingest_memory_entry(self, entry: MemoryEntry) -> Dict[str, int]:
        """
        Auto-extract entities and relations from a MemoryEntry.
        
        Simple NLP: capitalized words → entities, co-occurrence → relations.
        Returns count of entities and relations created.
        """
        entities_created = 0
        relations_created = 0

        if entry.memory_type == MemoryType.SEMANTIC:
            text = str(entry.value)
            candidates = self._extract_entities_from_text(text)
            kv_pairs = self._extract_kv_pairs(text)
            shared_entities = set(candidates)

            # Add the main entry key as an entity
            if entry.key:
                self.add_entity(entry.key, NodeType.FACT, {
                    "value": str(entry.value)[:500],
                    "source": entry.source,
                    "importance": entry.importance,
                    "created_at": entry.created_at,
                    "is_verified": entry.is_verified,
                })
                entities_created += 1

            # Add capitalized words as entities
            for cap_word in candidates:
                self.add_entity(cap_word, NodeType.ENTITY)
                entities_created += 1

                # Relate to the main entry
                if entry.key:
                    self.add_relation(entry.key, cap_word, EdgeType.RELATED_TO, weight=0.5)
                    relations_created += 1

            # Add key-value pairs as fact entities
            for k, v in kv_pairs:
                self.add_entity(k, NodeType.FACT, {"value": v.strip()})
                entities_created += 1
                shared_entities.add(k)
                if entry.key:
                    self.add_relation(entry.key, k, EdgeType.SUPPORTS, weight=0.8)
                    relations_created += 1

            if entry.key:
                # Cross-memory links: connect memories sharing any extracted entity.
                linked_memories: Set[str] = set()
                for entity_name in shared_entities:
                    linked_memories.update(self._entity_to_memories.get(entity_name, set()))
                linked_memories.discard(entry.key)

                for other_memory_key in linked_memories:
                    metadata = {"cross_memory": True}
                    if not self._has_relation(entry.key, other_memory_key, EdgeType.RELATED_TO, metadata):
                        self.add_relation(
                            entry.key,
                            other_memory_key,
                            EdgeType.RELATED_TO,
                            weight=0.6,
                            metadata=metadata,
                        )
                        relations_created += 1

                self._index_memory_entities(entry.key, shared_entities)

        return {"entities_created": entities_created, "relations_created": relations_created}

    # ─── Serialization ─────────────────────────────────────────

    def export_to_json(self) -> Dict[str, Any]:
        """Export the entire knowledge graph to a serializable dict."""
        return {
            "nodes": [node.to_dict() for node in self._nodes.values()],
            "edges": [edge.to_dict() for edge in self._edges],
            "stats": {
                "node_count": len(self._nodes),
                "edge_count": len(self._edges),
                "created_at": self._created_at,
                "updated_at": self._updated_at,
                "contradictions": len(self.find_contradictions()),
            },
        }

    def import_from_json(self, data: Dict[str, Any]) -> None:
        """Import a knowledge graph from a serialized dict."""
        self.graph = nx.MultiDiGraph()
        self._nodes = {}
        self._edges = []
        self._entity_to_memories = defaultdict(set)
        self._memory_to_entities = defaultdict(set)

        # Rebuild nodes
        for node_data in data.get("nodes", []):
            node = KGNode.from_dict(node_data)
            self._nodes[node.name] = node
            self.graph.add_node(node.name, **node.to_dict())

        # Rebuild edges
        for edge_data in data.get("edges", []):
            edge = KGEdge.from_dict(edge_data)
            self._edges.append(edge)
            self.graph.add_edge(edge.source, edge.target, **edge.to_dict())

        # Rebuild entity-memory index from explicit cross references and node metadata.
        for source_key, node in self._nodes.items():
            if node.node_type != NodeType.FACT:
                continue
            for edge in self.get_relations(source_key):
                if edge.get("relation_type") != EdgeType.RELATED_TO.value:
                    continue
                target = edge.get("target")
                if target and target in self._nodes and self._nodes[target].node_type == NodeType.ENTITY:
                    self._memory_to_entities[source_key].add(target)
                    self._entity_to_memories[target].add(source_key)

        self._created_at = data.get("stats", {}).get("created_at", time.time())
        self._updated_at = time.time()

    @property
    def stats(self) -> Dict[str, Any]:
        """Quick stats about the graph."""
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "entity_links": sum(len(v) for v in self._entity_to_memories.values()),
            "contradictions": len(self.find_contradictions()),
            "density": nx.density(self.graph) if self.graph.number_of_nodes() > 0 else 0.0,
        }
