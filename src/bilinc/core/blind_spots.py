"""
Blind Spot Detection for Bilinc Knowledge Graph.

Detects knowledge gaps, orphan nodes, shallow clusters, and stale zones.
ORIGINAL implementation.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from enum import Enum


class BlindSpotType(str, Enum):
    ORPHAN = "orphan"
    SHALLOW = "shallow"
    STALE = "stale"
    ISOLATED = "isolated"
    CONTRADICTORY = "contradictory"
    INCOMPLETE = "incomplete"


@dataclass
class BlindSpot:
    spot_type: BlindSpotType
    entity_key: str
    severity: float
    description: str
    suggestion: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BlindSpotReport:
    total_nodes: int = 0
    total_edges: int = 0
    blind_spots: List[BlindSpot] = field(default_factory=list)
    health_score: float = 1.0
    generated_at: float = field(default_factory=time.time)

    @property
    def orphan_count(self):
        return sum(1 for s in self.blind_spots if s.spot_type == BlindSpotType.ORPHAN)

    @property
    def shallow_count(self):
        return sum(1 for s in self.blind_spots if s.spot_type == BlindSpotType.SHALLOW)

    @property
    def stale_count(self):
        return sum(1 for s in self.blind_spots if s.spot_type == BlindSpotType.STALE)

    @property
    def critical_spots(self):
        return [s for s in self.blind_spots if s.severity >= 0.7]

    def to_dict(self):
        return {
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "health_score": round(self.health_score, 3),
            "counts": {"orphan": self.orphan_count, "shallow": self.shallow_count,
                       "stale": self.stale_count, "total": len(self.blind_spots)},
            "critical": len(self.critical_spots),
            "spots": [{"type": s.spot_type.value, "entity": s.entity_key,
                        "severity": round(s.severity, 2), "description": s.description,
                        "suggestion": s.suggestion} for s in self.blind_spots],
        }


class BlindSpotDetector:
    def __init__(self, stale_days: float = 30.0, shallow_threshold: int = 2):
        self.stale_days = stale_days
        self.shallow_threshold = shallow_threshold
        self.now = time.time()

    def analyze(self, nodes, get_edges, get_last_updated, get_beliefs=None):
        report = BlindSpotReport(total_nodes=len(nodes))
        if not nodes:
            report.health_score = 0.0
            return report

        adjacency = {}
        total_edges = 0
        for node in nodes:
            edges = get_edges(node) or []
            adjacency[node] = set()
            for rel_type, target in edges:
                adjacency[node].add(target)
                total_edges += 1
        report.total_edges = total_edges

        for node in nodes:
            edges = get_edges(node) or []
            edge_count = len(edges)

            if edge_count == 0:
                report.blind_spots.append(BlindSpot(
                    spot_type=BlindSpotType.ORPHAN, entity_key=node, severity=0.9,
                    description=f"'{node}' has no relations",
                    suggestion=f"Add relations to connect '{node}'"))
                continue

            if edge_count <= self.shallow_threshold:
                report.blind_spots.append(BlindSpot(
                    spot_type=BlindSpotType.SHALLOW, entity_key=node,
                    severity=0.5 + 0.2 * (self.shallow_threshold - edge_count),
                    description=f"'{node}' has only {edge_count} relation(s)",
                    suggestion=f"Add more relations to '{node}'",
                    metadata={"edge_count": edge_count}))

            last_updated = get_last_updated(node)
            if last_updated:
                days_since = (self.now - last_updated) / 86400.0
                if days_since > self.stale_days:
                    report.blind_spots.append(BlindSpot(
                        spot_type=BlindSpotType.STALE, entity_key=node,
                        severity=min(1.0, 0.4 + days_since / (self.stale_days * 3)),
                        description=f"'{node}' not updated in {int(days_since)} days",
                        suggestion=f"Review and update '{node}'",
                        metadata={"days_stale": round(days_since, 1)}))

        islands = self._find_islands(adjacency, nodes)
        if len(islands) > 1:
            main_island = max(islands, key=len)
            for island in islands:
                if island != main_island:
                    for node in island:
                        if not any(s.entity_key == node and s.spot_type == BlindSpotType.ORPHAN
                                   for s in report.blind_spots):
                            report.blind_spots.append(BlindSpot(
                                spot_type=BlindSpotType.ISOLATED, entity_key=node, severity=0.6,
                                description=f"'{node}' in disconnected island ({len(island)} nodes)",
                                suggestion=f"Bridge '{node}' to main cluster",
                                metadata={"island_size": len(island)}))

        if get_beliefs:
            for node in nodes:
                belief = get_beliefs(node)
                if belief and belief.get("conflict_id"):
                    report.blind_spots.append(BlindSpot(
                        spot_type=BlindSpotType.CONTRADICTORY, entity_key=node, severity=0.8,
                        description=f"'{node}' has unresolved conflict",
                        suggestion=f"Resolve using AGM belief revision"))

        report.health_score = self._calculate_health(report)
        report.blind_spots.sort(key=lambda s: s.severity, reverse=True)
        return report

    def _find_islands(self, adjacency, nodes):
        visited = set()
        islands = []
        for node in nodes:
            if node in visited:
                continue
            island = set()
            queue = [node]
            while queue:
                cur = queue.pop(0)
                if cur in visited:
                    continue
                visited.add(cur)
                island.add(cur)
                for nb in adjacency.get(cur, set()):
                    if nb not in visited:
                        queue.append(nb)
                for src, targets in adjacency.items():
                    if cur in targets and src not in visited:
                        queue.append(src)
            islands.append(island)
        return islands

    def _calculate_health(self, report):
        if report.total_nodes == 0:
            return 0.0
        orphan_p = report.orphan_count * 0.3
        shallow_p = report.shallow_count * 0.15
        stale_p = report.stale_count * 0.05
        isolated_p = sum(1 for s in report.blind_spots if s.spot_type == BlindSpotType.ISOLATED) * 0.1
        total_p = orphan_p + shallow_p + stale_p + isolated_p
        max_p = report.total_nodes * 0.5
        norm_p = min(1.0, total_p / max(max_p, 1))
        max_edges = report.total_nodes * (report.total_nodes - 1) / 2
        density = report.total_edges / max(max_edges, 1)
        bonus = min(0.2, density * 0.2)
        return max(0.0, min(1.0, 1.0 - norm_p + bonus))