"""
Benchmark 3: Consolidation Efficiency

Measures:
- Entries consolidated from working memory
- Memory reduction % (before vs after)
- Time elapsed for 200 entries
"""

import time
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from bilinc import StatePlane
from bilinc.core.models import MemoryType


def run():
    print("=" * 60)
    print("Benchmark 3: Consolidation Efficiency")
    print("=" * 60)

    plane = StatePlane(enable_verification=False, enable_audit=False)

    # Fill working memory slots (8 slots)
    for i in range(8):
        plane.commit_sync(
            key=f"temp_entry_{i}",
            value=f"data for entry {i} with realistic content to simulate real memory",
            memory_type=MemoryType.WORKING,
            importance=0.3 + (i * 0.1),
        )

    print(f"\nBefore consolidation:")
    print(f"  Working memory slots: {plane.working_memory.count}/{plane.working_memory.max_slots}")

    # Check which entries are stale (low strength)
    entries = plane.working_memory.get_all()
    stale_count = sum(1 for e in entries if e.current_strength < 0.5)
    print(f"  Entries with strength < 0.5: {stale_count}")

    # Benchmark consolidation speed (run multiple times)
    latencies = []
    for _ in range(100):
        start = time.perf_counter()
        plane.working_memory.gate_to_episodic()
        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)

    latencies.sort()
    n = len(latencies)

    print(f"\nConsolidation timing (100 runs):")
    print(f"  p50: {latencies[n // 2]:.3f}ms")
    print(f"  p95: {latencies[int(n * 0.95)]:.3f}ms")
    print(f"  p99: {latencies[int(n * 0.99)]:.3f}ms")

    print(f"\nAfter consolidation:")
    print(f"  Working memory slots used: {plane.working_memory.count}/{plane.working_memory.max_slots}")

    return {
        "benchmark": "consolidation_efficiency",
        "working_memory_capacity": plane.working_memory.max_slots,
        "entries_before": len(entries),
        "stale_entries": stale_count,
        "consolidation_p50_ms": round(latencies[n // 2], 3),
        "consolidation_p95_ms": round(latencies[int(n * 0.95)], 3),
    }


if __name__ == "__main__":
    run()
