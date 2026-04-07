"""
Health Check for Bilinc

Provides system health status including all loaded components (AGM, KG, Working Memory).
"""
from typing import Dict, Any


class HealthCheck:
    def __init__(self, state_plane=None):
        self.state_plane = state_plane

    def check(self) -> Dict[str, Any]:
        result = {
            "status": "healthy",
            "components": {}
        }

        if self.state_plane is None:
            return result

        # Working memory
        if hasattr(self.state_plane, "working_memory"):
            wm = self.state_plane.working_memory
            result["components"]["working_memory"] = {
                "status": "ok",
                "usage": wm.count,
                "capacity": wm.max_slots
            }

        # AGM Engine
        if hasattr(self.state_plane, "agm_engine") and self.state_plane.agm_engine:
            result["components"]["agm_engine"] = {
                "status": "ok",
                "beliefs": len(self.state_plane.agm_engine.belief_state.beliefs)
            }
        else:
            result["components"]["agm_engine"] = {"status": "not_initialized"}

        # Knowledge Graph
        if hasattr(self.state_plane, "knowledge_graph") and self.state_plane.knowledge_graph:
            kg = self.state_plane.knowledge_graph
            result["components"]["knowledge_graph"] = {
                "status": "ok",
                "nodes": kg.stats.get("nodes", 0),
                "edges": kg.stats.get("edges", 0)
            }
        else:
            result["components"]["knowledge_graph"] = {"status": "not_initialized"}

        # Verification
        if hasattr(self.state_plane, "enable_verification"):
            result["components"]["verification"] = {
                "status": "enabled" if self.state_plane.enable_verification else "disabled"
            }

        return result

    def update_gauge_on_metrics(self, metrics) -> None:
        """Push current health data to the metrics collector as gauges."""
        self.update_gauges(metrics)

    def update_gauges(self, metrics) -> None:
        """Push current health data to the metrics collector as gauges."""
        health = self.check()
        if "working_memory" in health.get("components", {}):
            wm = health["components"]["working_memory"]
            metrics.set_gauge("working_memory_usage", wm.get("usage", 0))
            metrics.set_gauge("working_memory_capacity", wm.get("capacity", 0))
        if "agm_engine" in health.get("components", {}):
            agm = health["components"]["agm_engine"]
            metrics.set_gauge("agm_beliefs", agm.get("beliefs", 0))
