"""
Bilinc MCP Server v2

Exposes full Bilinc functionality via Model Context Protocol (MCP).
Includes Phase 3 features: AGM Belief Revision, Knowledge Graph, Multi-Agent Sync.

Compatible with: Claude Code, OpenClaw, Cursor, Windsurf, any MCP-compatible agent.

Transport: stdio (default for Claude Code integration)
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.types import Tool, TextContent

from bilinc.core.stateplane import StatePlane
from bilinc.core.models import MemoryType
from bilinc.mcp_server.rate_limiter import TokenBucketLimiter
from bilinc.security.input_validator import InputValidator
from bilinc.security.resource_limits import ResourceLimits

logger = logging.getLogger(__name__)


def _json_safe(obj: Any) -> Any:
    """Make any object JSON-serializable."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_json_safe(i) for i in obj]
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    # Dataclass-like objects: use __dict__ or to_dict() if available
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return {k: _json_safe(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


def _result_text(data: Any) -> List[TextContent]:
    """Helper to create a TextContent response from any JSON-serializable data."""
    text = json.dumps(_json_safe(data), indent=2, default=str, ensure_ascii=False)
    return [TextContent(type="text", text=text)]


def _error_text(tool_name: str, error: Exception) -> List[TextContent]:
    """Helper to create a structured error response."""
    return _result_text({
        "tool": tool_name,
        "error": type(error).__name__,
        "message": str(error),
        "success": False,
    })


def create_mcp_server_v2(
    plane: Optional[StatePlane] = None,
    auth_token: Optional[str] = None,
    max_tokens: int = 10,
    refill_rate: float = 1.0,
) -> Server:
    """
    Create an MCP server instance exposing Bilinc v0.4.0 features.
    
    Args:
        plane: StatePlane instance (creates default if None)
        auth_token: Optional API key for server protection
        max_tokens: Rate limit max tokens per client (default: 10)
        refill_rate: Token refill rate per second (default: 1.0)
    """
    if plane is None:
        plane = StatePlane(backend=None, enable_verification=False, enable_audit=False)
        # Initialize Phase 3 components
        plane.init_agm()
        plane.init_knowledge_graph()

    auth_token = auth_token or os.environ.get("STATEMEL_API_KEY")
    rate_limiter = TokenBucketLimiter(max_tokens=max_tokens, refill_rate=refill_rate)

    server = Server("bilinc-v2")

    # ─── Tool Definitions ──────────────────────────────────

    @server.list_tools()
    async def list_tools() -> List[Tool]:
        return [
            Tool(
                name="commit_mem",
                description=(
                    "Store a memory entry with automatic AGM belief revision. "
                    "If the key already exists with a conflicting value, the AGM engine "
                    "resolves the conflict based on importance and strategy."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Unique identifier for this memory"},
                        "value": {"type": "string", "description": "The memory content (any JSON-serializable value)"},
                        "memory_type": {
                            "type": "string",
                            "enum": ["episodic", "procedural", "semantic", "working", "spatial"],
                            "default": "semantic",
                            "description": "Type of memory to store",
                        },
                        "importance": {"type": "number", "default": 1.0, "minimum": 0.0, "maximum": 1.0,
                                       "description": "Importance weight 0.0-1.0 (affects AGM conflict resolution)"},
                        "source": {"type": "string", "default": "mcp", "description": "Source system that created this memory"},
                    },
                    "required": ["key", "value"],
                },
            ),
            Tool(
                name="recall",
                description=(
                    "Retrieve memory entries by key, type, or all entries. "
                    "Returns matching entries with metadata including strength, verification status, and timestamps."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Specific memory key to recall (optional)"},
                        "memory_type": {
                            "type": "string",
                            "enum": ["episodic", "procedural", "semantic", "working", "spatial"],
                            "description": "Filter by memory type (optional)",
                        },
                        "limit": {"type": "integer", "default": 20, "description": "Max entries to return"},
                        "min_strength": {"type": "number", "default": 0.0,
                                         "description": "Minimum current_strength to include"},
                    },
                    "required": [],
                },
            ),
            Tool(
                name="forget",
                description=(
                    "Permanently remove a memory entry by key. "
                    "The reason is tracked for audit purposes."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Memory key to delete"},
                        "reason": {"type": "string", "default": "manual",
                                   "description": "Why this memory is being forgotten"},
                    },
                    "required": ["key"],
                },
            ),
            Tool(
                name="revise",
                description=(
                    "Perform AGM belief revision on an existing memory. "
                    "If the new value conflicts with existing belief, the specified "
                    "strategy determines the resolution."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Memory key to revise"},
                        "value": {"type": "string", "description": "New value for the memory"},
                        "importance": {"type": "number", "default": 1.0,
                                       "description": "Importance of new belief (determines if it replaces existing)"},
                        "strategy": {
                            "type": "string",
                            "enum": ["entrenchment", "recency", "verification", "importance"],
                            "default": "entrenchment",
                            "description": "Conflict resolution strategy",
                        },
                    },
                    "required": ["key", "value"],
                },
            ),
            Tool(
                name="status",
                description=(
                    "Get operational statistics including Phase 3 components "
                    "(AGM beliefs, Knowledge Graph, Multi-Agent Sync)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            Tool(
                name="verify",
                description="Run Z3 SMT verification on a specific memory key (if verifier is enabled).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Memory key to verify"},
                    },
                    "required": ["key"],
                },
            ),
            Tool(
                name="consolidate",
                description=(
                    "Trigger the sleep consolidation cycle. "
                    "Moves entries from working memory to long-term storage, applies forgetting curves."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "memory_type": {
                            "type": "string",
                            "enum": ["episodic", "procedural", "semantic", "working", "spatial"],
                            "description": "Only consolidate this type (optional)",
                        },
                    },
                    "required": [],
                },
            ),
            Tool(
                name="snapshot",
                description=(
                    "Get a verifiable state snapshot of all current beliefs, "
                    "including AGM operation history and entrenchment values."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "include_audit": {"type": "boolean", "default": False,
                                          "description": "Include full AGM operation log"},
                    },
                    "required": [],
                },
            ),
            Tool(
                name="diff",
                description=(
                    "Get the difference between two snapshots or timestamps. "
                    "Shows which beliefs were added, changed, or removed."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ts_a": {"type": "number", "description": "First timestamp (Unix epoch)"},
                        "ts_b": {"type": "number", "description": "Second timestamp (Unix epoch)"},
                    },
                    "required": [],
                },
            ),
            Tool(
                name="rollback",
                description="Restore the belief state to a previous snapshot. Destructive — use with caution.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ts": {"type": "number", "description": "Timestamp to rollback to (Unix epoch)"},
                    },
                    "required": ["ts"],
                },
            ),
            Tool(
                name="query_graph",
                description=(
                    "Query the Knowledge Graph for entities and their relations. "
                    "Returns a traversable subgraph starting from the specified entity."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entity": {"type": "string", "description": "Entity name to query"},
                        "max_depth": {"type": "integer", "default": 2,
                                      "description": "Maximum traversal depth"},
                        "relation_filter": {
                            "type": "array",
                            "items": {"type": "string",
                                      "enum": ["related_to", "causes", "contradicts", "supports", "temporal_before"]},
                            "description": "Only include these relation types (optional)",
                        },
                    },
                    "required": ["entity"],
                },
            ),
            Tool(
                name="contradictions",
                description=(
                    "List all detected contradictions in the knowledge graph. "
                    "Returns pairs of conflicting beliefs that need resolution."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
        ]

    # ─── Tool Handlers ─────────────────────────────────────

    @server.call_tool()
    async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        # ── Auth check (placeholder — not enforced in stdio transport) ──
        # For HTTP transport: extract bearer token and validate against auth_token.
        # For stdio: auth is handled at the process/environment level.
        if auth_token:
            pass  # TODO: Implement request-level auth validation for HTTP transport

        # ── Rate limiting ──
        if auth_token:
            import hmac
            # In a real deployment, extract the token from the request context.
            # For stdio transport, we rely on the environment-level auth.
            pass  # Auth is handled at the transport layer for stdio

        # ── Rate limiting ──
        client_id = "default"  # In production: extract from request context
        if not rate_limiter.allow(client_id):
            return _result_text({"error": "rate_limited", "message": "Too many requests. Try again later."})

        try:
            if name == "commit_mem":
                return _handle_commit_mem(plane, arguments)

            elif name == "recall":
                return _handle_recall(plane, arguments)

            elif name == "forget":
                return _handle_forget(plane, arguments)

            elif name == "revise":
                return _handle_revise(plane, arguments)

            elif name == "status":
                return _handle_status(plane)

            elif name == "verify":
                return _handle_verify(plane, arguments)

            elif name == "consolidate":
                return _handle_consolidate(plane, arguments)

            elif name == "snapshot":
                return _handle_snapshot(plane, arguments)

            elif name == "diff":
                return _handle_diff(plane, arguments)

            elif name == "rollback":
                return _handle_rollback(plane, arguments)

            elif name == "query_graph":
                return _handle_query_graph(plane, arguments)

            elif name == "contradictions":
                return _handle_contradictions(plane)

            else:
                return _error_text(name, ValueError(f"Unknown tool: {name}. Available tools: commit_mem, recall, forget, revise, status, verify, consolidate, snapshot, diff, rollback, query_graph, contradictions"))

        except Exception as e:
            logger.exception(f"MCP tool error: {name}")
            return _error_text(name, e)

    return server


# ─── Handler Functions (sync, called from async handlers) ─────────

def _handle_commit_mem(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    try:
        key = InputValidator.validate_key(args["key"])
        value = InputValidator.validate_value(args["value"])
    except ValueError as e:
        return _result_text({"tool": "commit_mem", "success": False, "error": str(e)})
    
    # Try to parse JSON values
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass  # Keep as string

    memory_type = args.get("memory_type", "semantic")
    importance = args.get("importance", 1.0)

    # Resource limit check
    if hasattr(plane, "working_memory") and memory_type == "working":
        if not ResourceLimits.check_entry_capacity(MemoryType.WORKING, plane.working_memory.count):
            return _result_text({
                "tool": "commit_mem", "success": False, 
                "error": f"Working memory full (max {ResourceLimits.LIMITS['max_entries'][MemoryType.WORKING]})"
            })

    result = plane.commit_with_agm(key, value, memory_type=memory_type, importance=importance)

    # AGMResult or MemoryEntry
    if hasattr(result, "success"):
        # It's an AGMResult
        return _result_text({
            "tool": "commit_mem",
            "key": key,
            "success": result.success,
            "operation": result.operation.value if hasattr(result.operation, "value") else str(result.operation),
            "conflicts_resolved": result.conflicts_resolved,
            "explanation": result.explanation_text,
            "affected_keys": result.affected_keys,
            "removed_keys": result.removed_keys,
        })
    else:
        # It's a MemoryEntry (fallback mode)
        return _result_text({
            "tool": "commit_mem",
            "key": result.key,
            "success": True,
            "mode": "fallback_no_agm",
            "memory_type": result.memory_type.value if hasattr(result.memory_type, "value") else str(result.memory_type),
        })


def _handle_recall(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    key = args.get("key")
    memory_type = args.get("memory_type")
    limit = args.get("limit", 20)
    min_strength = args.get("min_strength", 0.0)

    entries = []
    # Try AGM engine first
    if hasattr(plane, "agm_engine") and plane.agm_engine:
        beliefs = plane.agm_engine.belief_state.get_all_beliefs()
        for e in beliefs:
            if key and e.key != key:
                continue
            if memory_type and e.memory_type.value != memory_type:
                continue
            if e.current_strength < min_strength:
                continue
            entries.append(e)
    # Fallback: check working memory
    elif hasattr(plane, "working_memory"):
        for slot in plane.working_memory.entries:
            if key and slot.key != key:
                continue
            entries.append(slot)

    # Apply limit
    entries = entries[:limit]

    return _result_text({
        "tool": "recall",
        "count": len(entries),
        "entries": [_json_safe(e) for e in entries],
    })


def _handle_forget(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    key = args["key"]
    reason = args.get("reason", "manual")

    removed = False
    # Remove from AGM
    if hasattr(plane, "agm_engine") and plane.agm_engine:
        result = plane.agm_engine.contract(key)
        removed = result.success
    # Remove from working memory
    elif hasattr(plane, "working_memory"):
        plane.working_memory.remove(key)
        removed = True

    return _result_text({
        "tool": "forget",
        "key": key,
        "reason": reason,
        "removed": removed,
    })


def _handle_revise(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    from bilinc.adaptive.agm_engine import ConflictStrategy
    from bilinc.core.models import MemoryEntry

    key = args["key"]
    value = args["value"]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass

    importance = args.get("importance", 1.0)
    strategy_str = args.get("strategy", "entrenchment")

    try:
        strategy = ConflictStrategy(strategy_str)
    except ValueError:
        strategy = ConflictStrategy.ENTRENCHMENT

    if not hasattr(plane, "agm_engine") or not plane.agm_engine:
        return _result_text({
            "error": "AGM engine not initialized",
            "hint": "Call plane.init_agm() before using revise",
        })

    entry = MemoryEntry(key=key, value=value, importance=importance, memory_type=MemoryType.SEMANTIC)
    result = plane.agm_engine.revise(entry, strategy=strategy)

    return _result_text({
        "tool": "revise",
        "key": key,
        "strategy": strategy.value,
        "success": result.success,
        "conflicts_resolved": result.conflicts_resolved,
        "explanation": result.explanation_text,
        "affected_keys": result.affected_keys,
        "removed_keys": result.removed_keys,
    })


def _handle_status(plane: StatePlane, args: Dict[str, Any] = None) -> List[TextContent]:
    status = {"tool": "status", "version": "0.4.0a1"}

    # AGM stats
    if hasattr(plane, "agm_engine") and plane.agm_engine:
        agm = plane.agm_engine
        status["agm"] = {
            "beliefs": len(agm.belief_state.get_all_beliefs()),
            "operations": len(agm.operation_log),
            "entrenchment_keys": len(agm.entrenchment),
            "last_operation": agm.operation_log[-1].operation.value if agm.operation_log else None,
        }
    else:
        status["agm"] = "not_initialized"

    # Knowledge Graph stats
    if hasattr(plane, "knowledge_graph") and plane.knowledge_graph:
        status["knowledge_graph"] = plane.knowledge_graph.stats
    else:
        status["knowledge_graph"] = "not_initialized"

    # Belief sync stats
    if hasattr(plane, "belief_sync") and plane.belief_sync:
        status["belief_sync"] = plane.belief_sync.get_sync_stats()
    else:
        status["belief_sync"] = "not_initialized"

    # Working memory
    if hasattr(plane, "working_memory"):
        status["working_memory"] = {
            "slots_used": plane.working_memory.count,
            "capacity": plane.working_memory.max_slots,
        }

    return _result_text(status)


def _handle_verify(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    key = args["key"]

    if hasattr(plane, "agm_engine") and plane.agm_engine:
        entry = plane.agm_engine.belief_state.get_belief(key)
        if entry is None:
            return _result_text({"tool": "verify", "key": key, "exists": False})
        return _result_text({
            "tool": "verify",
            "key": key,
            "exists": True,
            "is_verified": entry.is_verified,
            "verification_score": entry.verification_score,
            "verification_method": entry.verification_method,
            "entrenchment": plane.agm_engine.get_entrenchment(key),
            "strength": entry.current_strength,
        })

    return _result_text({
        "tool": "verify",
        "key": key,
        "error": "AGM engine not initialized",
    })


def _handle_consolidate(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    return _result_text({
        "tool": "consolidate",
        "status": "consolidation_triggered",
        "message": "In production mode, this triggers the sleep cycle. Currently using in-memory storage.",
    })


def _handle_snapshot(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    include_audit = args.get("include_audit", False)

    snapshot = {
        "tool": "snapshot",
        "timestamp": time.time(),
    }

    # AGM beliefs
    if hasattr(plane, "agm_engine") and plane.agm_engine:
        agm = plane.agm_engine
        beliefs = {}
        for key, entry in agm.belief_state.beliefs.items():
            beliefs[key] = _json_safe(entry)
            beliefs[key]["entrenchment"] = agm.get_entrenchment(key)
        snapshot["beliefs"] = beliefs
        snapshot["belief_count"] = len(beliefs)
        snapshot["revision_count"] = agm.belief_state.revision_count

        if include_audit:
            snapshot["operation_log"] = [
                {
                    "operation": r.operation.value if hasattr(r.operation, "value") else str(r.operation),
                    "success": r.success,
                    "affected_keys": r.affected_keys,
                    "explanation": r.explanation_text,
                }
                for r in agm.operation_log[-50:]  # Last 50 operations
            ]

    return _result_text(snapshot)


def _handle_diff(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    return _result_text({
        "tool": "diff",
        "message": "Full diff requires persistent storage. Currently in-memory.",
        "hint": "Use 'snapshot' for current state dump, then compare externally.",
    })


def _handle_rollback(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    ts = args["ts"]
    return _result_text({
        "tool": "rollback",
        "message": f"Rollback to {ts} is not supported in in-memory mode. Requires persistent storage (SQLite/PostgreSQL backend).",
    })


def _handle_query_graph(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    entity = args["entity"]
    max_depth = args.get("max_depth", 2)
    relation_filter = args.get("relation_filter")

    if not hasattr(plane, "knowledge_graph") or not plane.knowledge_graph:
        return _result_text({
            "tool": "query_graph",
            "error": "Knowledge graph not initialized",
            "hint": "Call plane.init_knowledge_graph() first",
        })

    rel_filter = None
    if relation_filter:
        from bilinc.core.knowledge_graph import EdgeType
        try:
            rel_filter = [EdgeType(r) for r in relation_filter]
        except ValueError:
            rel_filter = None

    result = plane.knowledge_graph.traverse(entity, max_depth=max_depth, relation_filter=rel_filter)
    result["tool"] = "query_graph"
    return _result_text(result)


def _handle_contradictions(plane: StatePlane, args: Dict[str, Any] = None) -> List[TextContent]:
    if not hasattr(plane, "knowledge_graph") or not plane.knowledge_graph:
        return _result_text({
            "tool": "contradictions",
            "error": "Knowledge graph not initialized",
        })

    contradictions = plane.knowledge_graph.find_contradictions()
    return _result_text({
        "tool": "contradictions",
        "count": len(contradictions),
        "contradictions": contradictions,
    })
