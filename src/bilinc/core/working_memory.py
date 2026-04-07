"""
WorkingMemory: Active context buffer (PFC-inspired)

Baddeley model: max 4 +/- 1 chunks (Cowan's revision)
- Priority-based eviction: recency x relevance x novelty
- Auto-consolidation trigger when full
- Gating: working -> episodic threshold
"""
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional, Callable
from bilinc.core.models import MemoryEntry, MemoryType


class WorkingMemory:
    """
    Active context buffer modeled after prefrontal cortex working memory.
    Capacity: max_slots (default 8 = Cowan's 4+/-1 with headroom)
    """
    
    def __init__(self, max_slots: int = 8,
                 consolidation_trigger: Optional[float] = 0.3,
                 gate_threshold: Optional[float] = 0.5):
        self.max_slots = max_slots
        self.consolidation_trigger = consolidation_trigger
        self.gate_threshold = gate_threshold
        self._slots: Dict[str, MemoryEntry] = {}
        self._consolidation_callbacks: List[Callable] = []
    
    def on_consolidation(self, callback: Callable) -> None:
        """Register callback triggered when working memory needs consolidation."""
        self._consolidation_callbacks.append(callback)
    
    @property
    def count(self) -> int:
        return len(self._slots)
    
    @property
    def capacity_usage(self) -> float:
        return self.count / self.max_slots if self.max_slots > 0 else 0.0
    
    def put(self, entry: MemoryEntry) -> Optional[MemoryEntry]:
        """
        Add item to working memory.
        Returns evicted entry if buffer was full.
        """
        entry.memory_type = MemoryType.WORKING
        evicted = None
        
        if entry.key in self._slots:
            self._slots[entry.key] = entry
        else:
            if len(self._slots) >= self.max_slots:
                evicted = self._evict_lowest_priority()
            self._slots[entry.key] = entry
        
        # Check if consolidation needed
        if self.capacity_usage >= (self.consolidation_trigger or 0.8):
            for cb in self._consolidation_callbacks:
                cb(self)
        
        return evicted
    
    def get(self, key: str) -> Optional[MemoryEntry]:
        entry = self._slots.get(key)
        if entry:
            entry.last_accessed = time.time()
            entry.access_count += 1
        return entry
    
    def remove(self, key: str) -> Optional[MemoryEntry]:
        return self._slots.pop(key, None)
    
    def clear(self) -> List[MemoryEntry]:
        """Clear all slots, returning entries for consolidation."""
        entries = list(self._slots.values())
        self._slots.clear()
        return entries
    
    def get_all(self) -> List[MemoryEntry]:
        """Get all entries sorted by priority (importance x recency)."""
        now = time.time()
        return sorted(
            self._slots.values(),
            key=lambda e: e.importance * (1.0 / max(1.0, now - e.last_accessed)),
            reverse=True
        )
    
    def to_entries(self) -> List[MemoryEntry]:
        """Convert working memory to MemoryEntry list for consolidation."""
        return self.get_all()
    
    def _evict_lowest_priority(self) -> Optional[MemoryEntry]:
        """Evict entry with lowest priority score."""
        if not self._slots:
            return None
        now = time.time()
        lowest_key = min(
            self._slots.keys(),
            key=lambda k: self._slots[k].importance * max(0.01, 1.0 - (now - self._slots[k].created_at) / 3600)
        )
        return self._slots.pop(lowest_key)
    
    def gate_to_episodic(self) -> List[MemoryEntry]:
        """
        Gate threshold: entries above threshold are consolidated to episodic.
        Returns entries ready for consolidation.
        """
        ready = [e for e in self._slots.values() if e.importance >= self.gate_threshold]
        for e in ready:
            e.memory_type = MemoryType.EPISODIC
        for e in ready:
            self._slots.pop(e.key, None)
        return ready
    
    def stats(self) -> Dict:
        now = time.time()
        return {
            "count": self.count,
            "max_slots": self.max_slots,
            "capacity_usage": self.capacity_usage,
            "avg_importance": (sum(e.importance for e in self._slots.values()) / self.count) if self.count > 0 else 0,
            "recent_accesses": sum(1 for e in self._slots.values() if now - e.last_accessed < 60),
        }
