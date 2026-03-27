#!/usr/bin/env python3
"""LoreKit MCP server -- long-lived process with cached embedding model."""

import sys

import lorekit.tools
from lorekit._mcp_app import mcp

if __name__ == "__main__":
    from lorekit.support.vectordb import _get_model

    _get_model()

    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
