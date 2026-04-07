"""
MetricsCollector for Bilinc

Tracks counters (commit/recall counts), histograms (latency), and gauges (memory usage).
Compatible with Prometheus export format for Grafana dashboards.
"""
import time
import threading
from typing import Dict, List, Any


class MetricsCollector:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._gauges: Dict[str, float] = {}
        self._start_time = time.time()

    def increment(self, name: str, value: int = 1) -> None:
        """Increment a counter metric."""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def record_latency(self, name: str, value_ms: float) -> None:
        """Record an observation for latency histogram."""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value_ms)

    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge metric to a specific value."""
        with self._lock:
            self._gauges[name] = value

    def get_counter(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0)

    def get_gauge(self, name: str) -> float:
        with self._lock:
            return self._gauges.get(name, 0.0)

    def get_histogram_stats(self, name: str) -> Dict[str, float]:
        with self._lock:
            vals = self._histograms.get(name, [])
        if not vals:
            return {"count": 0, "avg": 0, "p50": 0, "p95": 0}
        
        s = sorted(vals)
        n = len(s)
        return {
            "count": n,
            "avg": sum(vals) / n,
            "p50": s[int(n * 0.5)],
            "p95": s[int(n * 0.95)],
        }

    def reset(self) -> None:
        self._counters.clear()
        self._histograms.clear()
        self._gauges.clear()

    def export_prometheus(self) -> str:
        """Exports all metrics in Prometheus text exposition format."""
        lines = [
            "# HELP synaptic_uptime_seconds Time since collector started",
            "# TYPE synaptic_uptime_seconds gauge",
            f"synaptic_uptime_seconds {time.time() - self._start_time:.2f}",
        ]
        
        for name, val in self._counters.items():
            lines.append(f"# HELP synaptic_{name}")
            lines.append(f"# TYPE synaptic_{name} counter")
            lines.append(f"synaptic_{name}_total {val}")

        for name, vals in self._histograms.items():
            stats = {
                "count": len(vals),
                "sum": sum(vals),
            }
            lines.append(f"# HELP synaptic_{name}")
            lines.append(f"# TYPE synaptic_{name} summary")
            lines.append(f"synaptic_{name}_count {stats['count']}")
            lines.append(f"synaptic_{name}_sum_ms {stats['sum']:.4f}")
        
        for name, val in self._gauges.items():
            lines.append(f"# HELP synaptic_{name}")
            lines.append(f"# TYPE synaptic_{name} gauge")
            lines.append(f"synaptic_{name} {val}")

        return "\n".join(lines)
