"""
Benchmark 2: Verification Accuracy

Measures: true positive rate, false positive rate, false negative rate
with Z3 SMT invariants on valid vs invalid memory entries.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from bilinc.core.verifier import StateVerifier, VerificationResult
from bilinc.core.models import MemoryEntry, MemoryType


def generate_valid_entries(count: int):
    """Generate entries that should pass verification."""
    entries = []
    for i in range(count):
        entries.append({
            "key": f"valid_{i}",
            "value": f"valid data {i}",
            "memory_type": MemoryType.EPISODIC,
            "importance": 0.5 + (i % 10) * 0.05,
            "is_verified": False,
            "current_strength": 1.0,
            "verification_score": 0.8,
        })
    return entries


def generate_invalid_entries(count: int):
    """Generate entries that should fail verification (empty keys, etc)."""
    entries = []
    for i in range(count):
        # Mix of invalid patterns
        if i % 3 == 0:
            entries.append({
                "key": "",  # Empty key
                "value": f"data {i}",
                "memory_type": MemoryType.EPISODIC,
                "importance": 0.5,
                "is_verified": False,
                "current_strength": 1.0,
                "verification_score": 0.1,
            })
        elif i % 3 == 1:
            entries.append({
                "key": f"invalid_{i}",
                "value": None,  # None value
                "memory_type": MemoryType.EPISODIC,
                "importance": 0.0,
                "is_verified": False,
                "current_strength": 0.0,
                "verification_score": 0.0,
            })
        else:
            entries.append({
                "key": f"weak_{i}",
                "value": f"data {i}",
                "memory_type": MemoryType.EPISODIC,
                "importance": 0.1,
                "is_verified": False,
                "current_strength": 0.05,  # Below threshold
                "verification_score": 0.1,
            })
    return entries


def run():
    print("=" * 60)
    print("Benchmark 2: Verification Accuracy")
    print("=" * 60)

    verifier = StateVerifier()

    # Valid entries
    valid_entries = generate_valid_entries(500)
    valid_results = verifier.verify_state(valid_entries)
    true_positives = sum(1 for r in valid_results if r.valid)
    false_negatives = sum(1 for r in valid_results if not r.valid)

    # Invalid entries
    invalid_entries = generate_invalid_entries(200)
    invalid_results = verifier.verify_state(invalid_entries)
    true_negatives = sum(1 for r in invalid_results if not r.valid)
    false_positives = sum(1 for r in invalid_results if r.valid)

    # Metrics
    total_valid = len(valid_entries)
    total_invalid = len(invalid_entries)
    tpr = true_positives / total_valid if total_valid > 0 else 0
    fpr = false_positives / total_invalid if total_invalid > 0 else 0
    fnr = false_negatives / total_valid if total_valid > 0 else 0

    print(f"\n--- Valid Entries ({total_valid}) ---")
    print(f"  True Positives (correctly passed): {true_positives}")
    print(f"  False Negatives (wrongly rejected): {false_negatives}")
    print(f"  True Positive Rate: {tpr:.2%}")

    print(f"\n--- Invalid Entries ({total_invalid}) ---")
    print(f"  True Negatives (correctly rejected): {true_negatives}")
    print(f"  False Positives (wrongly accepted): {false_positives}")
    print(f"  False Positive Rate: {fpr:.2%}")

    print(f"\n--- Overall ---")
    print(f"  False Negative Rate: {fnr:.2%}")
    print(f"  Accuracy: {(true_positives + true_negatives) / (total_valid + total_invalid):.2%}")

    # Verification speed test
    import time
    start = time.perf_counter()
    verifier.verify_state(generate_valid_entries(1000))
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(f"\n  Verification time for 1000 entries: {elapsed_ms:.1f}ms")
    print(f"  Throughput: {1000 / (elapsed_ms / 1000):.0f} entries/sec")

    return {
        "benchmark": "verification_accuracy",
        "true_positive_rate": round(tpr, 4),
        "false_positive_rate": round(fpr, 4),
        "false_negative_rate": round(fnr, 4),
        "accuracy": round((true_positives + true_negatives) / (total_valid + total_invalid), 4),
        "verification_time_ms_1000": round(elapsed_ms, 1),
    }


if __name__ == "__main__":
    run()
