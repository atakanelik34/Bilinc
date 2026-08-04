#!/usr/bin/env python3
"""Generic MCP bridge for the frozen AMB provider contract.

This file is benchmark infrastructure, not Bilinc product behavior.  It only
translates the provider-neutral remember/search/forget calls to the existing
StatePlane API.  It deliberately contains no query aliases, fixture terms,
answer normalization, result cache, or benchmark-specific scoring behavior.

The database path is mandatory so a missing environment variable cannot
silently select the user's live database.
"""

from __future__ import annotations

import asyncio
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

def _json_text(payload: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


def _content(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _new_key() -> str:
    return f"memory:{uuid.uuid4().hex}"


def _scope_visible(metadata: dict[str, Any], agent_id: str, scope: str | None) -> bool:
    stored_scope = str(metadata.get("scope") or "org")
    stored_agent = str(metadata.get("agent_id") or "")
    if scope == "agent":
        return stored_scope == "agent" and stored_agent == agent_id
    if stored_scope == "agent" and stored_agent != agent_id:
        return False
    return True


async def _build_plane(configured_path: str | None = None):
    source_root = Path(__file__).resolve().parents[2] / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from bilinc.core.stateplane import StatePlane
    from bilinc.storage.sqlite import SQLiteBackend

    db_path = configured_path or os.environ.get("BILINC_AMB_DB_PATH")
    if not db_path:
        raise RuntimeError("BILINC_AMB_DB_PATH is required for the isolated benchmark database")
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    plane = StatePlane(backend=SQLiteBackend(db_path=str(path)))
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()
    return plane


def create_server(plane) -> Server:
    server = Server("bilinc-generic-memory")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="remember",
                description="Store one memory entry.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "agent_id": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "scope": {"type": "string", "enum": ["agent", "user", "org"]},
                    },
                    "required": ["content"],
                },
            ),
            Tool(
                name="search",
                description="Search memory entries.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "agent_id": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                        "scope": {"type": "string", "enum": ["agent", "user", "org"]},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="forget",
                description="Delete one memory entry by id.",
                inputSchema={
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "remember":
            content = str(arguments.get("content") or "")
            agent_id = str(arguments.get("agent_id") or "")
            scope = str(arguments.get("scope") or "org")
            tags = arguments.get("tags") or []
            key = _new_key()
            metadata = {"agent_id": agent_id, "scope": scope, "tags": tags}
            await plane.commit_with_agm_async(
                key=key,
                value=content,
                memory_type="semantic",
                importance=0.8,
                metadata=metadata,
                source="adapter",
                session_id=agent_id,
            )
            return _json_text({"id": key, "content": content})

        if name == "search":
            query = str(arguments.get("query") or "")
            agent_id = str(arguments.get("agent_id") or "")
            scope = str(arguments["scope"]) if arguments.get("scope") is not None else None
            limit = max(0, int(arguments.get("limit") or 10))
            payload = await plane.recall_profiled(
                query=query,
                profile="balanced",
                limit=limit,
                explain=False,
            )
            results = []
            for item in payload.get("results", []):
                key = str(item.get("key") or "")
                entry = await plane.backend.load(key) if plane.backend and key else None
                metadata = entry.metadata if entry is not None else item.get("metadata") or {}
                if not _scope_visible(metadata, agent_id, scope):
                    continue
                results.append(
                    {
                        "id": key,
                        "content": _content(item.get("value")),
                        "score": float(item.get("score") or 0.0),
                        "createdAt": (
                            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(entry.created_at))
                            if entry is not None
                            else None
                        ),
                    }
                )
                if len(results) >= limit:
                    break
            return _json_text({"results": results})

        if name == "forget":
            key = str(arguments.get("id") or "")
            removed = await plane.forget(key) if key else False
            return _json_text({"success": bool(removed), "id": key})

        return _json_text({"success": False, "error": "unknown tool"})

    return server


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generic MCP memory bridge")
    parser.add_argument("--db-path", help="isolated SQLite database path")
    args = parser.parse_args()
    plane = await _build_plane(args.db_path)
    server = create_server(plane)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
