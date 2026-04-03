#!/usr/bin/env python3
"""LoreKit MCP server -- long-lived process with cached embedding model."""

from __future__ import annotations

import os
import sys

import lorekit.tools  # noqa: F401 — registers all MCP tools
from lorekit._mcp_app import configure_provider, mcp


def _parse_arg(name: str) -> str | None:
    """Extract --name value from sys.argv."""
    flag = f"--{name}"
    if flag in sys.argv:
        idx = sys.argv.index(flag)
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return None


if __name__ == "__main__":
    from lorekit.support.vectordb import _get_model

    _get_model()

    provider = _parse_arg("provider")
    model = _parse_arg("model")
    campaign_dir = _parse_arg("campaign-dir")

    configure_provider(provider=provider, model=model, campaign_dir=campaign_dir)

    if campaign_dir:
        os.environ["LOREKIT_DB_DIR"] = campaign_dir

    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
