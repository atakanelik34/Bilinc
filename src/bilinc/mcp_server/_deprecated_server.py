"""
DEPRECATED: Legacy Bilinc MCP Server.

This module is DEPRECATED and WILL BE REMOVED.
Use `bilinc.mcp_server.server_v2` instead.

This server is broken and should not be used in new code.
"""
import warnings
warnings.warn(
    "bilinc.mcp_server.server is DEPRECATED and will be removed. "
    "Use bilinc.mcp_server.server_v2 instead.",
    DeprecationWarning,
    stacklevel=2,
)
