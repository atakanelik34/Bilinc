"""Deterministic local eval receipts anchored to Bilinc memory events."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import importlib.metadata
import json
import time
from typing import Any, Iterable, Optional

from bilinc.core.event_ledger import EventOperation, MemoryEvent, redact_event_payload, stable_json

RECEIPT_SCHEMA_VERSION = 1


class EvalReceiptError(ValueError):
    """Raised when an eval receipt cannot be created safely."""


@dataclass(frozen=True)
class EvalReceipt:
    receipt_version: int
    receipt_id: str
    created_at: float
    bilinc_version: str
    git_commit: Optional[str]
    dataset_name: str
    dataset_version: Optional[str]
    dataset_hash: str
    run_config_hash: str
    event_ids: list[str]
    event_range_start: str
    event_range_end: str
    checkpoint_root: str
    metrics: dict[str, float]
    metric_definitions: dict[str, str]
    result_artifact_hash: str
    sample_count: int
    profile: Optional[str]
    backend: str
    notes: str
    public_safe: bool
    redactions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bilinc_version() -> str:
    try:
        return importlib.metadata.version("bilinc")
    except Exception:
        return "unknown"


def _hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def _count_samples(result_artifact: Any) -> int:
    if isinstance(result_artifact, dict):
        for key in ("samples", "rows", "results", "items"):
            value = result_artifact.get(key)
            if isinstance(value, list):
                return len(value)
        if "sample_count" in result_artifact:
            try:
                return int(result_artifact["sample_count"])
            except Exception:
                return 0
    if isinstance(result_artifact, list):
        return len(result_artifact)
    return 0


def _receipt_identity_payload(
    *,
    dataset_name: str,
    dataset_version: Optional[str],
    dataset_hash: str,
    run_config_hash: str,
    event_ids: list[str],
    metrics: dict[str, float],
    metric_definitions: dict[str, str],
    result_artifact_hash: str,
    sample_count: int,
    profile: Optional[str],
    backend: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "receipt_version": RECEIPT_SCHEMA_VERSION,
        "dataset_name": dataset_name,
        "dataset_version": dataset_version,
        "dataset_hash": dataset_hash,
        "run_config_hash": run_config_hash,
        "event_ids": event_ids,
        "metrics": metrics,
        "metric_definitions": metric_definitions,
        "result_artifact_hash": result_artifact_hash,
        "sample_count": sample_count,
        "profile": profile,
        "backend": backend,
        "notes": notes,
    }


async def create_eval_receipt(
    *,
    backend: Any,
    dataset_name: str,
    dataset_hash: str,
    event_ids: Iterable[str],
    metrics: dict[str, Any],
    metric_definitions: Optional[dict[str, str]] = None,
    run_config: Optional[dict[str, Any]] = None,
    result_artifact: Any = None,
    dataset_version: Optional[str] = None,
    profile: Optional[str] = None,
    git_commit: Optional[str] = None,
    notes: str = "",
) -> EvalReceipt:
    ids = [str(event_id) for event_id in event_ids]
    if not ids:
        raise EvalReceiptError("event_ids are required")
    if not dataset_name:
        raise EvalReceiptError("dataset_name is required")
    if not dataset_hash:
        raise EvalReceiptError("dataset_hash is required")
    if not hasattr(backend, "list_memory_events"):
        raise EvalReceiptError("backend does not support memory event ledger")

    events: list[MemoryEvent] = await backend.list_memory_events(ids=ids)
    found = {event.id for event in events}
    missing = [event_id for event_id in ids if event_id not in found]
    if missing:
        raise EvalReceiptError(f"missing event references: {', '.join(missing)}")
    by_id = {event.id: event for event in events}
    ordered_events = [by_id[event_id] for event_id in ids]

    scrubbed_config = redact_event_payload(run_config or {})
    scrubbed_artifact = redact_event_payload(result_artifact or {})
    metrics_f = {str(key): float(value) for key, value in sorted((metrics or {}).items())}
    definitions = {str(key): str(value) for key, value in sorted((metric_definitions or {}).items())}
    run_config_hash = _hash(scrubbed_config)
    artifact_hash = _hash(scrubbed_artifact)
    sample_count = _count_samples(scrubbed_artifact)
    backend_name = type(backend).__name__
    checkpoint_root = ordered_events[-1].event_hash

    identity = _receipt_identity_payload(
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        dataset_hash=dataset_hash,
        run_config_hash=run_config_hash,
        event_ids=ids,
        metrics=metrics_f,
        metric_definitions=definitions,
        result_artifact_hash=artifact_hash,
        sample_count=sample_count,
        profile=profile or scrubbed_config.get("profile") if isinstance(scrubbed_config, dict) else profile,
        backend=backend_name,
        notes=notes,
    )
    receipt_id = f"evalrcpt_{_hash(identity)[:32]}"
    receipt = EvalReceipt(
        receipt_version=RECEIPT_SCHEMA_VERSION,
        receipt_id=receipt_id,
        created_at=time.time(),
        bilinc_version=_bilinc_version(),
        git_commit=git_commit,
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        dataset_hash=dataset_hash,
        run_config_hash=run_config_hash,
        event_ids=ids,
        event_range_start=ids[0],
        event_range_end=ids[-1],
        checkpoint_root=checkpoint_root,
        metrics=metrics_f,
        metric_definitions=definitions,
        result_artifact_hash=artifact_hash,
        sample_count=sample_count,
        profile=identity["profile"],
        backend=backend_name,
        notes=notes,
        public_safe=True,
        redactions={
            "run_config_redacted": stable_json(scrubbed_config) != stable_json(run_config or {}),
            "result_artifact_redacted": stable_json(scrubbed_artifact) != stable_json(result_artifact or {}),
        },
    )

    if hasattr(backend, "append_memory_event"):
        existing_receipt_events = [
            event for event in await backend.list_memory_events(operation=EventOperation.EVAL_RECEIPT.value)
            if event.subject == receipt.receipt_id
        ]
        if not existing_receipt_events:
            await backend.append_memory_event(
                operation=EventOperation.EVAL_RECEIPT.value,
                subject=receipt.receipt_id,
                source="bilinc.eval.receipts",
                payload_json={
                    "dataset_name": receipt.dataset_name,
                    "dataset_hash": receipt.dataset_hash,
                    "event_ids": receipt.event_ids,
                    "metrics": receipt.metrics,
                    "receipt_id": receipt.receipt_id,
                    "public_safe": receipt.public_safe,
                },
                checkpoint_root=receipt.checkpoint_root,
            )
    return receipt


def receipt_to_json(receipt: EvalReceipt) -> str:
    return json.dumps(receipt.to_dict(), sort_keys=True, separators=(",", ":"))
