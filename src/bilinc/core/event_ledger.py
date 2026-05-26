"""Append-only semantic event ledger primitives for Bilinc memory operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import re
import time
import uuid
from typing import Any, Iterable, Optional

EVENT_SCHEMA_VERSION = 1
CLOUDEVENTS_SPEC_VERSION = "1.0"


class EventOperation(str, Enum):
    COMMIT = "commit"
    REVISE = "revise"
    FORGET = "forget"
    CONSOLIDATE = "consolidate"
    SNAPSHOT = "snapshot"
    CLAIM_PROJECTED = "claim_projected"
    EVAL_RECEIPT = "eval_receipt"


_EVENT_TYPES = {
    EventOperation.COMMIT.value: "bilinc.memory.committed",
    EventOperation.REVISE.value: "bilinc.memory.revised",
    EventOperation.FORGET.value: "bilinc.memory.forgotten",
    EventOperation.CONSOLIDATE.value: "bilinc.memory.consolidated",
    EventOperation.SNAPSHOT.value: "bilinc.memory.snapshot",
    EventOperation.CLAIM_PROJECTED.value: "bilinc.claim.projected",
    EventOperation.EVAL_RECEIPT.value: "bilinc.eval.receipt.created",
}

_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9._-]{8,}"),
    re.compile(r"\btp-[A-Za-z0-9._-]{8,}"),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\bsecret-token\b", re.IGNORECASE),
]
_SENSITIVE_KEYS = {"token", "secret", "password", "api_key", "apikey", "authorization", "bearer", "credential"}


@dataclass(frozen=True)
class MemoryEvent:
    id: str
    schema_version: int
    specversion: str
    type: str
    source: str
    subject: str
    time: float
    operation: str
    memory_key: Optional[str] = None
    memory_type: Optional[str] = None
    project_id: Optional[str] = None
    org_id: Optional[str] = None
    actor_type: str = "unknown"
    actor_id_hash: Optional[str] = None
    request_id: Optional[str] = None
    before_hash: Optional[str] = None
    after_hash: Optional[str] = None
    payload_ref: Optional[str] = None
    payload_json: dict[str, Any] = field(default_factory=dict)
    audit_log_id: Optional[int] = None
    prev_event_hash: Optional[str] = None
    event_hash: str = ""
    checkpoint_root: Optional[str] = None
    datacontenttype: str = "application/json"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_cloudevent(self) -> dict[str, Any]:
        return {
            "specversion": self.specversion,
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "subject": self.subject,
            "time": self.time,
            "datacontenttype": self.datacontenttype,
            "data": self.payload_json,
        }


def event_type_for_operation(operation: str) -> str:
    return _EVENT_TYPES.get(str(operation), f"bilinc.memory.{str(operation).replace('_', '-')}")


def redact_event_payload(value: Any, *, key_hint: str = "") -> Any:
    key_l = key_hint.lower()
    if any(sensitive in key_l for sensitive in _SENSITIVE_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact_event_payload(v, key_hint=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_event_payload(item, key_hint=key_hint) for item in value]
    if isinstance(value, str):
        redacted = value
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    return value


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def value_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(redact_event_payload(value)).encode("utf-8")).hexdigest()


def hash_actor_id(actor_id: Optional[str]) -> Optional[str]:
    if not actor_id:
        return None
    return hashlib.sha256(str(actor_id).encode("utf-8")).hexdigest()


def event_hash_payload(event: MemoryEvent) -> dict[str, Any]:
    data = event.to_dict()
    data.pop("event_hash", None)
    return data


def compute_event_hash(event: MemoryEvent) -> str:
    return hashlib.sha256(stable_json(event_hash_payload(event)).encode("utf-8")).hexdigest()


def create_memory_event(
    *,
    operation: str,
    subject: str,
    source: str = "bilinc.core.stateplane",
    memory_key: Optional[str] = None,
    memory_type: Optional[str] = None,
    payload_json: Optional[dict[str, Any]] = None,
    before_value: Any = None,
    after_value: Any = None,
    project_id: Optional[str] = None,
    org_id: Optional[str] = None,
    actor_type: str = "unknown",
    actor_id: Optional[str] = None,
    request_id: Optional[str] = None,
    payload_ref: Optional[str] = None,
    audit_log_id: Optional[int] = None,
    prev_event_hash: Optional[str] = None,
    checkpoint_root: Optional[str] = None,
    event_id: Optional[str] = None,
    created_at: Optional[float] = None,
) -> MemoryEvent:
    if not str(operation or "").strip():
        raise ValueError("operation is required")
    if not str(subject or "").strip():
        raise ValueError("subject is required")
    scrubbed_payload = redact_event_payload(payload_json or {})
    event = MemoryEvent(
        id=event_id or f"evt_{uuid.uuid4().hex}",
        schema_version=EVENT_SCHEMA_VERSION,
        specversion=CLOUDEVENTS_SPEC_VERSION,
        type=event_type_for_operation(operation),
        source=source,
        subject=str(subject),
        time=float(created_at or time.time()),
        operation=str(operation),
        memory_key=memory_key,
        memory_type=memory_type,
        project_id=project_id,
        org_id=org_id,
        actor_type=actor_type or "unknown",
        actor_id_hash=hash_actor_id(actor_id),
        request_id=request_id,
        before_hash=value_hash(before_value) if before_value is not None else None,
        after_hash=value_hash(after_value) if after_value is not None else None,
        payload_ref=payload_ref,
        payload_json=scrubbed_payload,
        audit_log_id=audit_log_id,
        prev_event_hash=prev_event_hash,
        checkpoint_root=checkpoint_root,
    )
    return MemoryEvent(**{**event.to_dict(), "event_hash": compute_event_hash(event)})


def event_to_jsonl(event: MemoryEvent) -> str:
    return stable_json(event.to_dict()) + "\n"


def event_from_dict(data: dict[str, Any]) -> MemoryEvent:
    return MemoryEvent(
        id=str(data.get("id")),
        schema_version=int(data.get("schema_version", EVENT_SCHEMA_VERSION)),
        specversion=str(data.get("specversion", CLOUDEVENTS_SPEC_VERSION)),
        type=str(data.get("type") or event_type_for_operation(str(data.get("operation", "")))),
        source=str(data.get("source", "bilinc.core.stateplane")),
        subject=str(data.get("subject", "")),
        time=float(data.get("time", time.time())),
        operation=str(data.get("operation", "")),
        memory_key=data.get("memory_key"),
        memory_type=data.get("memory_type"),
        project_id=data.get("project_id"),
        org_id=data.get("org_id"),
        actor_type=str(data.get("actor_type", "unknown")),
        actor_id_hash=data.get("actor_id_hash"),
        request_id=data.get("request_id"),
        before_hash=data.get("before_hash"),
        after_hash=data.get("after_hash"),
        payload_ref=data.get("payload_ref"),
        payload_json=redact_event_payload(dict(data.get("payload_json") or {})),
        audit_log_id=data.get("audit_log_id"),
        prev_event_hash=data.get("prev_event_hash"),
        event_hash=str(data.get("event_hash", "")),
        checkpoint_root=data.get("checkpoint_root"),
        datacontenttype=str(data.get("datacontenttype", "application/json")),
    )


def event_from_jsonl(line: str) -> MemoryEvent:
    return event_from_dict(json.loads(line))


def export_events_jsonl(events: Iterable[MemoryEvent]) -> str:
    return "".join(event_to_jsonl(event) for event in events)


def replay_events_summary(events_jsonl: str | Iterable[MemoryEvent]) -> dict[str, Any]:
    if isinstance(events_jsonl, str):
        events = [event_from_jsonl(line) for line in events_jsonl.splitlines() if line.strip()]
    else:
        events = list(events_jsonl)
    operation_counts: dict[str, int] = {}
    active_keys: set[str] = set()
    tombstoned_keys: set[str] = set()
    for event in events:
        operation_counts[event.operation] = operation_counts.get(event.operation, 0) + 1
        if event.operation in {EventOperation.COMMIT.value, EventOperation.REVISE.value, EventOperation.CONSOLIDATE.value} and event.memory_key:
            active_keys.add(event.memory_key)
            tombstoned_keys.discard(event.memory_key)
        if event.operation == EventOperation.FORGET.value and event.memory_key:
            active_keys.discard(event.memory_key)
            tombstoned_keys.add(event.memory_key)
    return {
        "event_count": len(events),
        "operation_counts": dict(sorted(operation_counts.items())),
        "active_memory_keys": sorted(active_keys),
        "tombstoned_memory_keys": sorted(tombstoned_keys),
        "first_event_id": events[0].id if events else None,
        "last_event_id": events[-1].id if events else None,
        "checkpoint_root": events[-1].event_hash if events else None,
    }
