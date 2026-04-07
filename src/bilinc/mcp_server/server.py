"""
DEPRECATED: Legacy Bilinc MCP Server.

This module is deprecated and will be removed in a future release.
Use `bilinc.mcp_server.server_v2` instead.
"""
import warnings

warnings.warn(
    "bilinc.mcp_server.server is deprecated and broken. Use bilinc.mcp_server.server_v2 instead.",
    DeprecationWarning,
    stacklevel=2,
)
