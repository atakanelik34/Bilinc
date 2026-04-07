"""
Benchmark 4: AGM Stress Test

Measures:
- 1000 consecutive revise operations
- Average conflict resolution time
- Audit trail growth
"""

import time
import sys
import os
import random
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.adaptive.agm_engine import AGMEngine, ConflictStrategy


def run():
    print("=" * 60)
    print("Benchmark 4: AGM Stress Test")
    print("=" * 60)

    engine = AGMEngine()

    # Phase 1: Populate 50 initial beliefs
    print("\n--- Phase 1: Populating 50 initial beliefs ---")
    for i in range(50):
        entry = MemoryEntry(
            key=f"belief_{i}",
            value=f"initial_value_{i}",
            importance=0.3 + random.uniform(0, 0.5),
            memory_type=MemoryType.SEMANTIC,
        )
        engine.expand(entry)

    print(f"  Beliefs created: {len(engine.belief_state.beliefs)}")

    # Phase 2: 1000 consecutive revise operations (mix of updates + new)
    print("\n--- Phase 2: 1000 consecutive revise operations ---")
    latencies = []
    conflict_count = 0
    rejected_count = 0

    for i in range(1000):
        # Mix: 70% updates to existing keys, 30% new keys
        if random.random() < 0.7 and engine.belief_state.beliefs:
            existing_key = random.choice(list(engine.belief_state.beliefs.keys()))
            value = f"updated_value_{i}"
            importance = random.uniform(0.1, 1.0)
        else:
            existing_key = f"new_belief_{i}"
            value = f"new_value_{i}"
            importance = random.uniform(0.1, 1.0)

        entry = MemoryEntry(
            key=existing_key,
            value=value,
            importance=importance,
            memory_type=MemoryType.SEMANTIC,
        )

        start = time.perf_counter()
        result = engine.revise(entry, strategy=random.choice(list(ConflictStrategy)))
        elapsed = (time.perf_counter() - start) * 1000  # ms
        latencies.append(elapsed)

        if result.conflicts_resolved > 0:
            conflict_count += 1
        if not result.success:
            rejected_count += 1

    latencies.sort()
    n = len(latencies)

    print(f"\n--- Results ---")
    print(f"  Total revise operations: {n}")
    print(f"  Conflicts resolved: {conflict_count}")
    print(f"  Revisions rejected: {rejected_count}")
    print(f"  Final belief count: {len(engine.belief_state.beliefs)}")
    print(f"  Operation log size: {len(engine.operation_log)}")

    print(f"\n--- Timing ---")
    print(f"  p50: {latencies[n // 2]:.3f}ms")
    print(f"  p95: {latencies[int(n * 0.95)]:.3f}ms")
    print(f"  p99: {latencies[int(n * 0.99)]:.3f}ms")
    print(f"  Total time: {sum(latencies):.1f}ms")

    # Phase 3: Multi-conflict resolution stress
    print(f"\n--- Phase 3: Multi-conflict resolution ---")
    multi_conflict_times = []
    for _ in range(100):
        entries = [
            MemoryEntry(key="shared_key", value=f"v_{j}", importance=random.uniform(0.1, 1.0))
            for j in range(5)
        ]
        start = time.perf_counter()
        engine.resolve_multi_conflict(entries, strategy=random.choice(list(ConflictStrategy)))
        elapsed = (time.perf_counter() - start) * 1000
        multi_conflict_times.append(elapsed)

    multi_conflict_times.sort()
    mn = len(multi_conflict_times)
    print(f"  Multi-conflict p50: {multi_conflict_times[mn // 2]:.3f}ms")
    print(f"  Multi-conflict p95: {multi_conflict_times[int(mn * 0.95)]:.3f}ms")

    print(f"\n--- Summary ---")
    print(f"{'Metric':<35} {'Value':<15}")
    print(f"{'-' * 50}")
    print(f"{'Total revise operations':<35} {n}")
    print(f"{'Conflicts resolved':<35} {conflict_count}")
    print(f"{'Avg revise latency (ms)':<35} {sum(latencies) / n:.3f}")
    print(f"{'Final belief count':<35} {len(engine.belief_state.beliefs)}")

    return {
        "benchmark": "agm_stress",
        "operations": n,
        "conflicts_resolved": conflict_count,
        "avg_latency_ms": round(sum(latencies) / n, 3),
        "p50_ms": round(latencies[n // 2], 3),
        "p95_ms": round(latencies[int(n * 0.95)], 3),
    }


if __name__ == "__main__":
    run()
