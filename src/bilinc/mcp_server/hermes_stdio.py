"""Standard Bilinc stdio launcher for Hermes integration."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from mcp.server.stdio import stdio_server

from bilinc import StatePlane
from bilinc.mcp_server.server_v2 import create_mcp_server_v2
from bilinc.storage.sqlite import SQLiteBackend


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


async def _build_server():
    db_path = os.getenv("BILINC_DB_PATH", str(Path.home() / "bilinc.db"))
    auth_token = os.getenv("STATEMEL_API_KEY")
    max_tokens = int(os.getenv("BILINC_RATE_LIMIT_MAX_TOKENS", "10"))
    refill_rate = float(os.getenv("BILINC_RATE_LIMIT_REFILL_RATE", "1.0"))
    verify = _env_bool("BILINC_ENABLE_VERIFICATION", True)
    audit = _env_bool("BILINC_ENABLE_AUDIT", True)

    plane = StatePlane(
        backend=SQLiteBackend(db_path=db_path),
        enable_verification=verify,
        enable_audit=audit,
    )
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()

    return create_mcp_server_v2(
        plane=plane,
        auth_token=auth_token,
        max_tokens=max_tokens,
        refill_rate=refill_rate,
        transport_mode="stdio",
    )


async def main():
    server = await _build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
