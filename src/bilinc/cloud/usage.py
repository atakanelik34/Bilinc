"""Quota evaluation helpers for Bilinc Cloud runtime decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    remaining: Optional[int]
    reason: str
    threshold: str


def evaluate_quota(*, used: int, limit: Optional[int], requested: int = 1) -> QuotaDecision:
    """Evaluate a deterministic quota decision."""
    if requested <= 0:
        raise ValueError("requested must be positive")
    if used < 0:
        raise ValueError("used must be non-negative")

    if limit is None:
        return QuotaDecision(allowed=True, remaining=None, reason="unlimited", threshold="none")

    remaining = max(0, limit - used)
    projected = used + requested
    if projected > limit:
        return QuotaDecision(
            allowed=False,
            remaining=remaining,
            reason="quota_exceeded",
            threshold="hard_stop",
        )

    percentage = projected / limit if limit else 1.0
    threshold = "warning_80" if percentage >= 0.8 else "none"
    return QuotaDecision(
        allowed=True,
        remaining=max(0, limit - projected),
        reason="within_quota",
        threshold=threshold,
    )
