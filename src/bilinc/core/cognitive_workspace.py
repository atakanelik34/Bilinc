"""Cognitive workspace lifecycle for Bilinc agent turns.

This module wires the read-only context assembler and deterministic salience engine
into an SDK-level turn lifecycle. It intentionally avoids MCP/server coupling and
never chooses a storage path; callers provide the StatePlane/backend.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from bilinc.core.context_assembler import ContextAssembler, ContextBundle
from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.salience import MemoryWriteProposal, SalienceDecision, SalienceEngine


@dataclass
class TurnFrame:
    """A compact lifecycle receipt for one agent turn."""

    session_id: str
    user_input: str = ""
    assistant_output: str = ""
    context: Optional[ContextBundle] = None
    salience: Optional[SalienceDecision] = None
    retrieved_keys: List[str] = field(default_factory=list)
    observed_user_key: Optional[str] = None
    written_keys: List[str] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_input": self.user_input,
            "assistant_output": self.assistant_output,
            "context": self.context.to_dict() if self.context else None,
            "salience": self.salience.to_dict() if self.salience else None,
            "retrieved_keys": list(self.retrieved_keys),
            "observed_user_key": self.observed_user_key,
            "written_keys": list(self.written_keys),
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }


class CognitiveWorkspace:
    """Framework-agnostic cognitive runtime workspace for one agent."""

    def __init__(
        self,
        *,
        state_plane: Any,
        agent_id: str = "agent",
        default_profile: str = "balanced",
        context_assembler: Optional[ContextAssembler] = None,
        salience_engine: Optional[SalienceEngine] = None,
    ) -> None:
        self.state_plane = state_plane
        self.agent_id = agent_id or "agent"
        self.default_profile = (default_profile or "balanced").strip().lower()
        self.context_assembler = context_assembler or ContextAssembler(state_plane)
        self.salience_engine = salience_engine or SalienceEngine(agent_id=self.agent_id)
        self._frames: Dict[str, TurnFrame] = {}

    def current_frame(self, session_id: str) -> TurnFrame:
        return self._frame(session_id)

    async def prepare_context(
        self,
        session_id: str,
        user_input: str,
        *,
        budget_tokens: int = 4096,
        profile: Optional[str] = None,
        limit: int = 10,
        metadata: Optional[Dict[str, Any]] = None,
        memory_types: Optional[List[Any]] = None,
    ) -> ContextBundle:
        """Recall and assemble a prompt block for a model call."""

        frame = self._frame(session_id)
        frame.user_input = user_input or frame.user_input
        frame.metadata.update(_redact_runtime_metadata(metadata or {}))
        bundle = await self.context_assembler.assemble(
            user_input,
            profile=profile or self.default_profile,
            limit=limit,
            budget_tokens=budget_tokens,
            memory_types=memory_types,
        )
        frame.context = bundle
        frame.retrieved_keys = list(bundle.selected_memory_keys)
        frame.warnings = _dedupe_warnings(frame.warnings + bundle.warnings)
        return bundle

    async def observe_user_turn(
        self,
        session_id: str,
        user_input: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryEntry:
        """Capture the current user turn as working memory for this session."""

        frame = self._frame(session_id)
        frame.user_input = user_input or frame.user_input
        frame.metadata.update(_redact_runtime_metadata(metadata or {}))
        key = f"{_slug(session_id)}:turn:{_stable_hash(user_input)}:user"
        if frame.observed_user_key == key:
            recalled = await self.state_plane.recall(key)
            if recalled:
                return recalled[0]
        value = {
            "session_id": session_id,
            "agent_id": self.agent_id,
            "role": "user",
            "user_input": user_input,
            "observed_at": time.time(),
        }
        entry = await self.state_plane.commit(
            key,
            value,
            memory_type=MemoryType.WORKING,
            importance=0.35,
            metadata={
                "created_by": "bilinc.cognitive_workspace",
                "workspace_event": "observe_user_turn",
                **frame.metadata,
            },
        )
        frame.observed_user_key = entry.key
        return entry

    async def assimilate_response(
        self,
        session_id: str,
        user_input: str,
        assistant_output: str,
        *,
        tool_events: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SalienceDecision:
        """Evaluate salience and commit only approved memory proposals."""

        frame = self._frame(session_id)
        frame.user_input = user_input or frame.user_input
        frame.assistant_output = assistant_output or frame.assistant_output
        frame.metadata.update(_redact_runtime_metadata(metadata or {}))
        safe_tool_events = [_redact_runtime_metadata(event) for event in (tool_events or [])]
        decision = self.salience_engine.evaluate_turn(
            user_input=user_input,
            assistant_output=assistant_output,
            tool_events=safe_tool_events,
            session_id=session_id,
            metadata={"agent_id": self.agent_id, **frame.metadata},
        )
        frame.salience = decision
        frame.warnings = _dedupe_warnings(frame.warnings + decision.warnings)
        if not decision.should_store:
            return decision

        for proposal in decision.proposals:
            if proposal.key in frame.written_keys:
                continue
            written = await self._apply_write_proposal(proposal, session_id=session_id)
            if written:
                frame.written_keys.append(written.key)
        return decision

    async def finalize_turn(
        self,
        session_id: str,
        *,
        user_input: Optional[str] = None,
        assistant_output: Optional[str] = None,
        tool_events: Optional[List[Dict[str, Any]]] = None,
        budget_tokens: int = 4096,
        profile: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TurnFrame:
        """Return a deterministic receipt for the turn, running missing lifecycle steps."""

        frame = self._frame(session_id)
        if metadata:
            frame.metadata.update(_redact_runtime_metadata(metadata))
        if user_input is not None:
            frame.user_input = user_input
        if assistant_output is not None:
            frame.assistant_output = assistant_output
        if frame.user_input and frame.context is None:
            await self.prepare_context(
                session_id,
                frame.user_input,
                budget_tokens=budget_tokens,
                profile=profile,
                metadata=metadata,
            )
        if frame.user_input and frame.observed_user_key is None:
            await self.observe_user_turn(session_id, frame.user_input, metadata=metadata)
        if frame.user_input and frame.assistant_output and frame.salience is None:
            await self.assimilate_response(
                session_id,
                frame.user_input,
                frame.assistant_output,
                tool_events=tool_events,
                metadata=metadata,
            )
        return frame

    async def end_session(self, session_id: str) -> Dict[str, Any]:
        """Best-effort session closeout. Consolidates working memory when available."""

        consolidated = 0
        warnings: List[Dict[str, Any]] = []
        if hasattr(self.state_plane, "consolidate"):
            try:
                maybe_count = await self.state_plane.consolidate()
                consolidated = int(maybe_count or 0)
            except Exception as exc:  # pragma: no cover - defensive runtime boundary
                warnings.append({"type": "consolidation_failed", "message": type(exc).__name__})
        frame = self._frame(session_id)
        frame.warnings = _dedupe_warnings(frame.warnings + warnings)
        return {
            "session_id": session_id,
            "consolidated_count": consolidated,
            "retrieved_keys": list(frame.retrieved_keys),
            "written_keys": list(frame.written_keys),
            "warnings": list(frame.warnings),
        }

    async def _apply_write_proposal(self, proposal: MemoryWriteProposal, *, session_id: str) -> Optional[MemoryEntry]:
        if proposal.action == "ignore":
            return None
        if proposal.action != "commit":
            self._frame(session_id).warnings.append({
                "type": "unsupported_write_action",
                "message": f"Skipped unsupported action: {proposal.action}",
                "key": proposal.key,
            })
            return None
        metadata = {
            **proposal.metadata,
            "created_by": "bilinc.cognitive_workspace",
            "workspace_event": "assimilate_response",
            "proposal_confidence": proposal.confidence,
        }
        if proposal.ttl is not None:
            metadata["ttl"] = proposal.ttl
        return await self.state_plane.commit(
            proposal.key,
            proposal.value,
            memory_type=proposal.memory_type,
            importance=proposal.importance,
            metadata=metadata,
        )

    def _frame(self, session_id: str) -> TurnFrame:
        key = session_id or "session"
        if key not in self._frames:
            self._frames[key] = TurnFrame(session_id=key, metadata={"agent_id": self.agent_id})
        return self._frames[key]


def _stable_hash(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:12]


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in (value or "session")).strip("-")
    return slug or "session"


def _dedupe_warnings(warnings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for warning in warnings:
        marker = tuple(sorted((str(k), str(v)) for k, v in warning.items()))
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(warning)
    return deduped


def _redact_runtime_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    redacted: Dict[str, Any] = {}
    for key, value in metadata.items():
        if any(marker in str(key).lower() for marker in ("password", "token", "secret", "api_key", "api-key")):
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = _redact_runtime_metadata(value)
        elif isinstance(value, list):
            redacted[key] = [
                _redact_runtime_metadata(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            redacted[key] = value
    return redacted
