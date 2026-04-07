"""Tests for Observability Layer (Step 5.3)."""
import time
import pytest
from bilinc.observability.metrics import MetricsCollector
from bilinc.observability.health import HealthCheck


class TestMetricsCollection:
    def test_metrics_counter_increment(self):
        """Incrementing a counter increases the value."""
        m = MetricsCollector()
        m.increment("commits_total")
        m.increment("commits_total", 5)
        assert m.get_counter("commits_total") == 6

    def test_metrics_histogram_records(self):
        """Recording latency populates the histogram stats."""
        m = MetricsCollector()
        for val in range(1, 101):
            m.record_latency("recall_latency_ms", float(val))
        
        stats = m.get_histogram_stats("recall_latency_ms")
        assert stats["count"] == 100
        assert stats["avg"] == 50.5
        assert stats["p50"] == 51.0  # index 50 of [1..100] is 51
        assert stats["p95"] == 96.0  # index 95 of [1..100] is 96

    def test_metrics_reset(self):
        """Reset clears all metrics."""
        m = MetricsCollector()
        m.increment("test_counter", 100)
        m.record_latency("test_latency", 1.23)
        m.set_gauge("test_gauge", 42.0)
        
        m.reset()
        assert m.get_counter("test_counter") == 0
        assert m.get_histogram_stats("test_latency")["count"] == 0
        assert m.get_gauge("test_gauge") == 0.0

    def test_metrics_export_prometheus_format(self):
        """Prometheus export generates the correct text format."""
        m = MetricsCollector()
        m.increment("commits_total", 10)
        m.set_gauge("working_memory_usage", 4)

        output = m.export_prometheus()
        
        assert "synaptic_commits_total_total 10" in output
        assert "# TYPE synaptic_commits_total counter" in output
        assert "synaptic_working_memory_usage 4" in output
        assert "# HELP synaptic_uptime_seconds" in output


class TestHealthCheck:
    def test_health_check_all_healthy(self):
        """A fully initialized StatePlane reports all components healthy."""
        from bilinc import StatePlane
        plane = StatePlane(enable_verification=False, enable_audit=False)
        plane.init_agm()
        plane.init_knowledge_graph()
        
        health = plane.health
        report = health.check()
        
        assert report["status"] == "healthy"
        assert report["components"]["working_memory"]["status"] == "ok"
        assert report["components"]["agm_engine"]["status"] == "ok"
        assert report["components"]["knowledge_graph"]["status"] == "ok"
        assert report["components"]["verification"]["status"] == "disabled"

    def test_health_check_missing_components(self):
        """Uninitialized AGM/KG report as not_initialized."""
        from bilinc import StatePlane
        plane = StatePlane(enable_verification=False, enable_audit=False)
        
        report = plane.health.check()
        assert report["components"]["agm_engine"]["status"] == "not_initialized"
        assert report["components"]["knowledge_graph"]["status"] == "not_initialized"

    def test_tracing_spans_via_metrics(self):
        """Simulate tracing by recording start/end times and calculating duration."""
        m = MetricsCollector()
        
        # Simulate a commit span
        start = time.perf_counter()
        time.sleep(0.01)  # 10ms work
        elapsed_ms = (time.perf_counter() - start) * 1000
        m.record_latency("commit_latency_ms", elapsed_ms)
        m.increment("commits_total")
        
        stats = m.get_histogram_stats("commit_latency_ms")
        assert stats["count"] == 1
        assert stats["p50"] >= 10.0  # At least 10ms as we slept
