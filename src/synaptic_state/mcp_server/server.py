"""
SynapticAI MCP Server

Exposes SynapticAI functionality via Model Context Protocol (MCP).
Allows any MCP-compatible agent (Claude Code, OpenClaw, Cursor, etc.)
to use SynapticAI for persistent, verifiable memory.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.types import Tool, TextContent

from synaptic_state.core.stateplane import StatePlane
from synaptic_state.core.models import MemoryType

logger = logging.getLogger(__name__)

synaptic_plane = StatePlane()


def create_mcp_server(plane: Optional[StatePlane] = None) -> Server:
    """Create an MCP server instance."""
    global synaptic_plane
    if plane:
        synaptic_plane = plane
    
    server = Server("synaptic-state")
    
    @server.list_tools()
    async def list_tools() -> List[Tool]:
        return [
            Tool(
                name="commit",
                description="Commit a memory entry with verification. Supports episodic, procedural, semantic, and symbolic memory types.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Unique identifier for this memory"},
                        "value": {"type": "string", "description": "The memory content (JSON-serializable)"},
                        "memory_type": {
                            "type": "string",
                            "enum": ["episodic", "procedural", "semantic", "symbolic"],
                            "default": "episodic",
                            "description": "Type of memory"
                        },
                        "metadata": {"type": "object", "description": "Additional metadata"},
                        "verify": {"type": "boolean", "default": True, "description": "Run verification gate"},
                        "ttl": {"type": "number", "description": "Time-to-live in seconds (optional)"},
                        "source": {"type": "string", "default": "mcp", "description": "Source of the memory"},
                        "session_id": {"type": "string", "description": "Session identifier"},
                    },
                    "required": ["key", "value"],
                },
            ),
            Tool(
                name="recall",
                description="Recall memories with budget-aware allocation across memory types.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "intent": {"type": "string", "description": "What you're looking for"},
                        "budget_tokens": {"type": "integer", "default": 2048, "description": "Max tokens to allocate"},
                        "strategy": {
                            "type": "string",
                            "enum": ["greedy", "rl_optimized", "symbolic_heavy", "conversation"],
                            "default": "rl_optimized",
                        },
                        "min_confidence": {"type": "number", "default": 0.3, "description": "Minimum confidence to include"},
                    },
                    "required": [],
                },
            ),
            Tool(
                name="forget",
                description="Explicitly forget (remove) a memory entry.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Memory key to forget"},
                        "reason": {"type": "string", "default": "manual", "description": "Why it's being forgotten"},
                    },
                    "required": ["key"],
                },
            ),
            Tool(
                name="explain",
                description="Get explainable forgetting: 'Why was this forgotten?'",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Memory key to explain"},
                    },
                    "required": ["key"],
                },
            ),
            Tool(
                name="status",
                description="Get operational statistics and memory health report.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
        ]
    
    @server.call_tool()
    async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        try:
            if name == "commit":
                result = synaptic_plane.commit(
                    key=arguments["key"],
                    value=json.loads(arguments["value"]) if isinstance(arguments["value"], str) else arguments["value"],
                    memory_type=arguments.get("memory_type", "episodic"),
                    metadata=arguments.get("metadata", {}),
                    verify=arguments.get("verify", True),
                    ttl=arguments.get("ttl"),
                    source=arguments.get("source", "mcp"),
                    session_id=arguments.get("session_id", ""),
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
            elif name == "recall":
                result = synaptic_plane.recall(
                    intent=arguments.get("intent", ""),
                    budget_tokens=arguments.get("budget_tokens", 2048),
                    strategy=arguments.get("strategy", "rl_optimized"),
                    min_confidence=arguments.get("min_confidence", 0.3),
                )
                output = {
                    "memories": [m.to_dict() for m in result.memories],
                    "budget": {
                        "requested": result.budget_requested,
                        "allocated": result.budget_allocated,
                        "estimated_tokens": result.total_tokens_estimated,
                    },
                    "quality": {
                        "stale_count": result.stale_count,
                        "conflict_count": result.conflict_count,
                    },
                }
                return [TextContent(type="text", text=json.dumps(output, indent=2))]
            
            elif name == "forget":
                entry = synaptic_plane.forget(
                    key=arguments["key"],
                    reason=arguments.get("reason", "manual"),
                )
                return [TextContent(type="text", text=json.dumps({"status": "forgotten", "key": arguments["key"]}, indent=2))]
            
            elif name == "explain":
                explanation = synaptic_plane.explain_forgetting(arguments["key"])
                return [TextContent(type="text", text=json.dumps(explanation, indent=2))]
            
            elif name == "status":
                stats = synaptic_plane.get_stats()
                drift = synaptic_plane.get_drift_report()
                return [TextContent(type="text", text=json.dumps({"stats": stats, "drift": drift}, indent=2))]
            
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]
        
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {type(e).__name__}: {str(e)}")]
    
    return server
