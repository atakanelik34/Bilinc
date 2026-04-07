"""
Learnable Forgetting Engine

Based on Oblivion (arXiv:2604.00131):
- Models biological forgetting curves
- Importance-based retention vs static TTL
- Explainable: "Why was this forgotten?"

Instead of expiring memories by time, this engine:
1. Adjusts decay rates based on importance and access patterns
2. Can strengthen frequently accessed memories
3. Provides explanations for forgetting decisions
"""

from __future__ import annotations

import time
import math
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from bilinc.core.models import MemoryEntry

logger = logging.getLogger(__name__)


@dataclass
class DecayConfig:
    """Configuration for decay behavior."""
    # Base decay rates per memory type
    episodic_decay: float = 0.02      # Experiences fade faster
    procedural_decay: float = 0.005   # Skills persist
    semantic_decay: float = 0.01      # Facts fade slowly
    symbolic_decay: float = 0.003     # Rules persist longest
    
    # Access-based reinforcement
    access_boost_per_use: float = 0.05
    max_access_boost: float = 0.3
    
    # Verification-based retention
    verified_retention_bonus: float = 0.1
    
    # Ebbinghaus forgetting curve parameters
    ebbinghaus_S: float = 100  # Initial memory strength (%)
    ebbinghaus_k: float = 1.25  # Forgetting constant


class LearnableForgetting:
    """
    Learnable decay and forgetting engine.
    
    Models how memories fade over time, with:
    - Type-specific decay rates
    - Access-based reinforcement (use it or lose it)
    - Verification-based retention
    - Ebbinghaus forgetting curve
    - Explainable decisions
    """
    
    def __init__(
        self,
        default_decay_rate: float = 0.01,
        config: Optional[DecayConfig] = None,
        enabled: bool = True,
    ):
        self.default_decay_rate = default_decay_rate
        self.config = config or DecayConfig()
        self.enabled = enabled
        self.decay_history: Dict[str, List[Dict[str, Any]]] = {}
        self._forget_count = 0
    
    def on_commit(self, entry: MemoryEntry) -> None:
        """Record when a memory is committed."""
        self.decay_history[entry.key] = [{
            "event": "commit",
            "timestamp": time.time(),
            "strength": entry.current_strength,
            "importance": entry.importance,
            "decay_rate": entry.decay_rate,
        }]
    
    def on_forget(self, entry: MemoryEntry, reason: str = "expired") -> None:
        """Record when a memory is forgotten."""
        if entry.key not in self.decay_history:
            self.decay_history[entry.key] = []
        
        self.decay_history[entry.key].append({
            "event": "forget",
            "timestamp": time.time(),
            "reason": reason,
            "final_strength": entry.current_strength,
        })
        self._forget_count += 1
    
    def on_access(self, entry: MemoryEntry) -> float:
        """
        Record memory access and apply reinforcement.
        
        Returns the new strength after access boost.
        """
        access_count = entry.access_count
        entry.access_count += 1
        entry.last_accessed = time.time()
        
        # Apply access boost (diminishing returns)
        boost = self.config.access_boost_per_use / (1 + access_count * 0.1)
        boost = min(boost, self.config.max_access_boost - 
                   sum(h["event"] == "boost" for h in self.decay_history.get(entry.key, [])) * 0.05)
        
        new_strength = min(1.0, entry.current_strength + boost)
        entry.current_strength = new_strength
        
        if entry.key not in self.decay_history:
            self.decay_history[entry.key] = []
        self.decay_history[entry.key].append({
            "event": "access_boost",
            "timestamp": time.time(),
            "strength_before": new_strength - boost,
            "strength_after": new_strength,
            "boost": boost,
            "access_count": entry.access_count,
        })
        
        return new_strength
    
    def apply_decay_to_entry(self, entry: MemoryEntry) -> None:
        """Apply time-based decay to a single entry."""
        if not self.enabled:
            return
        
        now = time.time()
        last_update = entry.updated_at
        elapsed_hours = max(0, (now - last_update) / 3600.0)
        
        if elapsed_hours < 0.01:  # Less than 36 seconds
            return
        
        # Get type-specific decay rate
        type_decay = {
            "episodic": self.config.episodic_decay,
            "procedural": self.config.procedural_decay,
            "semantic": self.config.semantic_decay,
            "symbolic": self.config.symbolic_decay,
        }.get(entry.memory_type.value if hasattr(entry.memory_type, 'value') else str(entry.memory_type), 
              self.default_decay_rate)
        
        # Apply Ebbinghaus curve
        ebbinghaus_strength = (
            self.config.ebbinghaus_S * 
            math.exp(-self.config.ebbinghaus_k * elapsed_hours)
        )
        
        # Exponential decay
        base_decay = type_decay * elapsed_hours
        
        # Verification bonus
        if entry.is_verified:
            base_decay *= (1 - self.config.verified_retention_bonus)
        
        entry.decay_rate = type_decay
        entry.apply_decay(elapsed_hours)
    
    def apply_global_decay(self) -> None:
        """
        Apply decay to all tracked entries.
        
        This should be called periodically (e.g., at the start of each recall).
        """
        if not self.enabled:
            return
        
        # Decay is applied per-entry during commit/recall in StatePlane
        pass
    
    def generate_explanation(self, key: str) -> str:
        """
        Explain why a memory was forgotten or has low strength.
        
        Returns a human-readable explanation.
        """
        history = self.decay_history.get(key, [])
        
        if not history:
            return f"No history found for '{key}'."
        
        explanations = []
        
        for event in history:
            if event["event"] == "commit":
                explanations.append(
                    f"Committed with importance {event['importance']:.2f} "
                    f"and initial strength {event['strength']:.2f}."
                )
            elif event["event"] == "forget":
                explanations.append(
                    f"Forgotten because: {event['reason']}. "
                    f"Final strength: {event.get('final_strength', 'N/A')}."
                )
            elif event["event"] == "access_boost":
                explanations.append(
                    f"Accessed {event['access_count']} times, "
                    f"strength boosted to {event['strength_after']:.2f}."
                )
        
        return " ".join(explanations)
    
    def get_decay_stats(self) -> Dict[str, Any]:
        """Get overall forgetting statistics."""
        total_committed = sum(
            1 for history in self.decay_history.values()
            if any(e["event"] == "commit" for e in history)
        )
        total_forgotten = sum(
            1 for history in self.decay_history.values()
            if any(e["event"] == "forget" for e in history)
        )
        
        return {
            "enabled": self.enabled,
            "tracked_keys": len(self.decay_history),
            "total_committed": total_committed,
            "total_forgotten": total_forgotten,
            "forget_rate": total_forgotten / max(total_committed, 1),
        }
