"""Deterministic salience and writeback policy for Bilinc cognitive runtime.

The salience engine is intentionally rule-based and side-effect free. It decides
whether a normal agent turn deserves persistence and emits write proposals that a
future workspace/runtime layer may review and apply.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from bilinc.core.models import MemoryType

WriteAction = Literal["commit", "revise", "ignore"]

SENSITIVE_PATTERNS = [
    re.compile(r"\bpassword\s*(?:is|=|:)\s*\S+", re.IGNORECASE),
    re.compile(r"\bbearer\s+[A-Za-z0-9._\-]{12,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b", re.IGNORECASE),
    re.compile(r"\bpypi-[A-Za-z0-9_\-]{20,}\b", re.IGNORECASE),
    re.compile(r"\bapi[_-]?key\s*(?:is|=|:)\s*\S+", re.IGNORECASE),
]
SENSITIVE_KEY_PATTERN = re.compile(r"(password|token|secret|api[_-]?key|bearer)", re.IGNORECASE)

CASUAL_PATTERNS = [
    re.compile(r"^\s*(thanks?|thank you|ok|okay|haha|lol|nice|cool|great|tamam|eyvallah)(?:[.!\s]+(?:thanks?|thank you|ok|okay|haha|lol|nice|cool|great|tamam|eyvallah))*[.!\s]*$", re.IGNORECASE),
]

PREFERENCE_PATTERNS = [
    re.compile(r"\b(?:remember that\s+)?(?:i|we)\s+prefer\b", re.IGNORECASE),
    re.compile(r"\b(?:ben|biz)\s+.*\btercih\s+ed", re.IGNORECASE),
]

WORKFLOW_PATTERNS = [
    re.compile(r"\bwhen\b.*\b(always|first|then|must|should)\b", re.IGNORECASE),
    re.compile(r"\balways\b.*\b(then|after|before|run|verify|check)\b", re.IGNORECASE),
    re.compile(r"\bworkflow\b|\bprocedure\b|\bplaybook\b", re.IGNORECASE),
]

DECISION_PATTERNS = [
    re.compile(r"^\s*(decision|karar)\s*:", re.IGNORECASE),
    re.compile(r"\bwe decided\b|\bdecided that\b|\bkarar verdik\b", re.IGNORECASE),
]

TEMPORARY_PATTERNS = [
    re.compile(r"\b(for now|temporary|temporarily|during this session|this debugging session only)\b", re.IGNORECASE),
    re.compile(r"\b(şimdilik|geçici|bu oturumda)\b", re.IGNORECASE),
]


@dataclass
class MemoryWriteProposal:
    """A side-effect-free proposal for a later writeback step."""

    key: str
    value: str
    memory_type: MemoryType
    importance: float
    confidence: float
    action: WriteAction = "commit"
    ttl: Optional[int] = None
    revision_strategy: str = "recency"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.importance = _clamp01(self.importance)
        self.confidence = _clamp01(self.confidence)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "memory_type": self.memory_type.value,
            "importance": self.importance,
            "confidence": self.confidence,
            "action": self.action,
            "ttl": self.ttl,
            "revision_strategy": self.revision_strategy,
            "metadata": self.metadata,
        }


@dataclass
class SalienceDecision:
    """Deterministic persistence decision for one conversation turn."""

    should_store: bool
    proposals: List[MemoryWriteProposal]
    reason: str
    importance: float
    confidence: float
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    prompt_safe_summary: str = ""

    def __post_init__(self) -> None:
        self.importance = _clamp01(self.importance)
        self.confidence = _clamp01(self.confidence)

    @property
    def primary_proposal(self) -> Optional[MemoryWriteProposal]:
        return self.proposals[0] if self.proposals else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_store": self.should_store,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "reason": self.reason,
            "importance": self.importance,
            "confidence": self.confidence,
            "warnings": self.warnings,
            "prompt_safe_summary": self.prompt_safe_summary,
        }


class SalienceEngine:
    """Rule-based salience engine for automatic agent memory writeback planning."""

    def __init__(self, *, agent_id: str = "agent", default_working_ttl: int = 6 * 60 * 60):
        self.agent_id = _slug(agent_id, lower=False) or "agent"
        self.default_working_ttl = max(60, int(default_working_ttl))

    def evaluate_turn(
        self,
        *,
        user_input: str,
        assistant_output: str = "",
        tool_events: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SalienceDecision:
        text = _normalize_space(user_input)
        assistant = _normalize_space(assistant_output)
        session = _slug(session_id or "session") or "session"
        metadata = metadata or {}
        tool_events = tool_events or []
        combined = " ".join(part for part in [text, assistant] if part)
        safe_summary = _redact_sensitive(combined[:500])

        sensitive_hits = _sensitive_hits(combined)
        if sensitive_hits:
            return SalienceDecision(
                should_store=False,
                proposals=[],
                reason="sensitive_value",
                importance=0.0,
                confidence=0.95,
                warnings=[{"type": "sensitive_value", "count": len(sensitive_hits), "action": "not_persisted"}],
                prompt_safe_summary=safe_summary,
            )

        if not text or _matches_any(text, CASUAL_PATTERNS):
            return SalienceDecision(False, [], "casual_chatter", 0.05, 0.9, prompt_safe_summary=safe_summary)

        if _matches_any(text, TEMPORARY_PATTERNS):
            proposal = MemoryWriteProposal(
                key=f"{session}:working:{_stable_hash(text)}",
                value=text,
                memory_type=MemoryType.WORKING,
                importance=0.45,
                confidence=0.78,
                ttl=self.default_working_ttl,
                revision_strategy="recency",
                metadata={"salience_reason": "temporary_state", **_base_metadata(metadata, tool_events)},
            )
            return SalienceDecision(True, [proposal], "temporary_state", proposal.importance, proposal.confidence, prompt_safe_summary=safe_summary)

        if _matches_any(text, DECISION_PATTERNS):
            decision_text = _strip_leading_label(text)
            episodic = MemoryWriteProposal(
                key=f"{session}:decision:{_stable_hash(decision_text)}",
                value=decision_text,
                memory_type=MemoryType.EPISODIC,
                importance=0.72,
                confidence=0.84,
                revision_strategy="recency",
                metadata={"salience_reason": "task_decision", **_base_metadata(metadata, tool_events)},
            )
            semantic = MemoryWriteProposal(
                key=f"decision:{_stable_hash(decision_text)}",
                value=decision_text,
                memory_type=MemoryType.SEMANTIC,
                importance=0.76,
                confidence=0.8,
                revision_strategy="verification",
                metadata={"salience_reason": "task_decision_summary", "source_session": session, **_base_metadata(metadata, tool_events)},
            )
            return SalienceDecision(True, [episodic, semantic], "task_decision", 0.76, 0.84, prompt_safe_summary=safe_summary)

        if _matches_any(text, WORKFLOW_PATTERNS):
            proposal = MemoryWriteProposal(
                key=f"procedure:{_stable_hash(text)}",
                value=text,
                memory_type=MemoryType.PROCEDURAL,
                importance=0.78,
                confidence=0.82,
                revision_strategy="verification",
                metadata={"salience_reason": "workflow", **_base_metadata(metadata, tool_events)},
            )
            return SalienceDecision(True, [proposal], "workflow", proposal.importance, proposal.confidence, prompt_safe_summary=safe_summary)

        if _matches_any(text, PREFERENCE_PATTERNS):
            proposal = MemoryWriteProposal(
                key=f"{self.agent_id}:preference:{_stable_hash(text)}",
                value=text,
                memory_type=MemoryType.SEMANTIC,
                importance=0.74,
                confidence=0.84,
                revision_strategy="verification",
                metadata={"salience_reason": "explicit_preference", **_base_metadata(metadata, tool_events)},
            )
            return SalienceDecision(True, [proposal], "explicit_preference", proposal.importance, proposal.confidence, prompt_safe_summary=safe_summary)

        if len(text.split()) >= 18:
            proposal = MemoryWriteProposal(
                key=f"{session}:episode:{_stable_hash(text)}",
                value=text,
                memory_type=MemoryType.EPISODIC,
                importance=0.35,
                confidence=0.55,
                revision_strategy="recency",
                metadata={"salience_reason": "nontrivial_turn", **_base_metadata(metadata, tool_events)},
            )
            return SalienceDecision(True, [proposal], "nontrivial_turn", proposal.importance, proposal.confidence, prompt_safe_summary=safe_summary)

        return SalienceDecision(False, [], "low_salience", 0.15, 0.75, prompt_safe_summary=safe_summary)


class WritebackRouter:
    """Small wrapper that keeps future writeback routing separate from scoring."""

    def __init__(self, salience_engine: Optional[SalienceEngine] = None):
        self.salience_engine = salience_engine or SalienceEngine()

    def route_turn(self, **kwargs: Any) -> SalienceDecision:
        return self.salience_engine.evaluate_turn(**kwargs)


def _base_metadata(metadata: Dict[str, Any], tool_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    base = {"created_by": "bilinc.salience", "side_effect_free": True}
    if metadata:
        base["input_metadata"] = _redact_obj(metadata)
    if tool_events:
        base["tool_event_count"] = len(tool_events)
    return base


def _matches_any(text: str, patterns: List[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _sensitive_hits(text: str) -> List[str]:
    return [match.group(0) for pattern in SENSITIVE_PATTERNS for match in pattern.finditer(text or "")]


def _redact_sensitive(text: str) -> str:
    redacted = text or ""
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _redact_obj(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_sensitive(value)
    if isinstance(value, dict):
        redacted = {}
        for key, val in value.items():
            if SENSITIVE_KEY_PATTERN.search(str(key)):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_obj(val)
        return redacted
    if isinstance(value, list):
        return [_redact_obj(item) for item in value]
    return value


def _stable_hash(text: str) -> str:
    return hashlib.sha256(_normalize_space(text).lower().encode("utf-8")).hexdigest()[:16]


def _normalize_space(text: str) -> str:
    return " ".join((text or "").split())


def _slug(text: str, *, lower: bool = True) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text or "").strip("-")
    if lower:
        slug = slug.lower()
    return slug[:64]


def _strip_leading_label(text: str) -> str:
    return re.sub(r"^\s*(decision|karar)\s*:\s*", "", text, flags=re.IGNORECASE).strip()


def _clamp01(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))
