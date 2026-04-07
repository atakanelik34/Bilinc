"""
Advanced Forgetting Engine — Phase 1 (v0.2.0)

Multi-reason forgetting modeled after brain's adaptive forgetting:
1. Relevance decay: time × task_relevance × usage_frequency
2. Contradiction resolution: conflicting beliefs → weaker one decays
3. Space optimization: near storage limit → prune lowest scores
4. Cognitive efficiency: fewer high-quality memories > quantity

Also includes:
- Spaced repetition scheduler
- Protection mechanisms (core beliefs, high-frequency, etc.)
- Explainable forgetting (why trace)
"""
from __future__ import annotations
import time
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from bilinc.core.models import MemoryEntry, MemoryType


@dataclass
class ForgettingResult:
    """Detailed forgetting operation result."""
    entries_processed: int = 0
    entries_forgotten: int = 0
    entries_archived: int = 0
    entries_protected: int = 0
    reasons: Dict[str, int] = field(default_factory=dict)
    explain_traces: List[str] = field(default_factory=list)


class ForgettingEngine:
    """
    Adaptive forgetting for AI Agent Brain.
    
    Reasons for forgetting:
    1. Relevance decay — natural decay based on time and usage
    2. Contradiction — conflicting information, weaker version removed
    3. Space limit — storage near capacity, lowest priority pruned
    4. Cognitive efficiency — too many similar memories, merge/remove
    
    Protection mechanisms:
    - Core beliefs (high importance + verified)
    - High-frequency access (access_count > threshold)
    - High-impact events (reward/penalty magnitude)
    - Procedural skills (once automated, very slow decay)
    """
    
    def __init__(self, storage_backend=None):
        self.backend = storage_backend
        self._config = {
            'forgetting_threshold': 0.1,
            'protection_access_count': 20,
            'protection_importance': 0.9,
            'protection_impact_threshold': 0.85,
            'merge_similarity_threshold': 0.7,
            'max_entries_per_type': {
                MemoryType.EPISODIC: 10000,
                MemoryType.SEMANTIC: 5000,
                MemoryType.PROCEDURAL: 1000,
                MemoryType.WORKING: 8,
                MemoryType.SPATIAL: 2000,
            },
        }
    
    async def forget_stale(self, reason: str = "decay") -> ForgettingResult:
        """Forget all entries that have gone stale."""
        result = ForgettingResult()
        if not self.backend:
            return result
        
        stale = await self.backend.load_stale()
        result.entries_processed = len(stale)
        
        for e in stale:
            # Check protection
            if self._is_protected(e):
                result.entries_protected += 1
                result.explain_traces.append(f"PROTECTED: {e.key} (importance={e.importance}, access={e.access_count})")
                # Boost strength instead of forgetting
                e.current_strength = max(e.current_strength, 0.2)
                await self.backend.save(e)
                continue
            
            # Archive or delete
            if e.access_count >= 3:
                # Archive: mark as archived, reduce to minimum
                e.metadata['archived_at'] = time.time()
                e.metadata['archive_reason'] = reason
                e.current_strength = 0.0
                result.entries_archived += 1
            else:
                await self.backend.delete(e.key)
                result.entries_forgotten += 1
                result.explain_traces.append(f"FORGOTTEN: {e.key} (strength={e.current_strength:.2f}, reason={reason})")
            
            result.reasons[reason] = result.reasons.get(reason, 0) + 1
        
        return result
    
    async def forget_by_contradiction(self) -> ForgettingResult:
        """Remove weaker entries that contradict stronger ones."""
        result = ForgettingResult()
        if not self.backend:
            return result
        
        all_entries = await self.backend.list_all()
        by_key: Dict[str, List[MemoryEntry]] = {}
        for e in all_entries:
            by_key.setdefault(e.key, []).append(e)
        
        for key, entries in by_key.items():
            if len(entries) <= 1:
                continue
            
            # Find strongest entry
            values = {}
            for e in entries:
                v = str(e.value)[:50]
                values.setdefault(v, []).append(e)
            
            if len(values) == 1:
                continue  # All same value, no conflict
            
            # Keep highest-verified entry for each distinct value group
            best_overall = max(entries, key=lambda e: e.verification_score * e.importance)
            
            for e in entries:
                if e.id != best_overall.id and str(e.value) != str(best_overall.value):
                    result.entries_processed += 1
                    if self._is_protected(e):
                        result.entries_protected += 1
                        result.explain_traces.append(f"PROTECTED from contradiction: {e.key}")
                        continue
                    
                    superseded = e
                    superseded.superseded_by = e.key
                    superseded.current_strength *= 0.3
                    await self.backend.save(superseded)
                    result.entries_forgotten += 1
                    result.reasons['contradiction'] = result.reasons.get('contradiction', 0) + 1
        
        return result
    
    async def enforce_space_limits(self) -> ForgettingResult:
        """Prune entries when storage nears per-type limits."""
        result = ForgettingResult()
        if not self.backend:
            return result
        
        counts = await self.backend.count_by_type()
        
        for mt in MemoryType:
            limit = self._config['max_entries_per_type'].get(mt, 5000)
            current = counts.get(mt.value, 0)
            
            if current > limit * 0.9:  # 90% full
                entries = await self.backend.load_by_type(mt, limit=200)
                # Sort by composite score (ascending = worst first)
                sorted_entries = sorted(entries, key=lambda e: e.importance * e.current_strength * (1 + e.access_count * 0.1))
                
                # Prune worst 20%
                to_prune = sorted_entries[:int(len(sorted_entries) * 0.2)]
                for e in to_prune:
                    if self._is_protected(e):
                        result.entries_protected += 1
                        continue
                    
                    if e.access_count >= 3:
                        e.metadata['archive_reason'] = 'space_limit'
                        e.current_strength = 0.0
                        await self.backend.save(e)
                        result.entries_archived += 1
                    else:
                        await self.backend.delete(e.key)
                        result.entries_forgotten += 1
                    result.entries_processed += 1
                    result.reasons['space_limit'] = result.reasons.get('space_limit', 0) + 1
        
        return result
    
    def explain_forgetting(self, entry: MemoryEntry) -> str:
        """Detailed explanation of why an entry was/would be forgotten."""
        reasons = []
        
        if entry.is_stale():
            reasons.append(f"Entry is stale (strength={entry.current_strength:.2f})")
        
        elapsed_hours = (time.time() - entry.updated_at) / 3600
        if elapsed_hours > 0 and entry.decay_rate > 0:
            expected = entry.current_strength * (1 - entry.decay_rate) ** elapsed_hours
            reasons.append(f"Decay: {elapsed_hours:.1f}h at rate {entry.decay_rate:.4f}/h → expected {expected:.3f}")
        
        if not self._is_protected(entry):
            reasons.append("No protection mechanisms active")
        
        if reasons:
            return f"Would forget {entry.key}: {'; '.join(reasons)}"
        return f"Entry {entry.key} is protected from forgetting"
    
    def _is_protected(self, entry: MemoryEntry) -> bool:
        """Check if entry is protected from forgetting."""
        c = self._config
        # Core beliefs (high importance + verified)
        if entry.importance >= c['protection_importance'] and entry.is_verified:
            return True
        # High-frequency access
        if entry.access_count >= c['protection_access_count']:
            return True
        # High-impact events
        if entry.importance >= c['protection_impact_threshold']:
            return True
        # Procedural skills (very slow decay once automated)
        if entry.memory_type == MemoryType.PROCEDURAL and entry.access_count >= 10:
            return True
        return False
