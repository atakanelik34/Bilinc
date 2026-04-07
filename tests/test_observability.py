"""Tests for the observability layer."""

from __future__ import annotations

import asyncio
import time

from bilinc import StatePlane
from bilinc.observability.health import HealthCheck
from bilinc.observability.metrics import MetricsCollector
from bilinc.storage.sqlite import SQLiteBackend


class TestMetricsCollection:
    def test_metrics_counter_increment(self):
        m = MetricsCollector()
        m.increment("commits_total")
        m.increment("commits_total", 5)
        assert m.get_counter("commits_total") == 6

    def test_metrics_histogram_records(self):
        m = MetricsCollector()
        for val in range(1, 101):
            m.record_latency("recall_latency_ms", float(val))

        stats = m.get_histogram_stats("recall_latency_ms")
        assert stats["count"] == 100
        assert stats["avg"] == 50.5
        assert stats["p50"] == 51.0
        assert stats["p95"] == 96.0

    def test_metrics_reset(self):
        m = MetricsCollector()
        m.increment("test_counter", 100)
        m.record_latency("test_latency", 1.23)
        m.set_gauge("test_gauge", 42.0)

        m.reset()
        assert m.get_counter("test_counter") == 0
        assert m.get_histogram_stats("test_latency")["count"] == 0
        assert m.get_gauge("test_gauge") == 0.0

    def test_metrics_export_prometheus_format_uses_bilinc_prefix(self):
        m = MetricsCollector()
        m.increment("commits_total", 10)
        m.set_gauge("working_memory_usage", 4)
        m.record_latency("commit_latency_ms", 12.5)

        output = m.export_prometheus()

        assert "bilinc_commits_total 10" in output
        assert "# TYPE bilinc_commits_total counter" in output
        assert "bilinc_working_memory_usage 4" in output
        assert "bilinc_commit_latency_ms_count 1" in output
        assert "synaptic" + "_" not in output


class TestHealthCheck:
    def test_health_check_all_healthy(self):
        plane = StatePlane(enable_verification=False, enable_audit=False)
        plane.init_agm()
        plane.init_knowledge_graph()

        report = plane.health.check()

        assert report["status"] == "healthy"
        assert report["components"]["working_memory"]["status"] == "ok"
        assert report["components"]["backend"]["status"] == "ephemeral"
        assert report["components"]["agm_engine"]["status"] == "ok"
        assert report["components"]["knowledge_graph"]["status"] == "ok"
        assert report["components"]["verification"]["status"] == "disabled"

    def test_health_check_persistent_backend_readiness(self, tmp_path):
        plane = StatePlane(
            backend=SQLiteBackend(str(tmp_path / "bilinc-observability.db")),
            enable_verification=False,
            enable_audit=False,
        )

        pre_init = plane.health.readiness()
        assert pre_init["status"] == "failed"
        assert pre_init["components"]["backend"]["status"] == "failed"

        asyncio.run(plane.init())
        post_init = plane.health.readiness()
        assert post_init["status"] == "healthy"
        assert post_init["components"]["backend"]["status"] == "ok"
        assert post_init["components"]["backend"]["schema_version"] == 1

    def test_liveness_can_be_degraded_while_readiness_failed(self, tmp_path):
        plane = StatePlane(
            backend=SQLiteBackend(str(tmp_path / "bilinc-readiness.db")),
            enable_verification=False,
            enable_audit=False,
        )

        assert plane.health.liveness()["status"] == "degraded"
        assert plane.health.readiness()["status"] == "failed"

    def test_health_check_audit_required_but_missing(self):
        plane = StatePlane(enable_verification=False, enable_audit=True)
        plane.audit = None

        report = plane.health.readiness()

        assert report["status"] == "failed"
        assert "audit_unavailable" in report["issues"]
        assert report["components"]["audit"]["status"] == "failed"

    def test_health_gauges_are_written_to_metrics(self):
        plane = StatePlane(enable_verification=False, enable_audit=False)
        plane.init_agm()

        plane.health.update_gauge_on_metrics(plane.metrics)

        assert plane.metrics.get_gauge("working_memory_capacity") == plane.working_memory.max_slots
        assert plane.metrics.get_gauge("agm_beliefs") == 0
        assert plane.metrics.get_gauge("readiness_status") == 2
        assert plane.metrics.get_gauge("liveness_status") == 2

    def test_tracing_spans_via_metrics(self):
        m = MetricsCollector()

        start = time.perf_counter()
        time.sleep(0.01)
        elapsed_ms = (time.perf_counter() - start) * 1000
        m.record_operation("commit", elapsed_ms)

        stats = m.get_histogram_stats("commit_latency_ms")
        assert stats["count"] == 1
        assert m.get_counter("commits_total") == 1
        assert stats["p50"] >= 10.0

    def test_http_transport_dev_mode_is_reported_as_degraded(self):
        plane = StatePlane(enable_verification=False, enable_audit=False)
        plane.http_transport_config = {
            "route_prefix": "/mcp",
            "auth_required": False,
            "rate_limit": {"max_tokens": 5, "refill_rate": 1.0},
        }

        report = plane.health.readiness()

        assert report["status"] == "degraded"
        assert "http_auth_disabled" in report["issues"]
        assert report["components"]["http_transport"]["status"] == "degraded"
