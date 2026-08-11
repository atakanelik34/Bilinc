"""Read-only, deterministic graph projection diagnostics for Bilinc.

KG v1 deliberately stops at a preview boundary. This module reads explicit
memory metadata and structured claims, then returns JSON-safe candidate nodes,
edges, and doctor findings. It never mutates a memory entry, StatePlane,
SQLite backend, or KnowledgeGraph.
"""

from __future__ import annotations

import json
import math
import re
import time
from typing import Any, Iterable

from bilinc.core.models import MemoryEntry, MemoryType


REDACTED = "[REDACTED]"
PREVIEW_SCHEMA_VERSION = "kg-v1-preview"
_UUID_PATTERN = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SECRET_FIELD_PATTERN = re.compile(
    r"(?i)(secret|token|password|api[_-]?key|private[_-]?key|credential|authorization|bearer)"
)
_SECRET_TEXT_PATTERN = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._~+/=-]{12,}|"
    r"(?:sk|pypi|bil_live|akia|asia)[-_a-z0-9]{12,}|"
    r"(?:secret|token|password|api[_-]?key|private[_-]?key)\s*[:=]\s*[^,\s;]+)"
)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+=-]*")


def _normalize_name(value: Any) -> str:
    """Normalize a display value without serializing arbitrary containers."""
    if value is None or isinstance(value, (dict, list, tuple, set, frozenset)):
        return ""
    return " ".join(str(value).strip().split())


def _dedupe_key(value: Any) -> str:
    return _normalize_name(value).casefold()


def _stable_sort_key(value: Any) -> str:
    if isinstance(value, dict):
        pairs = sorted((str(key), _stable_sort_key(item)) for key, item in value.items())
        return json.dumps(pairs, ensure_ascii=True, separators=(",", ":"))
    if isinstance(value, (set, frozenset)):
        return json.dumps(
            sorted(_stable_sort_key(item) for item in value),
            ensure_ascii=True,
            separators=(",", ":"),
        )
    if isinstance(value, (list, tuple)):
        return json.dumps(
            [_stable_sort_key(item) for item in value],
            ensure_ascii=True,
            separators=(",", ":"),
        )
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=_stable_sort_key)
    return [value]


def _coerce_timestamp(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return timestamp if math.isfinite(timestamp) else None


def _timestamp_in_past(value: Any, now: float | None) -> bool:
    timestamp = _coerce_timestamp(value)
    return timestamp is not None and now is not None and timestamp <= now


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"false", "0", "no", "off", "inactive"}:
            return False
        if lowered in {"true", "1", "yes", "on", "active"}:
            return True
    return bool(value)


def _looks_sensitive_token(token: str) -> bool:
    """Detect credential-like values conservatively before graph projection."""
    cleaned = str(token or "").strip().strip("()[]{}<>,.;")
    if not cleaned or _UUID_PATTERN.fullmatch(cleaned):
        return False
    if _SECRET_FIELD_PATTERN.search(cleaned):
        return True
    upper = cleaned.upper()
    if upper.startswith(("AKIA", "ASIA", "SK_", "SK-", "PYPI-", "BIL_LIVE_")):
        return True
    if len(cleaned) >= 24 and re.fullmatch(r"[A-Za-z0-9_./+=:-]+", cleaned):
        has_alpha = any(char.isalpha() for char in cleaned)
        has_digit = any(char.isdigit() for char in cleaned)
        mostly_upper = sum(1 for char in cleaned if char.isupper()) >= max(8, len(cleaned) // 2)
        if has_alpha and (has_digit or mostly_upper):
            return True
    return False


def _contains_secret_like(value: Any, key_hint: str = "") -> bool:
    if value in (None, ""):
        return False
    if _SECRET_FIELD_PATTERN.search(str(key_hint or "")):
        return True
    text = str(value)
    if _SECRET_TEXT_PATTERN.search(text):
        return True
    return any(_looks_sensitive_token(token) for token in _TOKEN_PATTERN.findall(text))


def _safe_text(value: Any) -> str:
    """Redact credential-like substrings while retaining useful evidence text."""
    text = _normalize_name(value)
    if not text:
        return ""
    text = _SECRET_TEXT_PATTERN.sub(REDACTED, text)

    def replace_token(match: re.Match[str]) -> str:
        token = match.group(0)
        return REDACTED if _looks_sensitive_token(token) else token

    return _TOKEN_PATTERN.sub(replace_token, text)


def _safe_projection_value(value: Any, *, key_hint: str = "") -> Any:
    """Make projected metadata JSON-safe and prevent secret propagation."""
    if value is None:
        return None
    if _SECRET_FIELD_PATTERN.search(str(key_hint or "")):
        return REDACTED
    if str(key_hint or "").casefold() in {"sensitivity", "classification"}:
        normalized = _normalize_name(value).casefold()
        if normalized in {"public", "internal", "private", "secret", "confidential"}:
            return normalized
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return _safe_text(value) if isinstance(value, str) else value
    if hasattr(value, "value") and not isinstance(value, (dict, list, tuple, set, frozenset)):
        return _safe_projection_value(value.value, key_hint=key_hint)
    if isinstance(value, dict):
        return {
            str(key): _safe_projection_value(item, key_hint=str(key))
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_safe_projection_value(item, key_hint=key_hint) for item in value]
        if isinstance(value, (set, frozenset)):
            items.sort(key=_stable_sort_key)
        return items
    return _safe_text(value)


def _safe_name(value: Any, *, key_hint: str = "") -> str:
    normalized = _normalize_name(value)
    if not normalized or _contains_secret_like(normalized, key_hint):
        return ""
    return _safe_text(normalized)


def _extract_capitalized_entities(text: Any) -> list[str]:
    """Extract only deterministic, lightweight capitalized-word candidates."""
    if not isinstance(text, str):
        return []
    tokens = re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", text)
    stop = {"the", "and", "for", "that", "this", "with", "from", "have"}
    seen: set[str] = set()
    entities: list[str] = []
    for token in tokens:
        if _looks_sensitive_token(token):
            continue
        normalized = token.casefold()
        if normalized in stop or normalized in seen:
            continue
        seen.add(normalized)
        entities.append(token)
    return sorted(entities, key=lambda item: (item.casefold(), item))


def _claim_items(entry: MemoryEntry) -> list[Any]:
    """Return explicit claims from metadata and structured claim values only."""
    metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
    raw_claims = metadata.get("claims", [])
    claims = _as_list(raw_claims)
    if isinstance(entry.value, dict) and "claim" in entry.value:
        claims.append(entry.value)

    deduped: list[Any] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw_claim in sorted(claims, key=_stable_sort_key):
        if not isinstance(raw_claim, dict):
            deduped.append(raw_claim)
            continue
        nested = raw_claim.get("metadata")
        nested = nested if isinstance(nested, dict) else {}
        holder = _normalize_name(raw_claim.get("holder"))
        subject = _normalize_name(raw_claim.get("subject") or raw_claim.get("entity"))
        text = _normalize_name(raw_claim.get("claim") or raw_claim.get("text"))
        provenance = _normalize_name(
            raw_claim.get("provenance_id")
            or nested.get("provenance_id")
            or raw_claim.get("source_hash")
        )
        key = (holder.casefold(), subject.casefold(), text.casefold(), provenance.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(raw_claim)
    return deduped


def _entry_status(entry: MemoryEntry, now: float) -> dict[str, Any]:
    reasons: list[str] = []
    if getattr(entry, "superseded_by", None):
        reasons.append("superseded")

    valid_at = _coerce_timestamp(getattr(entry, "valid_at", None))
    if valid_at is not None and valid_at > now:
        reasons.append("future")
    invalid_at = _coerce_timestamp(getattr(entry, "invalid_at", None))
    if invalid_at is not None and invalid_at <= now:
        reasons.append("expired")

    created_at = _coerce_timestamp(getattr(entry, "created_at", None))
    ttl = _coerce_timestamp(getattr(entry, "ttl", None))
    if ttl is not None and created_at is not None and created_at + ttl <= now:
        reasons.append("ttl_expired")

    try:
        if float(getattr(entry, "current_strength", 1.0)) < 0.1:
            reasons.append("weak")
    except (TypeError, ValueError):
        reasons.append("invalid_strength")

    return {
        "active": not reasons,
        "reasons": sorted(set(reasons)),
        "valid_at": getattr(entry, "valid_at", None),
        "invalid_at": getattr(entry, "invalid_at", None),
    }


def _claim_status(raw_claim: dict[str, Any], now: float) -> dict[str, Any]:
    nested = raw_claim.get("metadata")
    nested = nested if isinstance(nested, dict) else {}
    reasons: list[str] = []
    if not _as_bool(raw_claim.get("active"), True):
        reasons.append("inactive")
    if raw_claim.get("superseded_by") or nested.get("superseded_by"):
        reasons.append("superseded")
    if raw_claim.get("verified", raw_claim.get("is_verified", True)) is False:
        reasons.append("unverified")

    valid_at = _coerce_timestamp(raw_claim.get("valid_at", nested.get("valid_at")))
    if valid_at is not None and valid_at > now:
        reasons.append("future")
    invalid_at = _coerce_timestamp(raw_claim.get("invalid_at", nested.get("invalid_at")))
    if invalid_at is not None and invalid_at <= now:
        reasons.append("expired")

    return {
        "active": not reasons,
        "reasons": sorted(set(reasons)),
        "valid_at": raw_claim.get("valid_at", nested.get("valid_at")),
        "invalid_at": raw_claim.get("invalid_at", nested.get("invalid_at")),
    }


class _PreviewBuilder:
    def __init__(self, now: float):
        self.now = now
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
        self._node_keys: set[tuple[str, str, str]] = set()
        self._edge_keys: set[tuple[str, str, str, str]] = set()
        self._names_by_norm: dict[str, set[str]] = {}
        self.claim_count = 0
        self.active_claim_count = 0
        self.filtered_claim_count = 0
        self.memories_with_projection = 0
        self.memories_without_projection = 0
        self.filtered_memory_count = 0
        self.filtered_stale_count = 0
        self.filtered_superseded_count = 0
        self.filtered_future_count = 0
        self.secret_like_suppressed_count = 0
        self.provenance_fallback_count = 0
        self.provenance_missing_count = 0

    def suppress_secret(self, memory_key: str, field: str) -> None:
        self.secret_like_suppressed_count += 1
        self.issues.append(
            {
                "type": "secret_like_value_suppressed",
                "memory_key": memory_key,
                "field": field,
                "reason": "credential-like value was excluded from graph projection",
            }
        )

    def node(
        self,
        name: Any,
        node_type: str,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        normalized_name = _normalize_name(name)
        if not normalized_name:
            return
        normalized_key = _dedupe_key(normalized_name)
        self._names_by_norm.setdefault(normalized_key, set()).add(normalized_name)
        key = (normalized_key, node_type, source)
        if key in self._node_keys:
            return

        safe_metadata = _safe_projection_value(metadata or {})
        if not isinstance(safe_metadata, dict):
            safe_metadata = {}
        if not safe_metadata.get("provenance_id") and not safe_metadata.get("memory_key"):
            safe_metadata["provenance_id"] = REDACTED
            self.provenance_missing_count += 1

        self._node_keys.add(key)
        self.nodes.append(
            {
                "name": _safe_text(normalized_name),
                "node_type": node_type,
                "source": source,
                "metadata": safe_metadata,
            }
        )

    def edge(
        self,
        source: Any,
        target: Any,
        relation_type: str,
        source_label: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        normalized_source = _normalize_name(source)
        normalized_target = _normalize_name(target)
        if not normalized_source or not normalized_target:
            return
        key = (
            _dedupe_key(normalized_source),
            _dedupe_key(normalized_target),
            relation_type,
            source_label,
        )
        if key in self._edge_keys:
            return

        safe_metadata = _safe_projection_value(metadata or {})
        if not isinstance(safe_metadata, dict):
            safe_metadata = {}
        safe_metadata = {"source": source_label, **safe_metadata}
        if not safe_metadata.get("provenance_id") and not safe_metadata.get("memory_key"):
            safe_metadata["provenance_id"] = REDACTED
            self.provenance_missing_count += 1

        self._edge_keys.add(key)
        self.edges.append(
            {
                "source": _safe_text(normalized_source),
                "target": _safe_text(normalized_target),
                "relation_type": relation_type,
                "metadata": safe_metadata,
            }
        )

    def duplicate_alias_issues(self) -> None:
        for normalized_key in sorted(self._names_by_norm):
            names = self._names_by_norm[normalized_key]
            if len(names) <= 1:
                continue
            self.issues.append(
                {
                    "type": "possible_duplicate_entity",
                    "names": sorted(names, key=lambda item: (item.casefold(), item)),
                    "reason": "case_or_whitespace_alias_collision",
                }
            )


def _safe_memory_key(entry: MemoryEntry) -> str:
    original = _normalize_name(getattr(entry, "key", ""))
    if not original:
        return ""
    return _safe_name(original, key_hint="memory_key") or REDACTED


def _entry_projection_metadata(
    entry: MemoryEntry,
    memory_key: str,
    status: dict[str, Any],
    builder: _PreviewBuilder,
) -> dict[str, Any]:
    raw_metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
    explicit_provenance = (
        raw_metadata.get("provenance_id")
        or raw_metadata.get("source_hash")
        or raw_metadata.get("source_ref")
        or getattr(entry, "source", None)
    )
    provenance_id = _safe_name(
        raw_metadata.get("provenance_id")
        or raw_metadata.get("source_hash")
        or raw_metadata.get("source_ref")
        or getattr(entry, "key", ""),
        key_hint="provenance_id",
    )
    if not provenance_id:
        provenance_id = memory_key or REDACTED
    if not explicit_provenance:
        builder.provenance_fallback_count += 1

    return {
        "memory_key": memory_key,
        "provenance_id": provenance_id,
        "source": _safe_projection_value(getattr(entry, "source", ""), key_hint="source"),
        "source_reference": _safe_projection_value(
            raw_metadata.get("source_ref") or raw_metadata.get("source"),
            key_hint="source_reference",
        ),
        "memory_type": (
            entry.memory_type.value
            if hasattr(entry.memory_type, "value")
            else str(entry.memory_type)
        ),
        "authority": _safe_projection_value(raw_metadata.get("authority"), key_hint="authority"),
        "sensitivity": _safe_projection_value(
            raw_metadata.get("sensitivity") or raw_metadata.get("classification"),
            key_hint="sensitivity",
        ),
        "valid_at": status.get("valid_at"),
        "invalid_at": status.get("invalid_at"),
        "ttl": getattr(entry, "ttl", None),
        "conflict_id": _safe_projection_value(
            getattr(entry, "conflict_id", None), key_hint="conflict_id"
        ),
        "superseded_by": _safe_projection_value(
            getattr(entry, "superseded_by", None), key_hint="superseded_by"
        ),
        "is_verified": bool(getattr(entry, "is_verified", False)),
        "importance": getattr(entry, "importance", None),
        "active": bool(status.get("active")),
        "stale_reasons": status.get("reasons", []),
    }


def _claim_projection_metadata(
    raw_claim: dict[str, Any],
    entry: MemoryEntry,
    memory_key: str,
    entry_projection: dict[str, Any],
    claim_status: dict[str, Any],
    builder: _PreviewBuilder,
) -> tuple[dict[str, Any], str, str, str, str] | None:
    nested = raw_claim.get("metadata")
    nested = nested if isinstance(nested, dict) else {}
    holder = _safe_name(raw_claim.get("holder"), key_hint="holder")
    subject = _safe_name(
        raw_claim.get("subject") or raw_claim.get("entity"),
        key_hint="subject",
    )
    claim_text = _safe_text(raw_claim.get("claim") or raw_claim.get("text"))
    if not holder or not subject or not claim_text:
        return None

    provenance_raw = (
        raw_claim.get("provenance_id")
        or nested.get("provenance_id")
        or raw_claim.get("source_hash")
        or entry_projection.get("provenance_id")
        or memory_key
    )
    provenance_id = _safe_name(provenance_raw, key_hint="provenance_id") or memory_key or REDACTED
    if not (
        raw_claim.get("provenance_id")
        or nested.get("provenance_id")
        or raw_claim.get("source_hash")
        or entry_projection.get("provenance_id")
    ):
        builder.provenance_fallback_count += 1

    active = bool(claim_status["active"])
    claim_reasons = claim_status["reasons"]
    contradiction = raw_claim.get("contradicts")
    if contradiction is None:
        contradiction = raw_claim.get("contradiction")
    if contradiction is None:
        contradiction = raw_claim.get("conflicts_with")
    if contradiction is None:
        contradiction = nested.get("contradicts") or nested.get("conflicts_with")
    relation = "contradicts" if _as_bool(contradiction, False) else ("supports" if active else "related_to")

    claim_metadata: dict[str, Any] = {
        "memory_key": memory_key,
        "provenance_id": provenance_id,
        "claim": claim_text,
        "kind": _safe_projection_value(
            raw_claim.get("kind") or nested.get("kind") or "fact",
            key_hint="kind",
        ),
        "confidence": _safe_projection_value(
            raw_claim.get("confidence", nested.get("confidence", 0.5)),
            key_hint="confidence",
        ),
        "source_reference": _safe_projection_value(
            raw_claim.get("source_ref")
            or raw_claim.get("source")
            or nested.get("source_ref")
            or nested.get("source")
            or entry_projection.get("source_reference"),
            key_hint="source_reference",
        ),
        "authority": _safe_projection_value(
            raw_claim.get("authority") or nested.get("authority") or entry_projection.get("authority"),
            key_hint="authority",
        ),
        "sensitivity": _safe_projection_value(
            raw_claim.get("sensitivity")
            or nested.get("sensitivity")
            or entry_projection.get("sensitivity"),
            key_hint="sensitivity",
        ),
        "valid_at": claim_status["valid_at"],
        "invalid_at": claim_status["invalid_at"],
        "active": active,
        "verified": raw_claim.get("verified", raw_claim.get("is_verified", True)) is not False,
        "superseded_by": _safe_projection_value(
            raw_claim.get("superseded_by") or nested.get("superseded_by"),
            key_hint="superseded_by",
        ),
        "contradicts": _safe_projection_value(contradiction, key_hint="contradicts"),
        "conflict_id": _safe_projection_value(
            raw_claim.get("conflict_id") or nested.get("conflict_id"),
            key_hint="conflict_id",
        ),
        "stale_reasons": claim_reasons,
    }
    return claim_metadata, holder, subject, provenance_id, relation


def _issue_sort_key(issue: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(issue.get("type", "")),
        str(issue.get("memory_key", "")),
        str(issue.get("claim_index", "")),
        _stable_sort_key(issue),
    )


def _build_checks(builder: _PreviewBuilder) -> dict[str, Any]:
    duplicate_count = sum(
        1 for issue in builder.issues if issue.get("type") == "possible_duplicate_entity"
    )
    stale_issue_count = sum(
        1
        for issue in builder.issues
        if issue.get("type")
        in {
            "stale_memory",
            "superseded_memory",
            "future_memory",
            "expired_claim",
            "inactive_claim",
            "superseded_claim",
            "future_claim",
            "unverified_claim",
        }
    )
    return {
        "duplicate": {
            "status": "attention" if duplicate_count else "pass",
            "issue_count": duplicate_count,
        },
        "stale": {
            "status": "attention" if stale_issue_count else "pass",
            "issue_count": stale_issue_count,
            "filtered_memory_count": builder.filtered_memory_count,
            "filtered_claim_count": builder.filtered_claim_count,
        },
        "secret_like": {
            "status": "pass",
            "suppressed_count": builder.secret_like_suppressed_count,
        },
        "provenance": {
            "status": "pass" if builder.provenance_missing_count == 0 else "attention",
            "missing_count": builder.provenance_missing_count,
            "fallback_count": builder.provenance_fallback_count,
        },
        "determinism": {
            "status": "pass",
            "read_only": True,
            "idempotent": True,
            "repeatable": True,
        },
    }


def preview_projection(
    entries: Iterable[MemoryEntry],
    now: float | None = None,
    *,
    include_stale: bool = False,
) -> dict[str, Any]:
    """Return a read-only, deterministic graph projection doctor report.

    ``include_stale`` is an audit-only escape hatch. The default preview
    excludes stale, future, superseded, weak, inactive, and unverified
    structured claims from candidate nodes/edges. No option in this function
    applies or persists a projection.
    """
    timestamp = time.time() if now is None else float(now)
    builder = _PreviewBuilder(now=timestamp)
    materialized = sorted(
        list(entries or []),
        key=lambda entry: (
            _dedupe_key(getattr(entry, "key", "")),
            str(getattr(getattr(entry, "memory_type", ""), "value", getattr(entry, "memory_type", ""))),
            _stable_sort_key(getattr(entry, "id", "")),
            _stable_sort_key(getattr(entry, "value", "")),
        ),
    )

    for entry in materialized:
        before_nodes = len(builder.nodes)
        before_edges = len(builder.edges)
        raw_metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
        memory_key = _safe_memory_key(entry)
        status = _entry_status(entry, timestamp)

        if not status["active"]:
            builder.filtered_memory_count += 1
            if "superseded" in status["reasons"]:
                builder.filtered_superseded_count += 1
                builder.issues.append(
                    {
                        "type": "superseded_memory",
                        "memory_key": memory_key,
                        "superseded_by": _safe_projection_value(
                            getattr(entry, "superseded_by", None),
                            key_hint="superseded_by",
                        ),
                        "reason": "memory entry is superseded",
                    }
                )
            if "future" in status["reasons"]:
                builder.filtered_future_count += 1
                builder.issues.append(
                    {
                        "type": "future_memory",
                        "memory_key": memory_key,
                        "valid_at": status.get("valid_at"),
                        "reason": "memory entry is not valid at evaluation time",
                    }
                )
            stale_reasons = [
                reason
                for reason in status["reasons"]
                if reason in {"expired", "ttl_expired", "weak", "invalid_strength"}
            ]
            if stale_reasons:
                builder.filtered_stale_count += 1
                builder.issues.append(
                    {
                        "type": "stale_memory",
                        "memory_key": memory_key,
                        "invalid_at": status.get("invalid_at"),
                        "reasons": stale_reasons,
                        "reason": "stale memory entry excluded from default projection",
                    }
                )
            if not include_stale:
                continue

        entry_projection = _entry_projection_metadata(entry, memory_key, status, builder)
        claim_items = _claim_items(entry)
        has_metadata_projection = any(
            raw_metadata.get(field)
            for field in ("product", "concerns", "entities", "claims", "provenance_id", "source_ref")
        )
        should_add_memory_node = (
            entry.memory_type == MemoryType.SEMANTIC or has_metadata_projection or bool(claim_items)
        )
        if should_add_memory_node and memory_key:
            builder.node(memory_key, "fact", "memory_key", entry_projection)

        def project_named_value(raw_value: Any, field: str) -> None:
            value = raw_value
            if isinstance(raw_value, dict):
                value = (
                    raw_value.get("canonical_name")
                    or raw_value.get("name")
                    or raw_value.get("entity")
                    or raw_value.get("value")
                )
            name = _safe_name(value, key_hint=field)
            if not name:
                if value not in (None, ""):
                    builder.suppress_secret(memory_key, field)
                return
            metadata = dict(entry_projection)
            if isinstance(raw_value, dict):
                metadata.update(
                    {
                        key: _safe_projection_value(raw_value.get(key), key_hint=key)
                        for key in ("authority", "sensitivity", "source_ref", "provenance_id")
                        if raw_value.get(key) is not None
                    }
                )
            builder.node(name, "entity", field, metadata)
            builder.edge(memory_key, name, "related_to", field, metadata)

        for product in _as_list(raw_metadata.get("product")):
            if memory_key:
                project_named_value(product, "metadata.product")
        for concern in _as_list(raw_metadata.get("concerns")):
            if memory_key:
                project_named_value(concern, "metadata.concerns")
        for raw_entity in _as_list(raw_metadata.get("entities")):
            if memory_key:
                project_named_value(raw_entity, "metadata.entities")

        if entry.memory_type == MemoryType.SEMANTIC and memory_key:
            if isinstance(entry.value, str):
                for entity_name in _extract_capitalized_entities(entry.value):
                    builder.node(entity_name, "entity", "value.capitalized", entry_projection)
                    builder.edge(
                        memory_key,
                        entity_name,
                        "related_to",
                        "value.capitalized",
                        entry_projection,
                    )
                for token in re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", entry.value):
                    if _looks_sensitive_token(token):
                        builder.suppress_secret(memory_key, "value.capitalized")

        for index, raw_claim in enumerate(claim_items):
            if not isinstance(raw_claim, dict):
                builder.issues.append(
                    {
                        "type": "malformed_claim",
                        "memory_key": memory_key,
                        "claim_index": index,
                        "reason": "claim is not an object",
                    }
                )
                continue

            holder = _normalize_name(raw_claim.get("holder"))
            subject = _normalize_name(raw_claim.get("subject") or raw_claim.get("entity"))
            claim_text_raw = _normalize_name(raw_claim.get("claim") or raw_claim.get("text"))
            if not holder or not subject or not claim_text_raw:
                builder.issues.append(
                    {
                        "type": "malformed_claim",
                        "memory_key": memory_key,
                        "claim_index": index,
                        "reason": "missing holder/subject/claim",
                    }
                )
                continue

            builder.claim_count += 1
            claim_status = _claim_status(raw_claim, timestamp)
            if not claim_status["active"]:
                builder.filtered_claim_count += 1
                for reason in claim_status["reasons"]:
                    issue_type = {
                        "expired": "expired_claim",
                        "inactive": "inactive_claim",
                        "superseded": "superseded_claim",
                        "future": "future_claim",
                        "unverified": "unverified_claim",
                    }.get(reason, "stale_claim")
                    builder.issues.append(
                        {
                            "type": issue_type,
                            "memory_key": memory_key,
                            "claim_index": index,
                            "invalid_at": _safe_projection_value(
                                claim_status.get("invalid_at"), key_hint="invalid_at"
                            ),
                            "superseded_by": _safe_projection_value(
                                raw_claim.get("superseded_by"), key_hint="superseded_by"
                            ),
                            "reason": f"claim excluded: {reason}",
                        }
                    )
                if not include_stale:
                    continue

            claim_projection = _claim_projection_metadata(
                raw_claim,
                entry,
                memory_key,
                entry_projection,
                claim_status,
                builder,
            )
            if claim_projection is None:
                builder.issues.append(
                    {
                        "type": "malformed_claim",
                        "memory_key": memory_key,
                        "claim_index": index,
                        "reason": "secret-like or empty holder/subject/claim",
                    }
                )
                continue
            claim_metadata, holder_name, subject_name, provenance_id, relation = claim_projection
            if claim_status["active"]:
                builder.active_claim_count += 1
            builder.node(holder_name, "entity", "claim.holder", claim_metadata)
            builder.node(subject_name, "entity", "claim.subject", claim_metadata)
            builder.edge(
                holder_name,
                subject_name,
                relation,
                "metadata.claims",
                claim_metadata,
            )
            if provenance_id:
                builder.node(provenance_id, "fact", "claim.provenance_id", claim_metadata)
                builder.edge(
                    provenance_id,
                    subject_name,
                    relation,
                    "claim.provenance_id",
                    claim_metadata,
                )

        if len(builder.nodes) == before_nodes and len(builder.edges) == before_edges:
            builder.memories_without_projection += 1
            builder.issues.append(
                {
                    "type": "no_projection_candidates",
                    "memory_key": memory_key,
                    "reason": "no deterministic metadata, claim, entity, or semantic projection candidates",
                }
            )
        else:
            builder.memories_with_projection += 1

    builder.duplicate_alias_issues()
    builder.nodes.sort(
        key=lambda node: (
            str(node.get("node_type", "")),
            _dedupe_key(node.get("name", "")),
            str(node.get("name", "")),
            str(node.get("source", "")),
        )
    )
    builder.edges.sort(
        key=lambda edge: (
            _dedupe_key(edge.get("source", "")),
            _dedupe_key(edge.get("target", "")),
            str(edge.get("relation_type", "")),
            _stable_sort_key(edge.get("metadata", {})),
        )
    )
    builder.issues.sort(key=_issue_sort_key)

    stats = {
        "input_memory_count": len(materialized),
        "projected_memory_count": builder.memories_with_projection,
        "filtered_memory_count": builder.filtered_memory_count,
        "filtered_stale_count": builder.filtered_stale_count,
        "filtered_superseded_count": builder.filtered_superseded_count,
        "filtered_future_count": builder.filtered_future_count,
        "candidate_node_count": len(builder.nodes),
        "candidate_edge_count": len(builder.edges),
        "claim_count": builder.claim_count,
        "active_claim_count": builder.active_claim_count,
        "filtered_claim_count": builder.filtered_claim_count,
        "memories_with_projection": builder.memories_with_projection,
        "memories_without_projection": builder.memories_without_projection,
        "secret_like_suppressed_count": builder.secret_like_suppressed_count,
        "provenance_fallback_count": builder.provenance_fallback_count,
        "provenance_missing_count": builder.provenance_missing_count,
    }
    return {
        "schema_version": PREVIEW_SCHEMA_VERSION,
        "read_only": True,
        "apply_allowed": False,
        "backfill_allowed": False,
        "include_stale": bool(include_stale),
        "memory_count": len(materialized),
        "candidate_nodes": builder.nodes,
        "candidate_edges": builder.edges,
        "issues": builder.issues,
        "checks": _build_checks(builder),
        "stats": stats,
    }
