"""LangGraph workspace adapter for Bilinc cognitive runtime.

This is the flagship framework-facing integration: a thin LangGraph-shaped layer
on top of ``BilincAgentRuntime``. It does not create a parallel memory path and it
does not require LangGraph as an import-time dependency.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from bilinc.integrations.agent_runtime import BilincAgentRuntime, RuntimeModelInput, RuntimeTurnResult


LangGraphNode = Callable[..., Any]


@dataclass
class LangGraphTurnResult:
    """Receipt for a LangGraph node turn captured by Bilinc."""

    session_id: str
    runtime_result: RuntimeTurnResult
    output_state: Dict[str, Any]


class LangGraphWorkspace:
    """LangGraph-compatible adapter backed by BilincAgentRuntime."""

    def __init__(self, *, runtime: BilincAgentRuntime):
        self.runtime = runtime

    @classmethod
    def from_state_plane(
        cls,
        state_plane: Any,
        *,
        agent_id: str = "langgraph-agent",
        default_profile: str = "balanced",
    ) -> "LangGraphWorkspace":
        return cls(runtime=BilincAgentRuntime.from_state_plane(state_plane, agent_id=agent_id, default_profile=default_profile))

    @classmethod
    def from_runtime(cls, runtime: BilincAgentRuntime) -> "LangGraphWorkspace":
        return cls(runtime=runtime)

    async def pre_node(
        self,
        state: Dict[str, Any],
        *,
        config: Optional[Dict[str, Any]] = None,
        user_input: Optional[str] = None,
        budget_tokens: int = 4096,
        profile: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RuntimeModelInput:
        """Inject Bilinc context into a LangGraph state before node execution."""

        session_id = _session_id(config)
        messages = _messages(state)
        resolved_user_input = user_input or _last_user_content(messages)
        return await self.runtime.before_model_call(
            session_id=session_id,
            state=state,
            user_input=resolved_user_input,
            budget_tokens=budget_tokens,
            profile=profile,
            metadata={"integration": "langgraph", "phase": "pre_node", **(metadata or {})},
        )

    async def post_node(
        self,
        *,
        state: Dict[str, Any],
        prior_state: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        user_input: Optional[str] = None,
        assistant_output: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LangGraphTurnResult:
        """Capture a LangGraph node result after execution."""

        session_id = _session_id(config)
        prior_messages = _messages(prior_state)
        output_messages = _messages(state)
        resolved_user_input = user_input or _last_user_content(prior_messages)
        resolved_output = assistant_output if assistant_output is not None else _last_assistant_content(output_messages)
        tool_events = state.get("bilinc_tool_events") or state.get("tool_events") or []
        runtime_result = await self.runtime.after_model_call(
            session_id=session_id,
            user_input=resolved_user_input,
            assistant_output=resolved_output,
            tool_events=tool_events,
            metadata={"integration": "langgraph", "phase": "post_node", **(metadata or {})},
        )
        return LangGraphTurnResult(session_id=session_id, runtime_result=runtime_result, output_state=dict(state))

    def wrap_node(self, node: LangGraphNode) -> Callable[..., Awaitable[Any]]:
        """Wrap a LangGraph node callable with pre/post Bilinc hooks."""

        async def wrapped(state: Dict[str, Any], config: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Any:
            prepared = await self.pre_node(
                state,
                config=config,
                budget_tokens=kwargs.pop("budget_tokens", 4096),
                profile=kwargs.pop("profile", None),
                metadata=kwargs.pop("metadata", None),
            )
            output = node(prepared.state, config=config, **kwargs)
            if inspect.isawaitable(output):
                output = await output
            if isinstance(output, dict):
                await self.post_node(state=output, prior_state=state, config=config)
            return output

        return wrapped


def _session_id(config: Optional[Dict[str, Any]]) -> str:
    configurable = (config or {}).get("configurable", {})
    return str(configurable.get("thread_id") or configurable.get("session_id") or "langgraph-session")


def _messages(state: Dict[str, Any]) -> list[Dict[str, Any]]:
    return [dict(message) for message in state.get("messages", [])]


def _last_user_content(messages: list[Dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _last_assistant_content(messages: list[Dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "assistant":
            return str(message.get("content") or "")
    return ""
