"""Internal FastAPI sidecar for project-isolated Bilinc Cloud memory runtime."""

from __future__ import annotations

import os
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from bilinc.cloud.runtime import ProjectRuntimeManager


class CommitRequest(BaseModel):
    key: str = Field(min_length=1, max_length=512)
    value: Any
    memory_type: str = "semantic"
    importance: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecallRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4096)
    profile: str = "balanced"
    limit: int = Field(default=10, ge=1, le=50)


def create_app(
    *,
    runtime_dir: str | Path | None = None,
    sidecar_token: str | None = None,
) -> FastAPI:
    """Create an internal-only sidecar app with explicit service-token auth."""
    runtime_root = runtime_dir or os.getenv("BILINC_CLOUD_RUNTIME_DIR", "~/.bilinc-cloud-runtime")
    expected_token = sidecar_token or os.getenv("BILINC_CLOUD_SIDECAR_TOKEN")
    if not expected_token:
        raise RuntimeError("BILINC_CLOUD_SIDECAR_TOKEN is required")

    manager = ProjectRuntimeManager(runtime_root)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await manager.close()

    app = FastAPI(title="Bilinc Cloud Runtime", version="0.1.0", lifespan=lifespan)
    app.state.runtime_manager = manager

    async def require_sidecar_token(x_bilinc_sidecar_token: str | None = Header(default=None)) -> None:
        if not x_bilinc_sidecar_token or not hmac.compare_digest(x_bilinc_sidecar_token, expected_token):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/health")
    async def health(_: None = Depends(require_sidecar_token)):
        return {"status": "ok", "runtimeIsolation": "project_filesystem"}

    @app.post("/v1/projects/{project_id}/commit")
    async def commit(
        project_id: str,
        payload: CommitRequest,
        _: None = Depends(require_sidecar_token),
    ):
        try:
            result = await manager.commit(project_id, **payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not result["success"]:
            raise HTTPException(status_code=409, detail="commit_rejected")
        return result

    @app.post("/v1/projects/{project_id}/recall")
    async def recall(
        project_id: str,
        payload: RecallRequest,
        _: None = Depends(require_sidecar_token),
    ):
        try:
            return await manager.recall(project_id, **payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/projects/{project_id}/snapshots")
    async def list_snapshots(project_id: str, _: None = Depends(require_sidecar_token)):
        try:
            snapshots = await manager.list_snapshots(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshots": [snapshot.__dict__ for snapshot in snapshots]}

    @app.post("/v1/projects/{project_id}/snapshots")
    async def create_snapshot(project_id: str, _: None = Depends(require_sidecar_token)):
        try:
            snapshot = await manager.create_snapshot(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": snapshot.__dict__}

    return app
