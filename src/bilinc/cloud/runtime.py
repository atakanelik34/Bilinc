"""Project-isolated hosted runtime manager for Bilinc Cloud."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from bilinc.core.models import MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend


@dataclass(frozen=True)
class ProjectSnapshot:
    """Persisted project snapshot metadata."""

    id: str
    created_at: float
    total_entries: int
    by_type: dict[str, int]
    root_hash: str | None


class ProjectRuntimeManager:
    """
    Keep each hosted project in its own physical SQLite runtime.

    The control plane owns org/project authorization. This manager deliberately
    accepts only a validated project UUID and maps it to:

    ``<base_dir>/<project_id>/bilinc.db``

    That gives the private-beta runtime a hard filesystem boundary while the
    higher-level Cloud control plane keeps billing and entitlements in Postgres.
    """

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir).expanduser()
        self._planes: dict[str, StatePlane] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def normalize_project_id(project_id: str) -> str:
        """Validate and normalize a project UUID before using it as a path segment."""
        try:
            return str(UUID(str(project_id)))
        except (ValueError, AttributeError) as exc:
            raise ValueError("invalid_project_id") from exc

    def project_dir(self, project_id: str) -> Path:
        return self.base_dir / self.normalize_project_id(project_id)

    def db_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "bilinc.db"

    def snapshot_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "snapshots"

    async def get_plane(self, project_id: str) -> StatePlane:
        normalized = self.normalize_project_id(project_id)
        existing = self._planes.get(normalized)
        if existing is not None:
            return existing

        async with self._lock:
            existing = self._planes.get(normalized)
            if existing is not None:
                return existing

            db_path = self.db_path(normalized)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            plane = StatePlane(
                backend=SQLiteBackend(db_path=str(db_path)),
                enable_verification=True,
                enable_audit=True,
            )
            await plane.init()
            plane.init_agm()
            plane.init_knowledge_graph()

            if plane.backend and plane.agm_engine:
                entries = await plane.backend.list_all()
                plane.agm_engine.load_beliefs_from_entries(entries)

            self._planes[normalized] = plane
            return plane

    async def commit(
        self,
        project_id: str,
        *,
        key: str,
        value: Any,
        memory_type: str = MemoryType.SEMANTIC.value,
        importance: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        plane = await self.get_plane(project_id)
        result = await plane.commit_with_agm_async(
            key=key,
            value=value,
            memory_type=memory_type,
            importance=importance,
            metadata=metadata or {},
            source="bilinc_cloud",
        )
        return {
            "success": bool(getattr(result, "success", False)),
            "operation": getattr(getattr(result, "operation", None), "value", None),
            "affected_keys": list(getattr(result, "affected_keys", []) or []),
            "removed_keys": list(getattr(result, "removed_keys", []) or []),
        }

    async def recall(
        self,
        project_id: str,
        *,
        query: str,
        profile: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        plane = await self.get_plane(project_id)
        return await plane.recall_profiled(query=query, profile=profile, limit=limit)

    async def create_snapshot(self, project_id: str) -> ProjectSnapshot:
        normalized = self.normalize_project_id(project_id)
        plane = await self.get_plane(normalized)
        snapshot = await plane.snapshot()
        snapshot_id = f"{snapshot['timestamp']:.6f}"
        payload = {
            "id": snapshot_id,
            "created_at": snapshot["timestamp"],
            "total_entries": snapshot["total_entries"],
            "by_type": snapshot["by_type"],
            "root_hash": snapshot["root_hash"],
            "snapshot": snapshot,
        }

        directory = self.snapshot_dir(normalized)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{snapshot_id}.json").write_text(
            json.dumps(payload, sort_keys=True),
            encoding="utf-8",
        )
        return self._snapshot_from_payload(payload)

    async def list_snapshots(self, project_id: str) -> list[ProjectSnapshot]:
        directory = self.snapshot_dir(project_id)
        if not directory.exists():
            return []

        snapshots: list[ProjectSnapshot] = []
        for path in sorted(directory.glob("*.json"), reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                snapshots.append(self._snapshot_from_payload(payload))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return snapshots

    async def close(self) -> None:
        for plane in self._planes.values():
            backend = getattr(plane, "backend", None)
            if backend and hasattr(backend, "close"):
                await backend.close()
        self._planes.clear()

    @staticmethod
    def _snapshot_from_payload(payload: dict[str, Any]) -> ProjectSnapshot:
        return ProjectSnapshot(
            id=str(payload["id"]),
            created_at=float(payload["created_at"]),
            total_entries=int(payload["total_entries"]),
            by_type={str(key): int(value) for key, value in dict(payload["by_type"]).items()},
            root_hash=str(payload["root_hash"]) if payload.get("root_hash") is not None else None,
        )
