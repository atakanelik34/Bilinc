"""
Core data models for SynapticAI.

Defines the typed state objects, memory entries, and
belief revision states that form the foundation of the system.
"""

from __future__ import annotations

import uuid
import json
import time
from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


# ─── Memory Type Classification ───────────────────────────────────

class MemoryType(str, Enum):
    """Neuro-Symbolic memory type taxonomy."""
    # System 1: Neural / Fast
    EPISODIC = "episodic"        # Experiences, events
    PROCEDURAL = "procedural"    # Skills, how-to, patterns
    
    # System 2: Symbolic / Slow  
    SEMANTIC = "semantic"        # Facts, knowledge
    SYMBOLIC = "symbolic"        # Rules, constraints, logic
    
    # Meta
    DERIVED = "derived"          # Computed/derived states
    META = "meta"               # System metadata


# ─── Compressed Cognitive State Schema (8-dim) ────────────────────

class CCSDimension(str, Enum):
    """Compressed Cognitive State dimensions from ACC paper (arXiv:2601.11653)."""
    EPISODIC = "episodic"              # What happened
    SEMANTIC = "semantic"              # What we know
    ENTITIES = "entities"              # Key actors/objects
    RELATIONS = "relations"            # Connections between entities
    GOALS = "goals"                    # Current/achieved goals
    CONSTRAINTS = "constraints"        # Rules, preferences, limits
    PREDICTIVE = "predictive"          # Expected outcomes
    UNCERTAINTY = "uncertainty"        # Confidence levels


# ─── Memory Entry ─────────────────────────────────────────────────

@dataclass
class MemoryEntry:
    """
    A single memory entry with full provenance and lifecycle tracking.
    
    This is the atomic unit of SynapticAI memory. Each entry has:
    - Typed content (episodic, semantic, procedural, symbolic)
    - Provenance (source, session, timestamp)
    - Lifecycle (created, updated, validated, expired)
    - Verification state (verified, unverified, rejected)
    - Staleness tracking (valid_at, invalid_at, decay_rate)
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    memory_type: MemoryType = MemoryType.EPISODIC
    
    # Content
    key: str = ""
    value: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # CCS dimensions (optional annotations)
    ccs_dimensions: Dict[str, float] = field(default_factory=dict)
    
    # Provenance
    source: str = ""              # User, tool, agent, external
    session_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_accessed: float = 0.0
    access_count: int = 0
    
    # Lifecycle (inspired by Zep/Graphiti temporal KG approach)
    valid_at: Optional[float] = None   # When this became valid
    invalid_at: Optional[float] = None # When this became invalid
    ttl: Optional[float] = None        # Time-to-live in seconds
    
    # Verification state
    is_verified: bool = False
    verification_score: float = 0.0    # 0.0 to 1.0
    verification_method: str = ""      # How it was verified
    
    # Staleness / importance
    importance: float = 1.0           # 0.0 (trivial) to 1.0 (critical)
    decay_rate: float = 0.01          # Per-hour decay factor
    current_strength: float = 1.0     # After decay
    
    # Conflict resolution (AGM belief revision)
    conflict_id: Optional[str] = None
    superseded_by: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        d = asdict(self)
        d["memory_type"] = self.memory_type.value
        d["ccs_dimensions"] = {k.value if hasattr(k, 'value') else k: v 
                               for k, v in self.ccs_dimensions.items()}
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEntry":
        """Reconstruct from dictionary."""
        if "memory_type" in data:
            data["memory_type"] = MemoryType(data["memory_type"])
        if "ccs_dimensions" in data:
            data["ccs_dimensions"] = {
                CCSDimension(k) if k in CCSDimension._value2member_map_ else k: v
                for k, v in data["ccs_dimensions"].items()
            }
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    def apply_decay(self, elapsed_hours: float) -> float:
        """
        Apply biological decay curve.
        Based on learnable forgetting (Oblivion paper arXiv:2604.00131).
        
        Returns remaining strength after decay.
        """
        # Exponential decay: strength = initial * e^(-rate * time)
        if self.decay_rate == 0 or elapsed_hours <= 0:
            return self.current_strength
        
        decayed = self.current_strength * (1.0 - self.decay_rate) ** elapsed_hours
        self.current_strength = max(0.0, min(1.0, decayed))
        return self.current_strength
    
    def is_stale(self) -> bool:
        """Check if this memory entry has become stale."""
        now = time.time()
        
        # Explicit invalidation
        if self.invalid_at is not None and now > self.invalid_at:
            return True
        
        # TTL expiration
        if self.ttl is not None and (now - self.created_at) > self.ttl:
            return True
        
        # Strength-based staleness
        if self.current_strength < 0.1:
            return True
        
        return False


# ─── Belief State (for AGM Belief Revision) ───────────────────────

@dataclass
class BeliefState:
    """
    Represents the current belief state of an agent.
    
    Used by the AGM (Alchourrón-Gärdenfors-Makinson) belief revision engine
    to manage consistent knowledge over time.
    
    Based on Kumiho formal AGM belief revision theory (arXiv:2603.17244).
    """
    beliefs: Dict[str, MemoryEntry] = field(default_factory=dict)
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    revision_count: int = 0
    
    def add_belief(self, entry: MemoryEntry) -> None:
        """Add a belief (AGM EXPAND operation)."""
        self.beliefs[entry.key] = entry
        self.updated_at = time.time()
    
    def remove_belief(self, key: str) -> Optional[MemoryEntry]:
        """Remove a belief (AGM CONTRACT operation)."""
        entry = self.beliefs.pop(key, None)
        if entry:
            self.updated_at = time.time()
        return entry
    
    def has_belief(self, key: str) -> bool:
        """Check if a belief exists."""
        return key in self.beliefs
    
    def get_belief(self, key: str) -> Optional[MemoryEntry]:
        """Get a belief by key."""
        return self.beliefs.get(key)
    
    def get_all_beliefs(self) -> List[MemoryEntry]:
        """Get all beliefs, filtered by staleness."""
        return [e for e in self.beliefs.values() if not e.is_stale()]
    
    def get_conflicts(self) -> List[List[str]]:
        """
        Detect conflicting beliefs.
        Returns groups of keys that conflict with each other.
        """
        conflicts = []
        seen = set()
        
        for key1, entry1 in self.beliefs.items():
            if key1 in seen:
                continue
            conflict_group = [key1]
            
            for key2, entry2 in self.beliefs.items():
                if key1 == key2 or key2 in seen:
                    continue
                
                # Check for semantic conflict (same key pattern, different values)
                if self._entries_conflict(entry1, entry2):
                    conflict_group.append(key2)
                    seen.add(key2)
            
            if len(conflict_group) > 1:
                conflicts.append(conflict_group)
                seen.add(key1)
        
        return conflicts
    
    def _entries_conflict(self, e1: MemoryEntry, e2: MemoryEntry) -> bool:
        """Check if two entries conflict."""
        if e1.key == e2.key and e1.value != e2.value:
            return True
        
        # Check metadata for explicit conflict markers
        if (e1.metadata.get("conflicts_with") == e2.key or
            e2.metadata.get("conflicts_with") == e1.key):
            return True
        
        return False
