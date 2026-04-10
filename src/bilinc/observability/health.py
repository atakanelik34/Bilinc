"""
Health checks for Bilinc.

Provides readiness and liveness reporting for core runtime components.
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit, urlunsplit
from typing import Any, Dict, List


_STATUS_SCORE = {"failed": 0, "degraded": 1, "healthy": 2}


def _redact_dsn(dsn: str | None) -> str | None:
    """Return DSN with credentials redacted."""
    if not dsn:
        return dsn
    try:
        parsed = urlsplit(dsn)
        if not parsed.scheme:
            return "<redacted>"
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        user = parsed.username
        auth = f"{user}:***@" if user else ""
        netloc = f"{auth}{host}{port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        return "<redacted>"


class HealthCheck:
    def __init__(self, state_plane=None):
        self.state_plane = state_plane

    def check(self, mode: str = "readiness") -> Dict[str, Any]:
        plane = self.state_plane
        result: Dict[str, Any] = {
            "status": "healthy",
            "mode": mode,
            "timestamp": time.time(),
            "ephemeral": bool(plane and plane.backend is None),
            "issues": [],
            "components": {},
        }

        if plane is None:
            result["status"] = "failed" if mode == "readiness" else "degraded"
            result["issues"].append("state_plane_unavailable")
            return result

        blocking_issues: List[str] = []
        degraded_issues: List[str] = []

        wm = plane.working_memory
        wm_status = "ok"
        if wm.count > wm.max_slots:
            wm_status = "degraded"
            degraded_issues.append("working_memory_over_capacity")
        result["components"]["working_memory"] = {
            "status": wm_status,
            "usage": wm.count,
            "capacity": wm.max_slots,
        }

        backend = getattr(plane, "backend", None)
        if backend is None:
            result["components"]["backend"] = {
                "status": "ephemeral",
                "backend_type": "in_memory",
                "ready": True,
            }
        else:
            backend_component = {
                "status": "ok",
                "backend_type": backend.__class__.__name__.replace("Backend", "").lower(),
                "ready": True,
            }
            try:
                if backend.__class__.__name__ == "SQLiteBackend":
                    conn = backend._get_conn()
                    row = conn.execute(
                        "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
                    ).fetchone()
                    schema_version = row["version"] if row else None
                    backend_component["db_path"] = str(backend.db_path)
                    backend_component["schema_version"] = schema_version
                    expected = getattr(backend, "SCHEMA_VERSION", None)
                    if expected is not None and schema_version != expected:
                        backend_component["status"] = "failed"
                        backend_component["ready"] = False
                        blocking_issues.append("backend_schema_mismatch")
                elif backend.__class__.__name__ == "PostgresBackend":
                    backend_component["ready"] = bool(
                        getattr(backend, "_initialized", False) and getattr(backend, "pool", None)
                    )
                    backend_component["dsn"] = _redact_dsn(getattr(backend, "dsn", None))
                    if not backend_component["ready"]:
                        backend_component["status"] = "failed"
                        blocking_issues.append("backend_uninitialized")
                else:
                    backend_component["ready"] = True
            except Exception as exc:
                backend_component["status"] = "failed"
                backend_component["ready"] = False
                backend_component["error"] = str(exc)
                blocking_issues.append("backend_unavailable")
            result["components"]["backend"] = backend_component

        if getattr(plane, "enable_audit", False):
            if getattr(plane, "audit", None) is None:
                result["components"]["audit"] = {"status": "failed", "enabled": True}
                blocking_issues.append("audit_unavailable")
            else:
                try:
                    integrity = plane.audit.verify_integrity()
                    audit_status = "ok" if integrity.get("valid", False) else "failed"
                    result["components"]["audit"] = {
                        "status": audit_status,
                        "enabled": True,
                        "integrity_valid": integrity.get("valid", False),
                        "root_hash": plane.audit.get_root_hash(),
                    }
                    if audit_status != "ok":
                        blocking_issues.append("audit_integrity_invalid")
                except Exception as exc:
                    result["components"]["audit"] = {
                        "status": "failed",
                        "enabled": True,
                        "error": str(exc),
                    }
                    blocking_issues.append("audit_unavailable")
        else:
            result["components"]["audit"] = {"status": "disabled", "enabled": False}

        if hasattr(plane, "agm_engine") and plane.agm_engine:
            result["components"]["agm_engine"] = {
                "status": "ok",
                "beliefs": len(plane.agm_engine.belief_state.beliefs),
            }
        else:
            result["components"]["agm_engine"] = {"status": "not_initialized"}

        if hasattr(plane, "knowledge_graph") and plane.knowledge_graph:
            kg = plane.knowledge_graph
            result["components"]["knowledge_graph"] = {
                "status": "ok",
                "nodes": kg.stats.get("nodes", 0),
                "edges": kg.stats.get("edges", 0),
            }
        else:
            result["components"]["knowledge_graph"] = {"status": "not_initialized"}

        result["components"]["verification"] = {
            "status": "enabled" if getattr(plane, "enable_verification", False) else "disabled"
        }

        transport_config = getattr(plane, "http_transport_config", None)
        if transport_config:
            http_status = "ok"
            if not transport_config.get("auth_required", True):
                http_status = "degraded"
                degraded_issues.append("http_auth_disabled")
            result["components"]["http_transport"] = {
                "status": http_status,
                "route_prefix": transport_config.get("route_prefix"),
                "auth_required": transport_config.get("auth_required", True),
                "rate_limit": transport_config.get("rate_limit", {}),
            }

        if mode == "liveness":
            if not plane:
                result["status"] = "failed"
            elif blocking_issues or degraded_issues:
                result["status"] = "degraded"
        else:
            if blocking_issues:
                result["status"] = "failed"
            elif degraded_issues:
                result["status"] = "degraded"

        result["issues"] = blocking_issues + degraded_issues
        return result

    def liveness(self) -> Dict[str, Any]:
        return self.check(mode="liveness")

    def readiness(self) -> Dict[str, Any]:
        return self.check(mode="readiness")

    def update_gauge_on_metrics(self, metrics) -> None:
        self.update_gauges(metrics)

    def update_gauges(self, metrics) -> None:
        readiness = self.readiness()
        liveness = self.liveness()

        wm = readiness["components"].get("working_memory", {})
        metrics.set_gauge("working_memory_usage", wm.get("usage", 0))
        metrics.set_gauge("working_memory_capacity", wm.get("capacity", 0))

        agm = readiness["components"].get("agm_engine", {})
        metrics.set_gauge("agm_beliefs", agm.get("beliefs", 0))

        backend = readiness["components"].get("backend", {})
        metrics.set_gauge("backend_ready", 1 if backend.get("ready", False) else 0)

        audit = readiness["components"].get("audit", {})
        if audit.get("enabled", False):
            metrics.set_gauge("audit_integrity_valid", 1 if audit.get("integrity_valid", False) else 0)

        metrics.set_gauge("readiness_status", _STATUS_SCORE[readiness["status"]])
        metrics.set_gauge("liveness_status", _STATUS_SCORE[liveness["status"]])
        metrics.set_gauge("health_status", _STATUS_SCORE[readiness["status"]])
