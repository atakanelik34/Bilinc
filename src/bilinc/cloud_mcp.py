"""MCP stdio adapter for Bilinc Cloud.

Run with:

    python -m bilinc.cloud_mcp

Requires BILINC_API_KEY. This adapter exposes hosted commit, recall, and status
without bundling local StatePlane/storage internals.
"""

from __future__ import annotations

from typing import Any

from bilinc.client import CloudClient


def create_client(api_key: str | None = None, base_url: str = "https://bilinc.space") -> CloudClient:
    """Create a Bilinc Cloud client for MCP adapters."""

    return CloudClient(api_key=api_key, base_url=base_url)


def build_server():
    """Build the MCP server lazily so importing bilinc stays lightweight."""

    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - depends on optional MCP runtime import path
        raise RuntimeError("Bilinc Cloud MCP adapter requires mcp>=1.0.0") from exc

    mcp = FastMCP("bilinc")

    @mcp.tool()
    def commit_mem(
        key: str,
        value: Any,
        memory_type: str = "semantic",
        importance: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Commit a memory entry to hosted Bilinc Cloud."""

        return create_client().commit(
            key,
            value,
            memory_type=memory_type,
            importance=importance,
            metadata=metadata,
        )

    @mcp.tool()
    def recall(query: str, profile: str = "balanced", limit: int = 10) -> dict[str, Any]:
        """Recall memories from hosted Bilinc Cloud."""

        return create_client().recall(query, profile=profile, limit=limit)

    @mcp.tool()
    def status() -> dict[str, Any]:
        """Report the authenticated Bilinc Cloud workspace, plan, limits, and capabilities.

        Read-only and never billed. Use this to discover which lifecycle
        operations and recall profiles the current API key may use before
        attempting them. Secrets are never returned.
        """

        return create_client().status()

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()


__all__ = ["CloudClient", "build_server", "create_client", "main"]
