"""
3-Stage Consolidation Pipeline for Bilinc.

Stage 1: Fact Distillation
Stage 2: Decay Application (hybrid + LTP + prune)
Stage 3: Graph Strengthening (co-access + blind spots)

ORIGINAL implementation.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from enum import Enum


class ConsolidationStage(str, Enum):
    FACT_DISTILLATION = "fact_distillation"
    DECAY_APPLICATION = "decay_application"
    GRAPH_STRENGTHENING = "graph_strengthening"


@dataclass
class ConsolidationResult:
    stage: ConsolidationStage
    entries_processed: int = 0
    entries_modified: int = 0
    entries_pruned: int = 0
    entries_promoted: int = 0
    facts_extracted: int = 0
    edges_strengthened: int = 0
    blind_spots_found: int = 0
    duration_ms: float = 0.0

    def to_dict(self):
        return {"stage": self.stage.value, "processed": self.entries_processed,
                "modified": self.entries_modified, "pruned": self.entries_pruned,
                "promoted": self.entries_promoted, "facts": self.facts_extracted,
                "edges": self.edges_strengthened, "blind_spots": self.blind_spots_found,
                "duration_ms": round(self.duration_ms, 2)}


@dataclass
class ConsolidationReport:
    stages: List[ConsolidationResult] = field(default_factory=list)
    total_processed: int = 0
    total_pruned: int = 0
    total_promoted: int = 0
    health_score: float = 1.0
    duration_ms: float = 0.0

    def add_stage(self, result):
        self.stages.append(result)
        self.total_processed += result.entries_processed
        self.total_pruned += result.entries_pruned
        self.total_promoted += result.entries_promoted

    def to_dict(self):
        return {"stages": [s.to_dict() for s in self.stages],
                "total_processed": self.total_processed,
                "total_pruned": self.total_pruned,
                "total_promoted": self.total_promoted,
                "health_score": round(self.health_score, 3),
                "duration_ms": round(self.duration_ms, 2)}


class ConsolidationPipeline:
    def __init__(self, prune_threshold=0.05, promotion_threshold=0.7,
                 stale_days=30.0, co_access_window=3600.0):
        self.prune_threshold = prune_threshold
        self.promotion_threshold = promotion_threshold
        self.stale_days = stale_days
        self.co_access_window = co_access_window

    def run(self, entries, get_edges=None, set_edge_strength=None, now=None):
        if now is None:
            now = time.time()
        report = ConsolidationReport()
        start = time.time()

        report.add_stage(self._stage1(entries, now))
        report.add_stage(self._stage2(entries, now))
        report.add_stage(self._stage3(entries, get_edges, now))

        report.health_score = max(0.0, 1.0 - (report.stages[-1].blind_spots_found * 0.1))
        report.duration_ms = (time.time() - start) * 1000
        return report

    def _stage1(self, entries, now):
        start = time.time()
        r = ConsolidationResult(stage=ConsolidationStage.FACT_DISTILLATION)
        r.entries_processed = len(entries)
        seen = {}
        for e in entries:
            key = e.get("key", "")
            mt = e.get("memory_type", "semantic")
            ac = e.get("access_count", 0)
            cs = e.get("current_strength", 1.0)
            if mt in ("working", "episodic") and ac >= 10 and cs > 0.5:
                r.entries_promoted += 1
            val = e.get("value")
            if isinstance(val, dict) and len(val) >= 3:
                r.facts_extracted += 1
            if key in seen:
                r.entries_modified += 1
            seen[key] = e
        r.duration_ms = (time.time() - start) * 1000
        return r

    def _stage2(self, entries, now):
        start = time.time()
        r = ConsolidationResult(stage=ConsolidationStage.DECAY_APPLICATION)
        r.entries_processed = len(entries)
        from bilinc.core.decay import compute_new_strength, should_prune
        for e in entries:
            cs = e.get("current_strength", 1.0)
            mt = e.get("memory_type", "semantic")
            imp = e.get("importance", 1.0)
            vs = e.get("verification_score", 0.0)
            ac = e.get("access_count", 0)
            la = e.get("last_accessed", e.get("created_at", now))
            days = (now - la) / 86400.0
            if days <= 0:
                continue
            ns, _ = compute_new_strength(cs, mt, days, imp, vs, ac)
            if abs(ns - cs) > 0.01:
                r.entries_modified += 1
            if should_prune(ns, mt):
                r.entries_pruned += 1
        r.duration_ms = (time.time() - start) * 1000
        return r

    def _stage3(self, entries, get_edges, now):
        start = time.time()
        r = ConsolidationResult(stage=ConsolidationStage.GRAPH_STRENGTHENING)
        r.entries_processed = len(entries)
        if get_edges:
            windows = {}
            for e in entries:
                la = e.get("last_accessed", 0)
                k = e.get("key", "")
                if la > 0 and (now - la) < self.co_access_window:
                    windows[k] = la
            keys = list(windows.keys())
            for i, k1 in enumerate(keys):
                for k2 in keys[i+1:]:
                    if abs(windows[k1] - windows[k2]) < self.co_access_window:
                        r.edges_strengthened += 1
        try:
            from bilinc.core.blind_spots import detect_blind_spots_from_entries
            bs = detect_blind_spots_from_entries(entries, stale_days=self.stale_days)
            r.blind_spots_found = len(bs.blind_spots)
        except Exception:
            pass
        r.duration_ms = (time.time() - start) * 1000
        return r