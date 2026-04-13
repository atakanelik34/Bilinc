"""
Knowledge Graph Enhanced Retrieval for Bilinc.

HippoRAG-inspired spreading activation through the knowledge graph.
Uses Personalized PageRank-style activation with decay per hop.

ORIGINAL implementation. Not copied from any codebase.
"""
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field


@dataclass
class ActivationResult:
    """Result of spreading activation from seed nodes."""
    node_key: str
    activation_score: float
    hops: int
    path: List[str] = field(default_factory=list)

    def to_dict(self):
        return {"node": self.node_key, "score": round(self.activation_score, 4),
                "hops": self.hops, "path": self.path}


class KGSpreadingActivation:
    """
    Spreading activation through Bilinc's knowledge graph.

    Given seed nodes (from query matching), activation spreads through
    relations with decay. Higher-activation nodes are more relevant to
    the original query.

    Based on:
    - HippoRAG's Personalized PageRank (arxiv 2405.14831)
    - Collins & Loftus (1975) spreading activation theory
    """

    def __init__(self, conn, decay_per_hop: float = 0.5, max_hops: int = 3, min_activation: float = 0.1):
        self.conn = conn
        self.decay_per_hop = decay_per_hop
        self.max_hops = max_hops
        self.min_activation = min_activation

    def spread(self, seed_nodes: List[Tuple[str, float]]) -> List[ActivationResult]:
        """
        Spread activation from seed nodes through the knowledge graph.

        Args:
            seed_nodes: List of (node_key, initial_activation) tuples

        Returns:
            List of ActivationResult sorted by activation score (descending)
        """
        activation = {}
        paths = {}
        visited_hops = {}

        # Initialize seeds
        for node, score in seed_nodes:
            activation[node] = score
            paths[node] = [node]
            visited_hops[node] = 0

        # Spread through hops
        for hop in range(1, self.max_hops + 1):
            decay = self.decay_per_hop ** hop
            new_activation = {}

            # Get all neighbors for currently active nodes
            current_nodes = [n for n, h in visited_hops.items() if h == hop - 1]

            for node in current_nodes:
                neighbors = self._get_neighbors(node)
                for neighbor, rel_type, rel_strength in neighbors:
                    if neighbor in visited_hops and visited_hops[neighbor] <= hop:
                        continue  # Already visited at same or earlier hop

                    new_score = activation.get(node, 0) * decay * rel_strength
                    if new_score >= self.min_activation:
                        new_activation[neighbor] = new_activation.get(neighbor, 0) + new_score
                        if neighbor not in paths or len(paths.get(neighbor, [])) > len(paths[node]) + 1:
                            paths[neighbor] = paths[node] + [neighbor]
                        visited_hops[neighbor] = hop

            activation.update(new_activation)

        # Convert to results
        results = []
        for node, score in activation.items():
            results.append(ActivationResult(
                node_key=node,
                activation_score=score,
                hops=visited_hops.get(node, 0),
                path=paths.get(node, [node]),
            ))

        results.sort(key=lambda r: r.activation_score, reverse=True)
        return results

    def _get_neighbors(self, node_key: str) -> List[Tuple[str, str, float]]:
        """
        Get neighbors of a node from the knowledge graph.

        Returns list of (neighbor_key, relation_type, relation_strength).
        Checks both Bilinc KG and memory metadata.
        """
        neighbors = []

        # Try Bilinc Knowledge Graph (if table exists)
        try:
            rows = self.conn.execute("""
                SELECT target_entity, relation_type, strength
                FROM knowledge_graph_edges
                WHERE source_entity = ?
            """, (node_key,)).fetchall()
            for row in rows:
                neighbors.append((row[0], row[1], row[2] if row[2] else 0.5))
        except Exception:
            pass  # Table does not exist yet

        # Fallback: check memory metadata for relations
        try:
            row = self.conn.execute(
                "SELECT metadata FROM memories WHERE key = ?", (node_key,)
            ).fetchone()
            if row and row[0]:
                meta = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                relations = meta.get("relations", [])
                for rel in relations:
                    if isinstance(rel, (list, tuple)) and len(rel) >= 2:
                        neighbors.append((rel[1], rel[0], 0.5))
                    elif isinstance(rel, dict):
                        neighbors.append((rel.get("target", ""), rel.get("type", "related_to"), rel.get("strength", 0.5)))
        except Exception:
            pass

        return [(n, t, s) for n, t, s in neighbors if n]


def kg_enhanced_recall(query: str, conn, seed_entries: List[Dict], top_k: int = 10, now: float = None) -> List[Tuple[str, float, Dict]]:
    """
    Full KG-enhanced recall pipeline.

    1. Match seed entries to query
    2. Spread activation through KG
    3. Retrieve memories for activated nodes
    4. Apply decay-aware reranking
    """
    import json
    if now is None:
        now = time.time()

    # Step 1: Find seed nodes from initial search results
    seed_nodes = []
    for entry in seed_entries[:5]:
        key = entry.get("key", "")
        importance = entry.get("importance", 0.5)
        seed_nodes.append((key, importance))

    if not seed_nodes:
        return []

    # Step 2: Spread activation
    kg = KGSpreadingActivation(conn)
    activated = kg.spread(seed_nodes)

    # Step 3: Retrieve memories for activated nodes
    results = []
    seen = set()
    for act in activated[:top_k * 2]:
        if act.node_key in seen:
            continue
        seen.add(act.node_key)

        try:
            row = conn.execute("SELECT * FROM memories WHERE key = ?", (act.node_key,)).fetchone()
            if not row:
                continue

            from bilinc.core.decay import compute_new_strength
            days_elapsed = (now - row["last_accessed"]) / 86400.0 if row["last_accessed"] > 0 else 0
            new_strength, _ = compute_new_strength(
                current_strength=row["current_strength"],
                memory_type=row["memory_type"],
                days_elapsed=days_elapsed,
                importance=row["importance"],
                verification_score=row["verification_score"],
                access_count=row["access_count"],
            )

            final_score = act.activation_score * (0.5 + new_strength * 0.5)
            results.append((act.node_key, final_score, {
                "key": act.node_key,
                "activation": round(act.activation_score, 4),
                "hops": act.hops,
                "path": act.path,
                "strength": round(new_strength, 3),
            }))
        except Exception:
            continue

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]
