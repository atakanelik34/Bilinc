"""Plan entitlement contracts for Bilinc Cloud."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PlanEntitlements:
    max_projects: Optional[int]
    max_members: Optional[int]
    max_api_keys: Optional[int]
    monthly_memory_writes: Optional[int]
    monthly_recall_ops: Optional[int]
    monthly_contradiction_reports: Optional[int]
    retention_days: Optional[int]
    snapshot_retention_days: Optional[int]
    allowed_recall_profiles: tuple[str, ...]


PLAN_ENTITLEMENTS = {
    "cloud_free": PlanEntitlements(
        max_projects=1,
        max_members=1,
        max_api_keys=1,
        monthly_memory_writes=5_000,
        monthly_recall_ops=10_000,
        monthly_contradiction_reports=0,
        retention_days=7,
        snapshot_retention_days=3,
        allowed_recall_profiles=("fast", "balanced"),
    ),
    "pro": PlanEntitlements(
        max_projects=3,
        max_members=1,
        max_api_keys=5,
        monthly_memory_writes=50_000,
        monthly_recall_ops=150_000,
        monthly_contradiction_reports=200,
        retention_days=30,
        snapshot_retention_days=30,
        allowed_recall_profiles=("fast", "balanced", "verified"),
    ),
    "team": PlanEntitlements(
        max_projects=10,
        max_members=10,
        max_api_keys=25,
        monthly_memory_writes=250_000,
        monthly_recall_ops=1_000_000,
        monthly_contradiction_reports=2_000,
        retention_days=90,
        snapshot_retention_days=90,
        allowed_recall_profiles=("fast", "balanced", "verified", "deep"),
    ),
    "scale": PlanEntitlements(
        max_projects=50,
        max_members=25,
        max_api_keys=100,
        monthly_memory_writes=1_000_000,
        monthly_recall_ops=5_000_000,
        monthly_contradiction_reports=10_000,
        retention_days=365,
        snapshot_retention_days=365,
        allowed_recall_profiles=("fast", "balanced", "verified", "deep"),
    ),
}


def entitlements_for_plan(plan_key: str) -> PlanEntitlements:
    """Return plan entitlements or fail closed for unknown plan keys."""
    try:
        return PLAN_ENTITLEMENTS[plan_key]
    except KeyError as exc:
        raise ValueError(f"unknown plan key: {plan_key}") from exc
