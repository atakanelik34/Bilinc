"""Internal FastAPI sidecar for project-isolated Bilinc Cloud memory runtime."""

from __future__ import annotations

import os
import hmac
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from bilinc.cloud.runtime import ProjectRuntimeManager


#: One canonical maximum shared with the public route and the SDK. The sidecar
#: previously capped recall at 50 while the public route accepted 100, so valid
#: requests turned into opaque 503s.
MAX_RECALL_LIMIT = 100
MAX_SNAPSHOT_LIST_LIMIT = 100


class CommitRequest(BaseModel):
    key: str = Field(min_length=1, max_length=512)
    value: Any
    memory_type: str = "semantic"
    importance: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str | None = Field(default=None, max_length=256)
    session_id: str | None = Field(default=None, max_length=256)
    canonical: bool | None = None
    priority: float | None = Field(default=None, ge=0.0, le=1.0)
    ttl: float | None = Field(default=None, gt=0.0)


class RecallRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4096)
    profile: str = "balanced"
    limit: int = Field(default=10, ge=1, le=MAX_RECALL_LIMIT)
    memory_types: list[str] | None = None
    explain: bool = False


class SnapshotCreateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


#: Runtime failures the control plane is allowed to see verbatim. Anything else
#: is reported as a generic runtime error so filesystem paths, SQL, and stack
#: text can never reach a public caller through the sidecar.
_PUBLIC_RUNTIME_ERRORS = frozenset(
    {
        "invalid_project_id",
        "invalid_memory_type",
        "invalid_request",
        "memory_not_found",
        "snapshot_not_found",
        "snapshot_unreadable",
        "version_conflict",
        "state_changed_since_preview",
        "response_too_large",
    }
)

_ERROR_STATUS = {
    "memory_not_found": 404,
    "snapshot_not_found": 404,
    "snapshot_unreadable": 404,
    "version_conflict": 409,
    "state_changed_since_preview": 409,
}


@contextmanager
def _runtime_errors():
    """Translate runtime ``ValueError`` codes into stable sidecar responses."""
    try:
        yield
    except HTTPException:
        raise
    except ValueError as exc:
        code = str(exc)
        if code not in _PUBLIC_RUNTIME_ERRORS:
            code = "invalid_request"
        raise HTTPException(status_code=_ERROR_STATUS.get(code, 400), detail=code) from exc


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
        with _runtime_errors():
            result = await manager.commit(project_id, **payload.model_dump())
        if not result["success"]:
            raise HTTPException(status_code=409, detail="commit_rejected")
        return result

    @app.post("/v1/projects/{project_id}/recall")
    async def recall(
        project_id: str,
        payload: RecallRequest,
        _: None = Depends(require_sidecar_token),
    ):
        with _runtime_errors():
            return await manager.recall(project_id, **payload.model_dump())

    @app.get("/v1/projects/{project_id}/snapshots")
    async def list_snapshots(
        project_id: str,
        limit: int = MAX_SNAPSHOT_LIST_LIMIT,
        _: None = Depends(require_sidecar_token),
    ):
        with _runtime_errors():
            snapshots = await manager.list_snapshots(project_id, limit=limit)
        return {"snapshots": [snapshot.__dict__ for snapshot in snapshots]}

    @app.post("/v1/projects/{project_id}/snapshots")
    async def create_snapshot(
        project_id: str,
        payload: SnapshotCreateRequest | None = None,
        _: None = Depends(require_sidecar_token),
    ):
        request = payload or SnapshotCreateRequest()
        with _runtime_errors():
            snapshot = await manager.create_snapshot(
                project_id,
                label=request.label,
                metadata=request.metadata,
            )
        return {"snapshot": snapshot.__dict__}

    return app
