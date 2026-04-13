"""
Core data models for Bilinc. Phase 1 update (v0.2.0).
Brain-inspired 5-type memory taxonomy with full provenance tracking.
"""
from __future__ import annotations
import uuid, json, time
from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict


class MemoryType(str, Enum):
    """Brain-inspired 5-type memory taxonomy."""
    EPISODIC = "episodic"
    PROCEDURAL = "procedural"
    SEMANTIC = "semantic"
    WORKING = "working"
    SPATIAL = "spatial"

    @property
    def is_system1(self):
        return self in (self.EPISODIC, self.PROCEDURAL)

    @property
    def is_system2(self):
        return self is self.SEMANTIC

    @property
    def is_specialized(self):
        return self in (self.WORKING, self.SPATIAL)

    @property
    def default_decay_rate(self):
        return {self.EPISODIC: 0.05, self.SEMANTIC: 0.01,
                self.PROCEDURAL: 0.005, self.WORKING: 0.15, self.SPATIAL: 0.02}.get(self, 0.01)

    @property
    def max_entries(self):
        return {self.EPISODIC: 10000, self.SEMANTIC: 5000,
                self.PROCEDURAL: 1000, self.WORKING: 8, self.SPATIAL: 2000}.get(self, 5000)


class CCSDimension(str, Enum):
    """Compressed Cognitive State dimensions (ACC paper)."""
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    ENTITIES = "entities"
    RELATIONS = "relations"
    GOALS = "goals"
    CONSTRAINTS = "constraints"
    PREDICTIVE = "predictive"
    UNCERTAINTY = "uncertainty"


@dataclass
class MemoryEntry:
    """Atomic unit of Bilinc memory with full provenance."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    memory_type: MemoryType = MemoryType.EPISODIC
    key: str = ""
    value: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    ccs_dimensions: Dict[str, float] = field(default_factory=dict)
    source: str = ""
    session_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_accessed: float = 0.0
    access_count: int = 0
    valid_at: Optional[float] = None
    invalid_at: Optional[float] = None
    ttl: Optional[float] = None
    is_verified: bool = False
    verification_score: float = 0.0
    verification_method: str = ""
    importance: float = 1.0
    decay_rate: float = 0.01
    current_strength: float = 1.0
    conflict_id: Optional[str] = None
    superseded_by: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        d["memory_type"] = self.memory_type.value
        return d

    @classmethod
    def from_dict(cls, data):
        if "memory_type" in data:
            data["memory_type"] = MemoryType(data["memory_type"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def apply_decay(self, elapsed_hours):
        """Apply simple exponential decay (legacy). For hybrid decay, use apply_hybrid_decay()."""
        if self.decay_rate <= 0 or elapsed_hours <= 0:
            return self.current_strength
        self.current_strength = max(0.0, min(1.0, self.current_strength * (1 - self.decay_rate) ** elapsed_hours))
        return self.current_strength

    def apply_hybrid_decay(self, elapsed_hours, recent_accesses=0):
        """Apply type-aware hybrid decay (exponential + power-law) with LTP protection."""
        from bilinc.core.decay import compute_new_strength
        days_elapsed = elapsed_hours / 24.0
        mt = self.memory_type.value if hasattr(self.memory_type, "value") else str(self.memory_type)
        new_strength, _ = compute_new_strength(
            current_strength=self.current_strength,
            memory_type=mt,
            days_elapsed=days_elapsed,
            importance=self.importance,
            verification_score=self.verification_score,
            access_count=self.access_count,
            recent_accesses=recent_accesses,
        )
        self.current_strength = new_strength
        return self.current_strength

    def is_stale(self):
        now = time.time()
        if self.invalid_at and now > self.invalid_at:
            return True
        if self.ttl and (now - self.created_at) > self.ttl:
            return True
        return self.current_strength < 0.1


@dataclass
class BeliefState:
    """Agent belief state managed by AGM belief revision."""
    beliefs: Dict[str, MemoryEntry] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    revision_count: int = 0

    def add_belief(self, entry):
        self.beliefs[entry.key] = entry
        self.updated_at = time.time()

    def remove_belief(self, key):
        entry = self.beliefs.pop(key, None)
        if entry:
            self.updated_at = time.time()
        return entry

    def get_belief(self, key):
        return self.beliefs.get(key)

    def get_all_beliefs(self):
        return [e for e in self.beliefs.values() if not e.is_stale()]
