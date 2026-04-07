"""
Run all Bilinc benchmarks and print summary.
"""

import sys
import os
import json
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

import bench_retrieval
import bench_verification
import bench_consolidation
import bench_agm_stress


def run_all():
    start = time.time()
    results = {}

    # Benchmark 1: Retrieval
    print("\n")
    results["retrieval"] = bench_retrieval.run()

    # Benchmark 2: Verification
    print("\n")
    results["verification"] = bench_verification.run()

    # Benchmark 3: Consolidation
    print("\n")
    results["consolidation"] = bench_consolidation.run()

    # Benchmark 4: AGM Stress
    print("\n")
    results["agm_stress"] = bench_agm_stress.run()

    # Save results
    elapsed = time.time() - start

    print("\n")
    print("=" * 60)
    print("ALL BENCHMARKS COMPLETE")
    print("=" * 60)
    print(f"Total time: {elapsed:.1f}s")
    print(f"Results: {list(results.keys())}")

    # Save to file
    output_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Results saved to: {output_path}")

    return results


if __name__ == "__main__":
    run_all()
