"""Framework-agnostic Bilinc agent runtime adapter.

This module makes the cognitive workspace usable from ordinary agent lifecycles:
prepare context before a model call, observe tool events, then assimilate the
assistant output after the model call. It is intentionally SDK/local-only: no
MCP, Cloud, or HTTP coupling.
"""

from __future__ import annotations

import hashlib
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Sequence

from bilinc.core.cognitive_workspace import CognitiveWorkspace, TurnFrame
from bilinc.core.context_assembler import ContextBundle
from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.salience import SalienceDecision


Message = Dict[str, Any]
AgentCallable = Callable[..., Any]


class RuntimeAdapterProtocol(Protocol):
    """Protocol for framework adapters that expose a callable model/agent step."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        ...


@dataclass
class ToolEvent:
    """A redacted tool-call event captured during an agent turn."""

    name: str
    input: Any = None
    output: Any = None
    status: str = "success"
    metadata: Dict[str, Any] = field(default_factory=dict)
    observed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "input": _redact_obj(self.input),
            "output": _redact_obj(self.output),
            "status": self.status,
            "metadata": _redact_obj(self.metadata),
            "observed_at": self.observed_at,
        }


@dataclass
class RuntimeModelInput:
    """Prepared model input after Bilinc context injection."""

    session_id: str
    messages: List[Message]
    context: ContextBundle
    frame: TurnFrame
    original_messages: List[Message] = field(default_factory=list)
    state: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeTurnResult:
    """Receipt returned after an agent/model response is assimilated."""

    session_id: str
    salience: SalienceDecision
    frame: TurnFrame
    tool_events: List[ToolEvent] = field(default_factory=list)
    tool_evidence_keys: List[str] = field(default_factory=list)


class BilincAgentRuntime:
    """Generic before/after hook layer around a CognitiveWorkspace."""

    def __init__(
        self,
        *,
        workspace: CognitiveWorkspace,
        context_role: str = "system",
        context_header: str = "Bilinc memory context for this turn:",
    ) -> None:
        self.workspace = workspace
        self.context_role = context_role
        self.context_header = context_header
        self._pending_tool_events: Dict[str, List[ToolEvent]] = {}

    @classmethod
    def from_state_plane(
        cls,
        state_plane: Any,
        *,
        agent_id: str = "agent",
        default_profile: str = "balanced",
        **kwargs: Any,
    ) -> "BilincAgentRuntime":
        workspace = CognitiveWorkspace(
            state_plane=state_plane,
            agent_id=agent_id,
            default_profile=default_profile,
        )
        return cls(workspace=workspace, **kwargs)

    @classmethod
    def from_workspace(cls, workspace: CognitiveWorkspace, **kwargs: Any) -> "BilincAgentRuntime":
        return cls(workspace=workspace, **kwargs)

    @classmethod
    async def local(
        cls,
        db_path: str,
        *,
        agent_id: str = "agent",
        default_profile: str = "balanced",
        **kwargs: Any,
    ) -> "BilincAgentRuntime":
        """Create a local SQLite-backed runtime from a caller-provided DB path."""

        from bilinc.core.stateplane import StatePlane
        from bilinc.storage.sqlite import SQLiteBackend

        backend = SQLiteBackend(db_path)
        await backend.init()
        state_plane = StatePlane(backend=backend)
        await state_plane.init()
        return cls.from_state_plane(
            state_plane,
            agent_id=agent_id,
            default_profile=default_profile,
            **kwargs,
        )

    async def before_model_call(
        self,
        *,
        session_id: str,
        messages: Optional[Sequence[Message]] = None,
        state: Optional[Dict[str, Any]] = None,
        user_input: Optional[str] = None,
        budget_tokens: int = 4096,
        profile: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RuntimeModelInput:
        """Prepare context and inject it into messages or a framework state dict."""

        original_messages = _copy_messages(messages if messages is not None else (state or {}).get("messages", []))
        resolved_user_input = user_input or _last_user_content(original_messages)
        context = await self.workspace.prepare_context(
            session_id,
            resolved_user_input,
            budget_tokens=budget_tokens,
            profile=profile,
            metadata={"runtime_event": "before_model_call", **(metadata or {})},
        )
        if resolved_user_input:
            await self.workspace.observe_user_turn(
                session_id,
                resolved_user_input,
                metadata={"runtime_event": "before_model_call", **(metadata or {})},
            )
        context_message = {
            "role": self.context_role,
            "content": f"{self.context_header}\n\n{context.prompt_block}",
        }
        prepared_messages = [context_message] + _copy_messages(original_messages)
        prepared_state = None
        if state is not None:
            prepared_state = dict(state)
            prepared_state["messages"] = prepared_messages
            prepared_state["bilinc_context"] = context.to_dict()
        return RuntimeModelInput(
            session_id=session_id,
            messages=prepared_messages,
            context=context,
            frame=self.workspace.current_frame(session_id),
            original_messages=original_messages,
            state=prepared_state,
            metadata=_redact_obj(metadata or {}),
        )

    async def observe_tool_event(
        self,
        *,
        session_id: str,
        name: str,
        input: Any = None,
        output: Any = None,
        status: str = "success",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ToolEvent:
        """Buffer a redacted tool event for the current turn."""

        event = ToolEvent(
            name=name,
            input=_redact_obj(input),
            output=_redact_obj(output),
            status=status,
            metadata=_redact_obj(metadata or {}),
        )
        self._pending_tool_events.setdefault(session_id, []).append(event)
        return event

    async def after_model_call(
        self,
        *,
        session_id: str,
        user_input: str,
        assistant_output: Any,
        tool_events: Optional[List[ToolEvent | Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RuntimeTurnResult:
        """Assimilate an assistant response and commit salience-approved writes."""

        events = self._drain_tool_events(session_id)
        events.extend(_coerce_tool_event(event) for event in (tool_events or []))
        evidence_keys = []
        for event in events:
            entry = await self._commit_tool_evidence(session_id, event)
            evidence_keys.append(entry.key)

        assistant_text = _assistant_text(assistant_output)
        decision = await self.workspace.assimilate_response(
            session_id,
            user_input,
            assistant_text,
            tool_events=[event.to_dict() for event in events],
            metadata={"runtime_event": "after_model_call", **(metadata or {})},
        )
        return RuntimeTurnResult(
            session_id=session_id,
            salience=decision,
            frame=self.workspace.current_frame(session_id),
            tool_events=events,
            tool_evidence_keys=evidence_keys,
        )

    def wrap_agent(self, agent: RuntimeAdapterProtocol) -> Callable[..., Awaitable[Any]]:
        """Wrap a callable with Bilinc before/after hooks.

        The wrapper stays framework-agnostic: if a state dict is provided, the
        agent receives the prepared state; otherwise it receives prepared messages.
        The original agent return value is preserved.
        """

        async def wrapped(*, session_id: str, user_input: str, messages: Optional[Sequence[Message]] = None, state: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Any:
            prepared = await self.before_model_call(
                session_id=session_id,
                messages=messages,
                state=state,
                user_input=user_input,
                budget_tokens=kwargs.pop("budget_tokens", 4096),
                profile=kwargs.pop("profile", None),
                metadata=kwargs.pop("metadata", None),
            )
            if prepared.state is not None:
                output = agent(prepared.state, **kwargs)
            else:
                output = agent(prepared.messages, **kwargs)
            if inspect.isawaitable(output):
                output = await output
            await self.after_model_call(
                session_id=session_id,
                user_input=user_input,
                assistant_output=output,
            )
            return output

        return wrapped

    def _drain_tool_events(self, session_id: str) -> List[ToolEvent]:
        return self._pending_tool_events.pop(session_id, [])

    async def _commit_tool_evidence(self, session_id: str, event: ToolEvent) -> MemoryEntry:
        payload = event.to_dict()
        key = f"{_slug(session_id)}:tool:{_stable_hash(payload)}"
        return await self.workspace.state_plane.commit(
            key,
            {"session_id": session_id, "agent_id": self.workspace.agent_id, "tool_event": payload},
            memory_type=MemoryType.EPISODIC,
            importance=0.4,
            metadata={
                "created_by": "bilinc.agent_runtime",
                "runtime_event": "tool_event_evidence",
                "tool_name": event.name,
                "tool_status": event.status,
            },
        )


def _copy_messages(messages: Sequence[Message]) -> List[Message]:
    return [dict(message) for message in (messages or [])]


def _last_user_content(messages: Sequence[Message]) -> str:
    for message in reversed(messages or []):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _assistant_text(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("content", "output", "text", "message"):
            if key in output:
                return str(output[key])
    return str(output)


def _coerce_tool_event(event: ToolEvent | Dict[str, Any]) -> ToolEvent:
    if isinstance(event, ToolEvent):
        return event
    return ToolEvent(
        name=str(event.get("name") or event.get("tool") or "tool"),
        input=event.get("input"),
        output=event.get("output"),
        status=str(event.get("status") or "success"),
        metadata=event.get("metadata") or {},
    )


def _stable_hash(value: Any) -> str:
    encoded = repr(_redact_obj(value)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in (value or "session")).strip("-")
    return slug or "session"


def _redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: Dict[Any, Any] = {}
        for key, item in value.items():
            if any(marker in str(key).lower() for marker in ("password", "token", "secret", "api_key", "api-key", "bearer")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_obj(item)
        return redacted
    if isinstance(value, list):
        return [_redact_obj(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_obj(item) for item in value)
    if isinstance(value, str) and ("bearer " in value.lower() or value.startswith("sk-")):
        return "[REDACTED]"
    return value
