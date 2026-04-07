"""
Benchmark 1: Memory Retrieval Latency

Measures: p50, p95, p99 query latency for 100 / 1000 entries.
"""

import time
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from bilinc import StatePlane
from bilinc.core.models import MemoryType


def generate_entries(count: int):
    """Generate synthetic memory entries."""
    entries = []
    for i in range(count):
        entries.append({
            "key": f"entry_{i}",
            "value": f"test data for entry {i} with some extra text to make it realistic entry_{i}",
            "memory_type": MemoryType.EPISODIC,
        })
    return entries


def bench_commit_latency(plane: StatePlane, entries: list) -> dict:
    """Benchmark commit latency."""
    latencies = []
    for e in entries[:200]:  # limit to 200 for speed
        start = time.perf_counter()
        plane.commit_sync(**e)
        elapsed = (time.perf_counter() - start) * 1000  # ms
        latencies.append(elapsed)

    latencies.sort()
    n = len(latencies)
    return {
        "operation": "commit",
        "count": n,
        "p50_ms": round(latencies[n // 2], 3),
        "p95_ms": round(latencies[int(n * 0.95)], 3),
        "p99_ms": round(latencies[int(n * 0.99)], 3),
        "total_ms": round(sum(latencies), 3),
    }


def bench_recall_latency(plane: StatePlane, count: int) -> dict:
    """Benchmark full memory recall latency."""
    latencies = []
    for _ in range(50):  # 50 recall runs
        start = time.perf_counter()
        entries = plane.recall_all_sync()
        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)

    latencies.sort()
    n = len(latencies)
    return {
        "operation": "recall_all",
        "count": n,
        "entries_returned": len(entries),
        "p50_ms": round(latencies[n // 2], 3),
        "p95_ms": round(latencies[int(n * 0.95)], 3),
        "p99_ms": round(latencies[int(n * 0.99)], 3),
    }


def run():
    print("=" * 60)
    print("Benchmark 1: Memory Retrieval Latency")
    print("=" * 60)

    # Test with 100 entries
    plane_100 = StatePlane(enable_verification=False, enable_audit=False)
    entries_100 = generate_entries(100)
    for e in entries_100:
        plane_100.commit_sync(**e)

    result_100_recall = bench_recall_latency(plane_100, 100)
    print(f"\n--- 100 entries ---")
    print(f"  Recall p50: {result_100_recall['p50_ms']}ms")
    print(f"  Recall p95: {result_100_recall['p95_ms']}ms")
    print(f"  Recall p99: {result_100_recall['p99_ms']}ms")
    print(f"  Entries returned: {result_100_recall['entries_returned']}")

    # Test with 1000 entries
    plane_1000 = StatePlane(enable_verification=False, enable_audit=False)
    entries_1000 = generate_entries(1000)
    commit_result = bench_commit_latency(plane_1000, entries_1000)
    result_1000_recall = bench_recall_latency(plane_1000, 1000)

    print(f"\n--- 1000 entries ---")
    print(f"  Commit p50: {commit_result['p50_ms']}ms")
    print(f"  Commit p95: {commit_result['p95_ms']}ms")
    print(f"  Commit p99: {commit_result['p99_ms']}ms")
    print(f"  Recall p50: {result_1000_recall['p50_ms']}ms")
    print(f"  Recall p95: {result_1000_recall['p95_ms']}ms")
    print(f"  Recall p99: {result_1000_recall['p99_ms']}ms")
    print(f"  Entries returned: {result_1000_recall['entries_returned']}")

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(f"{'Metric':<25} {'100 entries':<18} {'1000 entries':<18}")
    print(f"{'-' * 61}")
    print(f"{'Recall p50 (ms)':<25} {result_100_recall['p50_ms']:<18} {result_1000_recall['p50_ms']:<18}")
    print(f"{'Recall p95 (ms)':<25} {result_100_recall['p95_ms']:<18} {result_1000_recall['p95_ms']:<18}")
    print(f"{'Recall p99 (ms)':<25} {result_100_recall['p99_ms']:<18} {result_1000_recall['p99_ms']:<18}")

    return {
        "benchmark": "retrieval_latency",
        "100_entries": result_100_recall,
        "1000_entries": {**commit_result, **result_1000_recall},
    }


if __name__ == "__main__":
    run()
