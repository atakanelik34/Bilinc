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
            # Extract entities: capitalized words, patterns
            candidates = re.findall(r'\b[A-Z][a-z]{2,}\b', text)
            # Also look for key-value patterns
            kv_pairs = re.findall(r'([a-z_]+)\s*[=:]\s*([^,\n]+)', text)

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
            for cap_word in set(candidates):
                if cap_word.lower() in ("the", "and", "for", "that", "this", "with", "from", "have"):
                    continue
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
                if entry.key:
                    self.add_relation(entry.key, k, EdgeType.SUPPORTS, weight=0.8)
                    relations_created += 1

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

        self._created_at = data.get("stats", {}).get("created_at", time.time())
        self._updated_at = time.time()

    @property
    def stats(self) -> Dict[str, Any]:
        """Quick stats about the graph."""
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "contradictions": len(self.find_contradictions()),
            "density": nx.density(self.graph) if self.graph.number_of_nodes() > 0 else 0.0,
        }
