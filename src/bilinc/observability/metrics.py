"""
MetricsCollector for Bilinc.

Tracks counters, latency summaries, and gauges for in-process observability.
Exports Prometheus-compatible text using Bilinc metric names.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List


METRIC_PREFIX = "bilinc"


def _sanitize_metric_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)


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
        """Record a latency observation in milliseconds."""
        with self._lock:
            hist = self._histograms.setdefault(name, [])
            hist.append(value_ms)
            if len(hist) > 10000:  # Cap to prevent OOM
                del hist[:5000]

    def record_operation(self, operation: str, elapsed_ms: float) -> None:
        """Record a successful operation count and latency."""
        self.increment(f"{operation}s_total")
        self.record_latency(f"{operation}_latency_ms", elapsed_ms)

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
            vals = list(self._histograms.get(name, []))
        if not vals:
            return {"count": 0, "avg": 0, "p50": 0, "p95": 0}

        s = sorted(vals)
        n = len(s)
        return {
            "count": n,
            "avg": sum(vals) / n,
            "p50": s[min(n - 1, int(n * 0.5))],
            "p95": s[min(n - 1, int(n * 0.95))],
        }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._gauges.clear()

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text exposition format."""
        with self._lock:
            counters = dict(self._counters)
            histograms = {name: list(values) for name, values in self._histograms.items()}
            gauges = dict(self._gauges)

        lines = [
            f"# HELP {METRIC_PREFIX}_uptime_seconds Time since collector started",
            f"# TYPE {METRIC_PREFIX}_uptime_seconds gauge",
            f"{METRIC_PREFIX}_uptime_seconds {time.time() - self._start_time:.2f}",
        ]

        for raw_name, val in sorted(counters.items()):
            name = _sanitize_metric_name(raw_name)
            metric_name = f"{METRIC_PREFIX}_{name}" if name.endswith("_total") else f"{METRIC_PREFIX}_{name}_total"
            lines.append(f"# HELP {metric_name} Counter metric for {name}")
            lines.append(f"# TYPE {metric_name} counter")
            lines.append(f"{metric_name} {val}")

        for raw_name, vals in sorted(histograms.items()):
            name = _sanitize_metric_name(raw_name)
            metric_name = f"{METRIC_PREFIX}_{name}"
            lines.append(f"# HELP {metric_name} Latency summary for {name}")
            lines.append(f"# TYPE {metric_name} summary")
            lines.append(f"{metric_name}_count {len(vals)}")
            lines.append(f"{metric_name}_sum {sum(vals):.4f}")

        for raw_name, val in sorted(gauges.items()):
            name = _sanitize_metric_name(raw_name)
            metric_name = f"{METRIC_PREFIX}_{name}"
            lines.append(f"# HELP {metric_name} Gauge metric for {name}")
            lines.append(f"# TYPE {metric_name} gauge")
            lines.append(f"{metric_name} {val}")

        return "\n".join(lines)
