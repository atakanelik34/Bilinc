"""Opt-in capture rows for Bilinc retrieval evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import re
import time
from typing import Any, Iterable

SCHEMA_VERSION = 1
MAX_QUERY_CHARS = 512

_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9._-]+"),
    re.compile(r"\btp-[A-Za-z0-9._-]+"),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
]


@dataclass(frozen=True)
class EvalCaptureRow:
    schema_version: int
    tool_name: str
    query: str
    retrieved_keys: list[str]
    retrieved_scores: list[float]
    memory_types: list[str]
    latency_ms: int
    created_at: float
    detail: dict[str, Any] = field(default_factory=dict)


def capture_enabled(config: dict[str, Any] | None = None) -> bool:
    """Return true only when eval capture is explicitly enabled."""
    config = config or {}
    if "enabled" in config:
        return bool(config["enabled"])
    if "eval_capture" in config:
        return bool(config["eval_capture"])
    value = os.environ.get("BILINC_EVAL_CAPTURE", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def scrub_query(query: str) -> str:
    """Redact token-shaped substrings and cap query length."""
    scrubbed = str(query or "")
    for pattern in _SECRET_PATTERNS:
        scrubbed = pattern.sub("[REDACTED]", scrubbed)
    if len(scrubbed) > MAX_QUERY_CHARS:
        scrubbed = scrubbed[:MAX_QUERY_CHARS] + "…"
    return scrubbed


def scrub_detail(value: Any) -> Any:
    """Recursively redact token-shaped strings inside capture detail payloads."""
    if isinstance(value, str):
        return scrub_query(value)
    if isinstance(value, list):
        return [scrub_detail(item) for item in value]
    if isinstance(value, tuple):
        return [scrub_detail(item) for item in value]
    if isinstance(value, dict):
        return {str(key): scrub_detail(item) for key, item in value.items()}
    return value


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def row_to_jsonl(row: EvalCaptureRow) -> str:
    return json.dumps(asdict(row), sort_keys=True, separators=(",", ":")) + "\n"


def row_from_jsonl(line: str) -> EvalCaptureRow:
    data = json.loads(line)
    return EvalCaptureRow(
        schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        tool_name=str(data.get("tool_name", "")),
        query=str(data.get("query", "")),
        retrieved_keys=[str(k) for k in data.get("retrieved_keys", [])],
        retrieved_scores=[float(s) for s in data.get("retrieved_scores", [])],
        memory_types=[str(mt) for mt in data.get("memory_types", [])],
        latency_ms=int(data.get("latency_ms", 0)),
        created_at=float(data.get("created_at", time.time())),
        detail=dict(data.get("detail", {}) or {}),
    )


def row_from_results(
    *,
    tool_name: str,
    query: str,
    results: Iterable[Any],
    latency_ms: int,
    detail: dict[str, Any] | None = None,
) -> EvalCaptureRow:
    keys: list[str] = []
    scores: list[float] = []
    memory_types: list[str] = []
    for result in results:
        if isinstance(result, dict):
            key = result.get("key")
            score = result.get("score", 0.0)
            memory_type = result.get("memory_type", "")
        else:
            key = getattr(result, "key", None)
            score = getattr(result, "score", 0.0)
            raw_type = getattr(result, "memory_type", "")
            memory_type = getattr(raw_type, "value", raw_type)
        if key is None:
            continue
        key_s = str(key)
        key_s = scrub_query(key_s)
        if key_s in keys:
            continue
        keys.append(key_s)
        try:
            scores.append(float(score))
        except (TypeError, ValueError):
            scores.append(0.0)
        memory_types.append(str(memory_type or ""))
    return EvalCaptureRow(
        schema_version=SCHEMA_VERSION,
        tool_name=tool_name,
        query=scrub_query(query),
        retrieved_keys=keys,
        retrieved_scores=scores,
        memory_types=memory_types,
        latency_ms=max(0, int(latency_ms)),
        created_at=time.time(),
        detail=scrub_detail(detail or {}),
    )
