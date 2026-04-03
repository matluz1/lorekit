"""Tests for MCP server provider configuration."""

from lorekit._mcp_app import configure_provider, get_default_model, get_provider_name


def test_configure_and_read_back():
    configure_provider(provider="claude", model="opus", campaign_dir="/tmp/test")
    assert get_provider_name() == "claude"
    assert get_default_model() == "opus"


def test_defaults_are_none():
    configure_provider(provider=None, model=None, campaign_dir=None)
    assert get_provider_name() is None
    assert get_default_model() is None
