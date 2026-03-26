"""Shared MCP application instance — imported by all tools/ modules."""

from mcp.server.fastmcp import FastMCP

NPC_MCP_PORT = 3847
mcp = FastMCP("lorekit", host="127.0.0.1", port=NPC_MCP_PORT)
