"""Phase 7 job handlers."""

from __future__ import annotations

from typing import Any, Dict

from bilinc.core.stateplane import StatePlane


async def background_consolidation_job(plane: StatePlane) -> Dict[str, Any]:
    consolidated = await plane.consolidate()
    return {"consolidated": consolidated}


async def decay_pass_job(plane: StatePlane) -> Dict[str, Any]:
    return await plane.apply_decay_pass(prune=True)


async def kg_maintenance_job(plane: StatePlane) -> Dict[str, Any]:
    return await plane.run_kg_maintenance()


async def entity_linking_backlog_job(plane: StatePlane) -> Dict[str, Any]:
    return await plane.run_entity_linking_backlog()


async def health_metrics_report_job(plane: StatePlane) -> Dict[str, Any]:
    return await plane.health_metrics_report()
