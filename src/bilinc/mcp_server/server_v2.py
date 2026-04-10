"""
Bilinc MCP Server v2

Exposes full Bilinc functionality via Model Context Protocol (MCP).
Includes Phase 3 features: AGM Belief Revision, Knowledge Graph, Multi-Agent Sync.

Compatible with: Claude Code, OpenClaw, Cursor, Windsurf, any MCP-compatible agent.

Transport: stdio (default for Claude Code integration)
"""

from __future__ import annotations

import contextlib
import hashlib
import asyncio
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

from bilinc.core.stateplane import StatePlane
from bilinc.core.models import MemoryType
from bilinc.core.audit import OpType
from bilinc.mcp_server.rate_limiter import TokenBucketLimiter
from bilinc.observability.logging import log_event
from bilinc.security.input_validator import InputValidator
from bilinc.security.resource_limits import ResourceLimits

logger = logging.getLogger(__name__)

DEFAULT_HERMES_SESSION_TTL_SECONDS = 14 * 24 * 60 * 60


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


def _resolve_auth_token(auth_token: Optional[str]) -> Optional[str]:
    """Canonical auth token resolution."""
    return auth_token or os.environ.get("STATEMEL_API_KEY")


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Extract Bearer token from Authorization header."""
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        return None
    return parts[1].strip()



def _enforce_auth_policy(required_token: Optional[str], provided_token: Optional[str], transport_mode: str) -> Optional[Dict[str, Any]]:
    """
    Enforce auth policy:
    - stdio: trusted-local, token optional
    - http: token required and constant-time compared
    """
    if transport_mode == "stdio":
        return None
    if not required_token:
        return {
            "tool": "auth",
            "success": False,
            "error": "server_misconfigured",
            "message": "HTTP transport requires auth token policy.",
        }
    if not provided_token:
        return {
            "tool": "auth",
            "success": False,
            "error": "unauthorized",
            "message": "Missing auth token.",
        }
    if not hmac.compare_digest(str(provided_token), str(required_token)):
        return {
            "tool": "auth",
            "success": False,
            "error": "unauthorized",
            "message": "Invalid auth token.",
        }
    return None


def _hash_client_token(token: str) -> str:
    """Generate a stable non-reversible client identity from a bearer token."""
    return f"token:{hashlib.sha256(token.encode()).hexdigest()[:16]}"


def _resolve_http_client_id(token: Optional[str], scope: Dict[str, Any]) -> str:
    """Resolve HTTP client identity from token or client IP."""
    if token:
        return _hash_client_token(token)
    client = scope.get("client")
    if client and client[0]:
        return f"ip:{client[0]}"
    return "anonymous"


def _http_error(status_code: int, error: str, message: str) -> JSONResponse:
    """Standard JSON error shape for HTTP transport."""
    return JSONResponse(
        {
            "success": False,
            "error": error,
            "message": message,
        },
        status_code=status_code,
    )


def _increment_metric(plane: Optional[StatePlane], name: str, value: int = 1) -> None:
    if plane is not None and hasattr(plane, "metrics"):
        plane.metrics.increment(name, value)


def _record_latency(plane: Optional[StatePlane], name: str, value_ms: float) -> None:
    if plane is not None and hasattr(plane, "metrics"):
        plane.metrics.record_latency(name, value_ms)


def _record_http_request(
    plane: Optional[StatePlane],
    surface: str,
    start_time: float,
    status_code: int,
) -> None:
    elapsed = (time.perf_counter() - start_time) * 1000
    _increment_metric(plane, "http_requests_total")
    _increment_metric(plane, f"http_{surface}_requests_total")
    _record_latency(plane, f"http_{surface}_latency_ms", elapsed)
    if plane is not None and hasattr(plane, "health"):
        plane.health.update_gauge_on_metrics(plane.metrics)
    log_event(
        logger,
        "info",
        "http_request",
        surface=surface,
        status_code=status_code,
        latency_ms=round(elapsed, 3),
    )


def _health_http_status(readiness: Dict[str, Any]) -> int:
    return 503 if readiness["status"] == "failed" else 200


def _health_payload(plane: StatePlane) -> Dict[str, Any]:
    plane.health.update_gauge_on_metrics(plane.metrics)
    readiness = plane.health.readiness()
    liveness = plane.health.liveness()
    return {
        "service": "bilinc-mcp-http",
        "status": readiness["status"],
        "ephemeral": readiness["ephemeral"],
        "liveness": liveness,
        "readiness": readiness,
    }




def _run_coro_sync(coro):
    """Run coroutine from sync handler contexts."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            raise RuntimeError("Cannot run sync coroutine while event loop is active.")
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _build_metadata(args):
    """Build metadata dict from MCP tool arguments, supporting Hermes contract."""
    metadata = args.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    for field in ("source", "session_id", "canonical", "priority", "ttl"):
        val = args.get(field)
        if val is not None:
            metadata[field] = val
    return metadata

def _create_server_v2(
    plane: Optional[StatePlane] = None,
    rate_limiter: Optional[TokenBucketLimiter] = None,
    transport_mode: str = "stdio",
) -> Server:
    """Build the shared MCP server instance used by stdio and HTTP transports."""
    if plane is None:
        plane = StatePlane(backend=None, enable_verification=False, enable_audit=False)
        # Initialize Phase 3 components
        plane.init_agm()
        plane.init_knowledge_graph()

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
                        "metadata": {"type": "object", "description": "Additional metadata dict (Hermes contract)"},
                        "session_id": {"type": "string", "description": "Session identifier for multi-session tracking"},
                        "canonical": {"type": "boolean", "default": False, "description": "Mark as canonical (preferred) entry"},
                        "priority": {"type": "number", "default": 0.5, "description": "Priority for recall ordering (0.0-1.0)"},
                        "ttl": {"type": "number", "description": "Time-to-live in seconds (optional expiry)"},
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
        start_time = time.perf_counter()
        if rate_limiter is not None:
            client_id = "stdio" if transport_mode == "stdio" else "transport"
            if not rate_limiter.allow(client_id):
                _increment_metric(plane, "rate_limit_hits_total")
                _increment_metric(plane, "tool_rate_limit_hits_total")
                log_event(
                    logger,
                    "warning",
                    "tool_rate_limited",
                    tool=name,
                    transport=transport_mode,
                    client_id=client_id,
                )
                return _result_text({"error": "rate_limited", "message": "Too many requests. Try again later."})

        try:
            _increment_metric(plane, "tool_calls_total")
            _increment_metric(plane, f"tool_{name}_calls_total")
            if name == "commit_mem":
                result = await _handle_commit_mem(plane, arguments)

            elif name == "recall":
                result = await _handle_recall(plane, arguments)

            elif name == "forget":
                result = await _handle_forget(plane, arguments)

            elif name == "revise":
                result = await _handle_revise(plane, arguments)

            elif name == "status":
                result = await _handle_status(plane)

            elif name == "verify":
                result = await _handle_verify(plane, arguments)

            elif name == "consolidate":
                result = _handle_consolidate(plane, arguments)

            elif name == "snapshot":
                if plane.backend and plane.enable_audit:
                    snapshot = await plane.snapshot()
                    snapshot["tool"] = "snapshot"
                    result = _result_text(snapshot)
                else:
                    result = _handle_snapshot(plane, arguments)

            elif name == "diff":
                if plane.backend and plane.enable_audit:
                    diff = await plane.diff(arguments["ts_a"], arguments["ts_b"])
                    diff["tool"] = "diff"
                    result = _result_text(diff)
                else:
                    result = _handle_diff(plane, arguments)

            elif name == "rollback":
                if plane.backend and plane.enable_audit:
                    rollback = await plane.rollback(arguments["ts"])
                    rollback["tool"] = "rollback"
                    result = _result_text(rollback)
                else:
                    result = _handle_rollback(plane, arguments)

            elif name == "query_graph":
                result = _handle_query_graph(plane, arguments)

            elif name == "contradictions":
                result = _handle_contradictions(plane)

            else:
                result = _error_text(name, ValueError(f"Unknown tool: {name}. Available tools: commit_mem, recall, forget, revise, status, verify, consolidate, snapshot, diff, rollback, query_graph, contradictions"))

            _record_latency(plane, "tool_call_latency_ms", (time.perf_counter() - start_time) * 1000)
            log_event(logger, "info", "tool_call", tool=name, transport=transport_mode, status="success")
            return result

        except Exception as e:
            _increment_metric(plane, "backend_errors_total")
            _increment_metric(plane, "tool_errors_total")
            _record_latency(plane, "tool_call_latency_ms", (time.perf_counter() - start_time) * 1000)
            log_event(
                logger,
                "error",
                "tool_call",
                tool=name,
                transport=transport_mode,
                status="failed",
                error_type=type(e).__name__,
                error=str(e),
            )
            return _error_text(name, e)

    return server




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
    if auth_token:
        logger.info("stdio transport is trusted-local only; auth_token is ignored for request-level auth")
    rate_limiter = TokenBucketLimiter(max_tokens=max_tokens, refill_rate=refill_rate)
    return _create_server_v2(plane=plane, rate_limiter=rate_limiter, transport_mode="stdio")


def create_mcp_http_app(
    plane: Optional[StatePlane] = None,
    auth_token: Optional[str] = None,
    max_tokens: int = 10,
    refill_rate: float = 1.0,
    allow_unauthenticated: bool = False,
    route_prefix: str = "/mcp",
) -> Starlette:
    """
    Create a production-oriented HTTP MCP app with bearer auth and client-aware rate limiting.

    HTTP auth is enforced by default. To allow unauthenticated local development,
    pass allow_unauthenticated=True explicitly.
    """
    resolved_auth = _resolve_auth_token(auth_token)
    if not allow_unauthenticated and not resolved_auth:
        raise ValueError(
            "HTTP MCP auth requires auth_token or STATEMEL_API_KEY unless allow_unauthenticated=True."
        )

    route_prefix = "/" + route_prefix.strip("/")
    if plane is None:
        plane = StatePlane(backend=None, enable_verification=False, enable_audit=False)
        plane.init_agm()
        plane.init_knowledge_graph()
    plane.http_transport_config = {
        "route_prefix": route_prefix,
        "auth_required": not allow_unauthenticated,
        "rate_limit": {"max_tokens": max_tokens, "refill_rate": refill_rate},
    }

    server = _create_server_v2(plane=plane, rate_limiter=None, transport_mode="http")
    session_manager = StreamableHTTPSessionManager(server, json_response=True)
    rate_limiter = TokenBucketLimiter(max_tokens=max_tokens, refill_rate=refill_rate)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with session_manager.run():
            yield

    async def _authorize(scope, receive, send, surface: str, start_time: float) -> Optional[str]:
        headers = Headers(scope=scope)
        bearer_token = _extract_bearer_token(headers.get("authorization"))
        client_id = _resolve_http_client_id(bearer_token, scope)

        if resolved_auth:
            if bearer_token is None:
                _increment_metric(plane, "auth_failures_total")
                _record_http_request(plane, surface, start_time, 401)
                log_event(
                    logger,
                    "warning",
                    "http_auth_failed",
                    surface=surface,
                    reason="missing_bearer_token",
                    client_id=client_id,
                )
                await _http_error(401, "unauthorized", "Missing Authorization: Bearer token.")(scope, receive, send)
                return None
            if not hmac.compare_digest(bearer_token, resolved_auth):
                _increment_metric(plane, "auth_failures_total")
                _record_http_request(plane, surface, start_time, 401)
                log_event(
                    logger,
                    "warning",
                    "http_auth_failed",
                    surface=surface,
                    reason="invalid_bearer_token",
                    client_id=client_id,
                )
                await _http_error(401, "unauthorized", "Invalid bearer token.")(scope, receive, send)
                return None
        elif not allow_unauthenticated:
            _increment_metric(plane, "auth_failures_total")
            _record_http_request(plane, surface, start_time, 401)
            log_event(
                logger,
                "warning",
                "http_auth_failed",
                surface=surface,
                reason="auth_required",
                client_id=client_id,
            )
            await _http_error(401, "unauthorized", "HTTP auth is required.")(scope, receive, send)
            return None

        if not rate_limiter.allow(client_id):
            _increment_metric(plane, "rate_limit_hits_total")
            _record_http_request(plane, surface, start_time, 429)
            log_event(
                logger,
                "warning",
                "http_rate_limited",
                surface=surface,
                client_id=client_id,
            )
            await _http_error(429, "rate_limited", "Too many requests. Try again later.")(scope, receive, send)
            return None
        return client_id

    def _authorize_request(request: Request, surface: str, start_time: float) -> tuple[Optional[str], Optional[JSONResponse]]:
        headers = request.headers
        bearer_token = _extract_bearer_token(headers.get("authorization"))
        client_id = _resolve_http_client_id(bearer_token, request.scope)

        if resolved_auth:
            if bearer_token is None:
                _increment_metric(plane, "auth_failures_total")
                _record_http_request(plane, surface, start_time, 401)
                log_event(
                    logger,
                    "warning",
                    "http_auth_failed",
                    surface=surface,
                    reason="missing_bearer_token",
                    client_id=client_id,
                )
                return None, _http_error(401, "unauthorized", "Missing Authorization: Bearer token.")
            if not hmac.compare_digest(bearer_token, resolved_auth):
                _increment_metric(plane, "auth_failures_total")
                _record_http_request(plane, surface, start_time, 401)
                log_event(
                    logger,
                    "warning",
                    "http_auth_failed",
                    surface=surface,
                    reason="invalid_bearer_token",
                    client_id=client_id,
                )
                return None, _http_error(401, "unauthorized", "Invalid bearer token.")
        elif not allow_unauthenticated:
            _increment_metric(plane, "auth_failures_total")
            _record_http_request(plane, surface, start_time, 401)
            log_event(
                logger,
                "warning",
                "http_auth_failed",
                surface=surface,
                reason="auth_required",
                client_id=client_id,
            )
            return None, _http_error(401, "unauthorized", "HTTP auth is required.")

        if not rate_limiter.allow(client_id):
            _increment_metric(plane, "rate_limit_hits_total")
            _record_http_request(plane, surface, start_time, 429)
            log_event(
                logger,
                "warning",
                "http_rate_limited",
                surface=surface,
                client_id=client_id,
            )
            return None, _http_error(429, "rate_limited", "Too many requests. Try again later.")
        return client_id, None

    async def http_transport(scope, receive, send):
        start_time = time.perf_counter()
        client_id = await _authorize(scope, receive, send, "mcp", start_time)
        if client_id is None:
            return

        await session_manager.handle_request(scope, receive, send)
        _record_http_request(plane, "mcp", start_time, 200)
        log_event(logger, "info", "http_mcp_request", client_id=client_id, status_code=200)

    async def health_endpoint(request: Request) -> JSONResponse:
        start_time = time.perf_counter()
        client_id, error_response = _authorize_request(request, "health", start_time)
        if error_response is not None:
            return error_response

        payload = _health_payload(plane)
        status_code = _health_http_status(payload["readiness"])
        _record_http_request(plane, "health", start_time, status_code)
        log_event(
            logger,
            "info",
            "health_check",
            client_id=client_id,
            readiness_status=payload["readiness"]["status"],
            liveness_status=payload["liveness"]["status"],
            status_code=status_code,
        )
        return JSONResponse(payload, status_code=status_code)

    async def metrics_endpoint(request: Request) -> PlainTextResponse:
        start_time = time.perf_counter()
        client_id, error_response = _authorize_request(request, "metrics", start_time)
        if error_response is not None:
            return PlainTextResponse(error_response.body.decode(), status_code=error_response.status_code)

        plane.health.update_gauge_on_metrics(plane.metrics)
        output = plane.metrics.export_prometheus()
        _record_http_request(plane, "metrics", start_time, 200)
        log_event(logger, "info", "metrics_scrape", client_id=client_id, status_code=200)
        return PlainTextResponse(output, media_type="text/plain; version=0.0.4")

    return Starlette(
        routes=[
            Route("/health", endpoint=health_endpoint, methods=["GET"]),
            Route("/metrics", endpoint=metrics_endpoint, methods=["GET"]),
            Mount(route_prefix, app=http_transport),
        ],
        lifespan=lifespan,
    )


# ─── Handler Functions (sync, called from async handlers) ─────────

async def _handle_commit_mem(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
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
    source = args.get("source", "mcp")
    session_id = args.get("session_id", "")
    metadata = _build_metadata(args)
    ttl = args.get("ttl")
    invalid_at = args.get("invalid_at")

    if ttl is None and str(source).startswith("hermes_session"):
        ttl = DEFAULT_HERMES_SESSION_TTL_SECONDS

    # Resource limit check
    if hasattr(plane, "working_memory") and memory_type == "working":
        if not ResourceLimits.check_entry_capacity(MemoryType.WORKING, plane.working_memory.count):
            return _result_text({
                "tool": "commit_mem", "success": False, 
                "error": f"Working memory full (max {ResourceLimits.LIMITS['max_entries'][MemoryType.WORKING]})"
            })

    # Commit with AGM
    if hasattr(plane, "commit_with_agm_async"):
        result = await plane.commit_with_agm_async(key, value, memory_type=memory_type, importance=importance)
    else:
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
            "metadata": metadata,
            "ttl": ttl,
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


async def _handle_recall(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    key = args.get("key")
    memory_type = args.get("memory_type")
    limit = args.get("limit", 20)
    min_strength = args.get("min_strength", 0.0)
    canonical_only = bool(args.get("canonical_only", False))
    exclude_session_summaries = bool(args.get("exclude_session_summaries", False))

    entries_by_key = {}

    # Start from persistent backend when available.
    if plane.backend:
        backend_entries = []
        if key:
            backend_entries = await plane.recall(key=key)
        elif memory_type:
            backend_entries = await plane.recall(memory_type=MemoryType(memory_type), limit=limit)
        elif hasattr(plane.backend, "list_all"):
            backend_entries = await plane.backend.list_all()

        for entry in backend_entries:
            if entry.current_strength < min_strength:
                continue
            entries_by_key[entry.key] = entry

    # Overlay AGM beliefs as the freshest truth when initialized.
    if hasattr(plane, "agm_engine") and plane.agm_engine:
        beliefs = plane.agm_engine.belief_state.get_all_beliefs()
        for entry in beliefs:
            if key and entry.key != key:
                continue
            if memory_type and entry.memory_type.value != memory_type:
                continue
            if entry.current_strength < min_strength:
                continue
            entries_by_key[entry.key] = entry

    # Include working memory entries when present.
    if hasattr(plane, "working_memory"):
        for slot in plane.working_memory.get_all():
            if key and slot.key != key:
                continue
            if memory_type and slot.memory_type.value != memory_type:
                continue
            if slot.current_strength < min_strength:
                continue
            entries_by_key[slot.key] = slot

    # Apply limit
    entries = list(entries_by_key.values())[:limit]

    # Backend fallback for fresh process / persistent mode
    if not entries and getattr(plane, "backend", None):
        backend_entries = _run_coro_sync(plane.backend.list_all())
        for e in backend_entries:
            if key and e.key != key:
                continue
            if memory_type and e.memory_type.value != memory_type:
                continue
            if e.current_strength < min_strength:
                continue
            entries.append(e)

    # Apply limit
    entries = list(entries_by_key.values())[:limit]

    return _result_text({
        "tool": "recall",
        "count": len(entries),
        "entries": [_json_safe(e) for e in entries],
    })


async def _handle_forget(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    key = args["key"]
    reason = args.get("reason", "manual")

    removed = False
    existing_backend = await plane.backend.load(key) if plane.backend else None
    existing_belief = None

    # Remove from AGM
    if hasattr(plane, "agm_engine") and plane.agm_engine:
        existing_belief = plane.agm_engine.belief_state.get_belief(key)
        result = plane.agm_engine.contract(key)
        removed = result.success
    if hasattr(plane, "working_memory"):
        plane.working_memory.remove(key)
    if plane.backend:
        removed = await plane.backend.delete(key) or removed
    if plane.enable_audit and plane.audit and (existing_backend or existing_belief):
        plane.audit.log(
            OpType.FORGET,
            key,
            before_value=(existing_backend.to_dict() if existing_backend else existing_belief.to_dict()),
            metadata={"reason": reason, "deleted": removed},
        )

    backend_removed = False
    if getattr(plane, "backend", None):
        backend_removed = bool(_run_coro_sync(plane.backend.delete(key)))

    return _result_text({
        "tool": "forget",
        "key": key,
        "reason": reason,
        "removed": removed,
        "backend_removed": backend_removed,
    })


async def _handle_revise(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
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

    previous_entry = await plane.backend.load(key) if plane.backend else None
    entry = MemoryEntry(key=key, value=value, importance=importance, memory_type=MemoryType.SEMANTIC)
    if hasattr(plane, "_apply_entry_verification"):
        plane._apply_entry_verification(entry)
    result = plane.agm_engine.revise(entry, strategy=strategy)
    winning_entry = plane.agm_engine.belief_state.get_belief(key)

    if result.success and winning_entry and hasattr(plane, "knowledge_graph") and plane.knowledge_graph:
        plane.knowledge_graph.ingest_memory_entry(winning_entry)

    if plane.backend and result.success and winning_entry:
        await plane.backend.save(winning_entry)
        if plane.enable_audit and plane.audit:
            previous_state = previous_entry.to_dict() if previous_entry else None
            next_state = winning_entry.to_dict()
            if previous_state != next_state:
                plane.audit.log(
                    OpType.UPDATE if previous_entry else OpType.CREATE,
                    key,
                    before_value=previous_state,
                    after_value=next_state,
                    metadata={
                        "revision_strategy": strategy.value,
                        "conflicts_resolved": result.conflicts_resolved,
                    },
                )


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


async def _handle_status(plane: StatePlane, args: Dict[str, Any] = None) -> List[TextContent]:
    status = {"tool": "status", "version": "1.0.1"}


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
    if getattr(plane, "backend", None):
        try:
            if hasattr(plane.backend, "stats"):
                status["backend"] = _run_coro_sync(plane.backend.stats())
            elif hasattr(plane.backend, "get_stats"):
                status["backend"] = _run_coro_sync(plane.backend.get_stats())
        except Exception as exc:
            status["backend"] = {"error": str(exc)}

    if plane.backend:
        status["backend"] = await plane.backend.stats()

    status["health"] = {
        "liveness": plane.health.liveness()["status"],
        "readiness": plane.health.readiness()["status"],
    }

    return _result_text(status)


async def _handle_verify(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    key = args["key"]

    if hasattr(plane, "agm_engine") and plane.agm_engine:
        entry = plane.agm_engine.belief_state.get_belief(key)
        if entry is not None:
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

    if plane.backend:
        entry = await plane.backend.load(key)
        if entry is not None:
            return _result_text({
                "tool": "verify",
                "key": key,
                "exists": True,
                "is_verified": entry.is_verified,
                "verification_score": entry.verification_score,
                "verification_method": entry.verification_method,
                "entrenchment": plane.agm_engine.get_entrenchment(key) if hasattr(plane, "agm_engine") and plane.agm_engine else None,
                "strength": entry.current_strength,
            })


    return _result_text({
        "tool": "verify",
        "key": key,
        "exists": False,
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

    if getattr(plane, "backend", None):
        try:
            snap = _run_coro_sync(plane.snapshot())
            snapshot["backend_snapshot"] = snap
        except Exception as exc:
            snapshot["backend_snapshot_error"] = str(exc)

    return _result_text(snapshot)


def _handle_diff(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    ts_a = args.get("ts_a")
    ts_b = args.get("ts_b")
    if ts_a is None or ts_b is None:
        return _result_text({
            "tool": "diff",
            "success": False,
            "error": "ts_a and ts_b are required for diff",
        })
    if not getattr(plane, "backend", None) and not getattr(plane, "audit", None):
        return _result_text({
            "tool": "diff",
            "success": False,
            "error": "persistent backend or audit trail required",
        })
    data = _run_coro_sync(plane.diff(float(ts_a), float(ts_b)))
    data["tool"] = "diff"
    data["success"] = True
    return _result_text(data)


def _handle_rollback(plane: StatePlane, args: Dict[str, Any]) -> List[TextContent]:
    ts = args.get("ts")
    if ts is None:
        return _result_text({"tool": "rollback", "success": False, "error": "ts is required"})
    if not getattr(plane, "backend", None) and not getattr(plane, "audit", None):
        return _result_text({
            "tool": "rollback",
            "success": False,
            "error": "persistent backend or audit trail required",
        })
    restored = _run_coro_sync(plane.rollback(float(ts)))
    return _result_text({
        "tool": "rollback",
        "success": True,
        "restored_count": restored,
        "target_ts": float(ts),
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
