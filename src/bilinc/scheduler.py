"""Phase 7 background scheduler and job orchestration."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from bilinc.core.stateplane import StatePlane


JobHandler = Callable[[], Awaitable[Dict[str, Any]]]


@dataclass
class ScheduledJob:
    """Single scheduled job definition."""

    name: str
    interval_seconds: int
    handler: JobHandler
    last_run_at: float = 0.0
    run_count: int = 0

    def is_due(self, now: float) -> bool:
        if self.last_run_at <= 0:
            return True
        return (now - self.last_run_at) >= self.interval_seconds


class BackgroundScheduler:
    """Simple async scheduler for Phase 7 periodic and trigger-based jobs."""

    def __init__(self, state_plane: StatePlane):
        self.state_plane = state_plane
        self._jobs: Dict[str, ScheduledJob] = {}
        self._task: Optional[asyncio.Task] = None
        self._shutdown = False

    def register_job(self, name: str, interval_seconds: int, handler: JobHandler) -> None:
        """Register or replace a scheduled job."""
        self._jobs[name] = ScheduledJob(
            name=name,
            interval_seconds=max(1, int(interval_seconds)),
            handler=handler,
        )

    def register_phase7_jobs(self) -> None:
        """Register canonical Phase 7 periodic jobs."""
        self.register_job("background_consolidation", 5 * 60, self._job_background_consolidation)
        self.register_job("decay_pass", 30 * 60, self._job_decay_pass)
        self.register_job("kg_maintenance", 60 * 60, self._job_kg_maintenance)
        self.register_job("entity_linking_backlog", 6 * 60 * 60, self._job_entity_linking_backlog)
        self.register_job("health_metrics_report", 24 * 60 * 60, self._job_health_metrics_report)

    def job_names(self) -> List[str]:
        return sorted(self._jobs.keys())

    async def run_job_once(self, name: str) -> Dict[str, Any]:
        """Run one named job immediately."""
        job = self._jobs.get(name)
        if not job:
            raise KeyError(f"unknown job: {name}")
        payload = await job.handler()
        job.last_run_at = time.time()
        job.run_count += 1
        return payload

    async def run_due_jobs(self, force: bool = False) -> Dict[str, Dict[str, Any]]:
        """Run all due jobs and return per-job output payload."""
        now = time.time()
        outputs: Dict[str, Dict[str, Any]] = {}
        for name, job in self._jobs.items():
            if not force and not job.is_due(now):
                continue
            outputs[name] = await self.run_job_once(name)
        return outputs

    async def run_trigger_checks(self) -> Dict[str, Any]:
        """
        Run trigger-based checks:
        - working memory > capacity threshold => immediate consolidation.
        """
        threshold = getattr(self.state_plane, "AUTO_CONSOLIDATE_CAPACITY_THRESHOLD", 0.8)
        usage = self.state_plane.working_memory.capacity_usage
        if usage < threshold:
            return {"triggered": False, "consolidated": 0, "usage": usage, "threshold": threshold}

        consolidated = await self.state_plane.consolidate()
        return {
            "triggered": True,
            "consolidated": consolidated,
            "usage": usage,
            "threshold": threshold,
        }

    async def start(self, tick_seconds: float = 5.0) -> None:
        """Start periodic scheduler loop as a background asyncio task."""
        if self._task and not self._task.done():
            return
        self._shutdown = False
        self._task = asyncio.create_task(self._loop(max(0.5, float(tick_seconds))))

    async def stop(self) -> None:
        """Stop periodic scheduler loop."""
        self._shutdown = True
        if self._task:
            await self._task
            self._task = None

    async def _loop(self, tick_seconds: float) -> None:
        while not self._shutdown:
            await self.run_due_jobs(force=False)
            await self.run_trigger_checks()
            await asyncio.sleep(tick_seconds)

    async def _job_background_consolidation(self) -> Dict[str, Any]:
        consolidated = await self.state_plane.consolidate()
        return {"consolidated": consolidated}

    async def _job_decay_pass(self) -> Dict[str, Any]:
        return await self.state_plane.apply_decay_pass(prune=True)

    async def _job_kg_maintenance(self) -> Dict[str, Any]:
        return await self.state_plane.run_kg_maintenance()

    async def _job_entity_linking_backlog(self) -> Dict[str, Any]:
        return await self.state_plane.run_entity_linking_backlog()

    async def _job_health_metrics_report(self) -> Dict[str, Any]:
        return await self.state_plane.health_metrics_report()
