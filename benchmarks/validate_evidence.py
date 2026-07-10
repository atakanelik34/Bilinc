"""Validate committed benchmark evidence manifests without external dependencies."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


REQUIRED_FIELDS = {
    "schema_version",
    "benchmark",
    "lane",
    "evidence_status",
    "git",
    "dataset",
    "runner",
    "environment",
    "raw_results",
    "metrics",
    "limitations",
    "disallowed_claims",
}
VALID_LANES = {"product-core", "component", "calibrated", "historical", "invalid"}
VALID_STATUSES = {"reproducible", "archived-unverifiable", "invalid"}


def validate_manifest(path: Path) -> list[str]:
    """Return human-readable contract violations for one manifest."""
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{path}: cannot read JSON: {exc}"]

    errors = [f"{path}: missing {field}" for field in sorted(REQUIRED_FIELDS - payload.keys())]
    if errors:
        return errors
    if payload["lane"] not in VALID_LANES:
        errors.append(f"{path}: unsupported lane {payload['lane']!r}")
    if payload["evidence_status"] not in VALID_STATUSES:
        errors.append(f"{path}: unsupported evidence_status {payload['evidence_status']!r}")
    if not isinstance(payload["limitations"], list) or not payload["limitations"]:
        errors.append(f"{path}: limitations must be a non-empty list")
    if not isinstance(payload["disallowed_claims"], list) or not payload["disallowed_claims"]:
        errors.append(f"{path}: disallowed_claims must be a non-empty list")
    for group in ("git", "dataset", "runner", "environment"):
        if not isinstance(payload[group], dict) or not payload[group]:
            errors.append(f"{path}: {group} must be a populated object")
    for result in payload["raw_results"]:
        result_path = path.parents[3] / result["path"]
        if not result_path.is_file():
            errors.append(f"{path}: missing raw result {result['path']}")
            continue
        actual = hashlib.sha256(result_path.read_bytes()).hexdigest()
        if actual != result["sha256"]:
            errors.append(f"{path}: checksum mismatch for {result['path']}")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parent / "evidence"
    manifests = sorted(root.glob("**/manifest.json"))
    if not manifests:
        print("No benchmark evidence manifests found.", file=sys.stderr)
        return 1
    errors = [error for manifest in manifests for error in validate_manifest(manifest)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Validated {len(manifests)} benchmark evidence manifest(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
