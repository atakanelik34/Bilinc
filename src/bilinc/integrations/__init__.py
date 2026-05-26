"""Integrations with external frameworks."""
from bilinc.integrations.cross_tool import CrossToolTranslator, ToolFormat
from bilinc.integrations.agent_runtime import (
    BilincAgentRuntime,
    RuntimeAdapterProtocol,
    RuntimeModelInput,
    RuntimeTurnResult,
    ToolEvent,
)

__all__ = [
    "CrossToolTranslator",
    "ToolFormat",
    "BilincAgentRuntime",
    "RuntimeAdapterProtocol",
    "RuntimeModelInput",
    "RuntimeTurnResult",
    "ToolEvent",
]
