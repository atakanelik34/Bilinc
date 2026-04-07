"""
ConsolidationEngine: Sleep-inspired memory consolidation.
NREM (4 phases): Replay → Integrate → Abstract → Downscale
REM (3 phases): Skill consolidation → Creative recombination → Counterfactuals
"""
from __future__ import annotations
import time, random, asyncio
from typing import Any, Dict, List, Optional, Callable
from enum import Enum
from dataclasses import dataclass, field
from bilinc.core.models import MemoryEntry, MemoryType


class ConsolidationPhase(str, Enum):
    NREM_REPLAY = "nrem_replay"
    NREM_INTEGRATE = "nrem_integrate"
    NREM_ABSTRACT = "nrem_abstract"
    NREM_DOWNSCALE = "nrem_downscale"
    REM_SKILL = "rem_skill"
    REM_CREATIVE = "rem_creative"
    REM_COUNTERFACTUAL = "rem_counterfactual"


@dataclass
class ConsolidationResult:
    phase: ConsolidationPhase
    items_processed: int = 0
    items_consolidated: int = 0
    items_pruned: int = 0
    new_entries_created: int = 0
    insights_generated: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class ConsolidationEngine:
    """Sleep-inspired memory consolidation for AI Agent Brain."""
    
    def __init__(self, working_memory=None, storage_backend=None):
        self.wm = working_memory
        self.backend = storage_backend
        self._callbacks = []
        self._cycle_count = 0
    
    def on_cycle_complete(self, callback):
        self._callbacks.append(callback)
    
    async def run_full_cycle(self):
        self._cycle_count += 1
        results = []
        results.append(await self._nrem_replay())
        results.append(await self._nrem_integrate())
        results.append(await self._nrem_abstract())
        results.append(await self._nrem_downscale())
        results.append(await self._rem_skill())
        results.append(await self._rem_creative())
        results.append(await self._rem_counterfactuals())
        for cb in self._callbacks:
            try: cb(results)
            except: pass
        return results
    
    async def _nrem_replay(self):
        start = time.time()
        if not self.backend:
            return ConsolidationResult(phase=ConsolidationPhase.NREM_REPLAY, duration_seconds=time.time()-start)
        entries = await self.backend.load_high_priority(50)
        count = 0
        for e in entries:
            e.last_accessed = time.time()
            e.access_count += 1
            e.current_strength = min(1.0, e.current_strength + 0.05 * e.importance)
            e.updated_at = time.time()
            await self.backend.save(e)
            count += 1
        return ConsolidationResult(phase=ConsolidationPhase.NREM_REPLAY, items_processed=len(entries), items_consolidated=count, duration_seconds=time.time()-start)
    
    async def _nrem_integrate(self):
        start = time.time()
        linked = 0
        if not self.backend:
            return ConsolidationResult(phase=ConsolidationPhase.NREM_INTEGRATE, duration_seconds=time.time()-start)
        episodic = await self.backend.load_by_type(MemoryType.EPISODIC, limit=50)
        to_integrate = [e for e in episodic if not e.metadata.get("integrated")]
        for e in to_integrate:
            e.metadata["integrated"] = True
            e.metadata["integrated_at"] = time.time()
            if isinstance(e.value, dict):
                for k, v in e.value.items():
                    if v and isinstance(v, (str, int, float, bool)):
                        link_key = f"derived_{e.key}_{k}"
                        existing = await self.backend.load(link_key)
                        if not existing:
                            se = MemoryEntry(key=link_key, value=v, memory_type=MemoryType.SEMANTIC,
                                importance=e.importance * 0.7, source="consolidation",
                                metadata={"derived_from": e.key, "attribute": k})
                            await self.backend.save(se)
                            linked += 1
            await self.backend.save(e)
        return ConsolidationResult(phase=ConsolidationPhase.NREM_INTEGRATE, items_processed=len(to_integrate), items_consolidated=linked, duration_seconds=time.time()-start)
    
    async def _nrem_abstract(self):
        start = time.time()
        rules = 0
        if not self.backend:
            return ConsolidationResult(phase=ConsolidationPhase.NREM_ABSTRACT, duration_seconds=time.time()-start)
        episodic = await self.backend.load_by_type(MemoryType.EPISODIC, limit=100)
        by_source = {}
        for e in episodic:
            s = e.source or "unknown"
            by_source.setdefault(s, []).append(e)
        for source, entries in by_source.items():
            if len(entries) >= 3:
                rule_key = f"abstraction_{source}"
                existing = await self.backend.load(rule_key)
                if existing:
                    existing.metadata["event_count"] = len(entries) + existing.metadata.get("event_count", 0)
                    existing.updated_at = time.time()
                    await self.backend.save(existing)
                else:
                    abstraction = MemoryEntry(key=rule_key,
                        value={"source": source, "event_count": len(entries), "keys": [x.key for x in entries[:5]]},
                        memory_type=MemoryType.SEMANTIC, importance=0.8, source="consolidation",
                        metadata={"is_abstraction": True, "source": source, "abstracted_at": time.time()})
                    await self.backend.save(abstraction)
                    rules += 1
        return ConsolidationResult(phase=ConsolidationPhase.NREM_ABSTRACT, items_processed=len(by_source), new_entries_created=rules, duration_seconds=time.time()-start)
    
    async def _nrem_downscale(self):
        start = time.time()
        pruned = 0
        if not self.backend:
            return ConsolidationResult(phase=ConsolidationPhase.NREM_DOWNSCALE, duration_seconds=time.time()-start)
        stale = await self.backend.load_stale()
        for e in stale:
            if e.current_strength < 0.15:
                e.metadata["consolidation_status"] = "downscaled"
                e.importance *= 0.5
                await self.backend.save(e)
                pruned += 1
            elif e.current_strength < 0.3:
                e.current_strength *= 0.8
                await self.backend.save(e)
        return ConsolidationResult(phase=ConsolidationPhase.NREM_DOWNSCALE, items_processed=len(stale), items_pruned=pruned, duration_seconds=time.time()-start)
    
    async def _rem_skill(self):
        start = time.time()
        optimized = 0
        if not self.backend:
            return ConsolidationResult(phase=ConsolidationPhase.REM_SKILL, duration_seconds=time.time()-start)
        all_ep = await self.backend.load_by_type(MemoryType.EPISODIC, limit=200)
        frequent = [e for e in all_ep if e.access_count >= 10]
        for e in frequent:
            if e.memory_type != MemoryType.PROCEDURAL:
                e.memory_type = MemoryType.PROCEDURAL
                e.metadata["automated_at"] = time.time()
                e.decay_rate = MemoryType.PROCEDURAL.default_decay_rate
                await self.backend.save(e)
                optimized += 1
        return ConsolidationResult(phase=ConsolidationPhase.REM_SKILL,
            items_processed=len(frequent),
            items_consolidated=optimized,
            duration_seconds=time.time()-start)
    
    async def _rem_creative(self):
        start = time.time()
        count = 0
        if not self.backend:
            return ConsolidationResult(phase=ConsolidationPhase.REM_CREATIVE, duration_seconds=time.time()-start)
        semantic = await self.backend.load_by_type(MemoryType.SEMANTIC, limit=50)
        if len(semantic) < 2:
            return ConsolidationResult(phase=ConsolidationPhase.REM_CREATIVE, duration_seconds=time.time()-start)
        pairings = min(5, len(semantic) * (len(semantic) - 1) // 2)
        for _ in range(pairings):
            pair = random.sample(semantic, 2)
            e1, e2 = pair
            ck = f"creative_{e1.key}_{e2.key}"
            ce = MemoryEntry(key=ck, value={"concept_1": e1.key, "concept_2": e2.key},
                memory_type=MemoryType.SEMANTIC, importance=0.4, source="consolidation_creative",
                metadata={"is_creative": True, "concepts": [e1.key, e2.key], "created_at": time.time()})
            await self.backend.save(ce)
            count += 1
        return ConsolidationResult(phase=ConsolidationPhase.REM_CREATIVE, new_entries_created=count, duration_seconds=time.time()-start)
    
    async def _rem_counterfactuals(self):
        start = time.time()
        count = 0
        if not self.backend:
            return ConsolidationResult(phase=ConsolidationPhase.REM_COUNTERFACTUAL, duration_seconds=time.time()-start)
        verified = await self.backend.load_by_type(MemoryType.EPISODIC, limit=30)
        verified_entries = [e for e in verified if e.is_verified]
        for e in verified_entries[:3]:
            cf_key = f"cf_{e.key}_alt"
            cf = MemoryEntry(key=cf_key, value={"actual": e.value, "counterfactual": f"alt_{e.key}"},
                memory_type=MemoryType.EPISODIC, importance=e.importance * 0.5, source="consolidation_cf",
                metadata={"is_counterfactual": True, "based_on": e.key, "created_at": time.time()})
            await self.backend.save(cf)
            count += 1
        return ConsolidationResult(phase=ConsolidationPhase.REM_COUNTERFACTUAL, new_entries_created=count, duration_seconds=time.time()-start)
    
    def get_stats(self):
        return {"cycle_count": self._cycle_count, "phases": [p.value for p in ConsolidationPhase]}
