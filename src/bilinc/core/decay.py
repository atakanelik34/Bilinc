"""
Hybrid Decay Model for Bilinc Memory System.

Implements type-aware decay with two phases:
  1. Exponential decay (fast noise filtering) for t < crossover
  2. Power-law decay (long-term retention) for t >= crossover

Also provides LTP (Long-Term Potentiation) integration for
importance-based decay protection.

ORIGINAL implementation. Inspired by cognitive science:
  - Wixted & Ebbesen (1991) "On the Form of Forgetting"
  - Anderson & Schooler (1991) "Reflections of the Environment in Memory"
"""

from __future__ import annotations
import math
import time
from dataclasses import dataclass
from typing import Optional, Dict, Tuple
from enum import Enum


class LTPStatus(Enum):
    """Long-Term Potentiation protection levels."""
    NONE = "none"
    BURST = "burst"       # 2x slower decay
    WEEKLY = "weekly"     # 3x slower decay
    FULL = "full"         # 10x slower decay


LTP_FACTORS = {
    LTPStatus.NONE: 1.0,
    LTPStatus.BURST: 0.5,
    LTPStatus.WEEKLY: 0.3,
    LTPStatus.FULL: 0.1,
}


@dataclass
class DecayProfile:
    """Decay parameters for a specific memory type."""
    base_rate: float
    half_life_days: float
    crossover_days: float
    power_law_beta: float

    @classmethod
    def for_memory_type(cls, memory_type: str) -> "DecayProfile":
        profiles = {
            "working": cls(base_rate=0.05, half_life_days=1.0, crossover_days=1.0, power_law_beta=0.5),
            "episodic": cls(base_rate=0.02, half_life_days=7.0, crossover_days=3.0, power_law_beta=0.35),
            "procedural": cls(base_rate=0.015, half_life_days=30.0, crossover_days=7.0, power_law_beta=0.3),
            "semantic": cls(base_rate=0.005, half_life_days=180.0, crossover_days=14.0, power_law_beta=0.2),
            "spatial": cls(base_rate=0.01, half_life_days=90.0, crossover_days=7.0, power_law_beta=0.25),
        }
        return profiles.get(memory_type, profiles["semantic"])


def compute_ltp_status(importance: float, verification_score: float = 0.0, access_count: int = 0) -> LTPStatus:
    if importance >= 0.9 and verification_score >= 0.8:
        return LTPStatus.FULL
    if importance >= 0.7 or (verification_score >= 0.5 and access_count >= 5):
        return LTPStatus.WEEKLY
    if importance >= 0.5 or access_count >= 10:
        return LTPStatus.BURST
    return LTPStatus.NONE


def hybrid_decay_factor(days_elapsed: float, profile: DecayProfile, ltp_status: LTPStatus = LTPStatus.NONE) -> float:
    if days_elapsed <= 0:
        return 1.0
    ltp_factor = LTP_FACTORS[ltp_status]
    effective_rate = profile.base_rate * ltp_factor
    if days_elapsed < profile.crossover_days:
        return math.exp(-effective_rate * days_elapsed)
    else:
        value_at_crossover = math.exp(-effective_rate * profile.crossover_days)
        beta = profile.power_law_beta * ltp_factor
        power_law_factor = (days_elapsed / profile.crossover_days) ** (-beta)
        return value_at_crossover * power_law_factor


def access_frequency_boost(access_count: int, recent_accesses: int = 0) -> float:
    if access_count >= 20:
        base = 1.2
    elif access_count >= 10:
        base = 1.1
    elif access_count >= 5:
        base = 1.05
    else:
        base = 1.0
    if recent_accesses >= 5:
        base += 0.1
    elif recent_accesses >= 2:
        base += 0.05
    return min(base, 1.3)


def compute_new_strength(
    current_strength: float,
    memory_type: str,
    days_elapsed: float,
    importance: float = 1.0,
    verification_score: float = 0.0,
    access_count: int = 0,
    recent_accesses: int = 0,
) -> Tuple[float, Dict]:
    if days_elapsed <= 0:
        return current_strength, {"factor": 1.0, "phase": "none", "ltp": "none"}
    profile = DecayProfile.for_memory_type(memory_type)
    ltp_status = compute_ltp_status(importance, verification_score, access_count)
    decay_factor = hybrid_decay_factor(days_elapsed, profile, ltp_status)
    access_boost = access_frequency_boost(access_count, recent_accesses)
    combined_factor = min(1.0, decay_factor * access_boost)
    new_strength = max(0.0, min(1.0, current_strength * combined_factor))
    phase = "exponential" if days_elapsed < profile.crossover_days else "power_law"
    metadata = {
        "factor": round(combined_factor, 6),
        "decay_factor": round(decay_factor, 6),
        "access_boost": round(access_boost, 4),
        "phase": phase,
        "ltp": ltp_status.value,
        "profile": {"base_rate": profile.base_rate, "half_life_days": profile.half_life_days, "crossover_days": profile.crossover_days},
    }
    return new_strength, metadata


def decay_for_entry(entry, now: Optional[float] = None, recent_accesses: int = 0) -> float:
    if now is None:
        now = time.time()
    if isinstance(entry, dict):
        current_strength = entry.get("current_strength", 1.0)
        memory_type = entry.get("memory_type", "semantic")
        importance = entry.get("importance", 1.0)
        verification_score = entry.get("verification_score", 0.0)
        access_count = entry.get("access_count", 0)
        last_accessed = entry.get("last_accessed", entry.get("created_at", now))
    else:
        current_strength = entry.current_strength
        memory_type = entry.memory_type.value if hasattr(entry.memory_type, "value") else str(entry.memory_type)
        importance = entry.importance
        verification_score = entry.verification_score
        access_count = entry.access_count
        last_accessed = entry.last_accessed if entry.last_accessed > 0 else entry.created_at
    elapsed_seconds = now - last_accessed
    days_elapsed = elapsed_seconds / 86400.0
    new_strength, _ = compute_new_strength(
        current_strength=current_strength,
        memory_type=memory_type,
        days_elapsed=days_elapsed,
        importance=importance,
        verification_score=verification_score,
        access_count=access_count,
        recent_accesses=recent_accesses,
    )
    return new_strength


def should_prune(current_strength: float, memory_type: str) -> bool:
    thresholds = {"working": 0.3, "episodic": 0.08, "procedural": 0.05, "semantic": 0.03, "spatial": 0.05}
    return current_strength < thresholds.get(memory_type, 0.05)


def decay_preview(memory_type: str, importance: float = 1.0, verification_score: float = 0.0, access_count: int = 0, days: int = 90) -> list:
    profile = DecayProfile.for_memory_type(memory_type)
    ltp_status = compute_ltp_status(importance, verification_score, access_count)
    preview = []
    strength = 1.0
    for day in range(days + 1):
        if day == 0:
            preview.append((0, 1.0))
            continue
        factor = hybrid_decay_factor(float(day), profile, ltp_status)
        boost = access_frequency_boost(access_count)
        combined = min(1.0, factor * boost)
        strength = max(0.0, strength * combined)
        preview.append((day, round(strength, 4)))
        if strength < 0.001:
            break
    return preview