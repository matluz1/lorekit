"""Shared MCP application instance — imported by all tools/ modules."""

from mcp.server.fastmcp import FastMCP

NPC_MCP_PORT = 3847
mcp = FastMCP("lorekit", host="127.0.0.1", port=NPC_MCP_PORT)

# -- Provider configuration (set by server.py at startup) --

_provider_name: str | None = None
_default_model: str | None = None
_campaign_dir: str | None = None


def configure_provider(
    provider: str | None = None,
    model: str | None = None,
    campaign_dir: str | None = None,
) -> None:
    """Called by server.py at startup with CLI args."""
    global _provider_name, _default_model, _campaign_dir
    _provider_name = provider
    _default_model = model
    _campaign_dir = campaign_dir


def get_provider_name() -> str | None:
    return _provider_name


def get_default_model() -> str | None:
    return _default_model
