"""User-level configuration for LoreKit infrastructure settings."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir


@dataclass
class LoreKitConfig:
    """Infrastructure configuration (provider, model, server port, campaign dir)."""

    provider: str | None = None
    model: str | None = None
    port: int = 8765
    campaign_dir: Path | None = None


def config_path() -> Path:
    """Platform-standard config file location."""
    return Path(user_config_dir("lorekit")) / "config.toml"


def load_config(path: Path | None = None) -> LoreKitConfig:
    """Load config from TOML file. Returns defaults if file is missing."""
    p = path or config_path()
    if not p.is_file():
        return LoreKitConfig()
    with open(p, "rb") as f:
        raw = tomllib.load(f)
    agent = raw.get("agent", {})
    server = raw.get("server", {})
    campaign = raw.get("campaign", {})
    campaign_dir_str = campaign.get("dir")
    return LoreKitConfig(
        provider=agent.get("provider"),
        model=agent.get("model"),
        port=server.get("port", 8765),
        campaign_dir=Path(campaign_dir_str) if campaign_dir_str else None,
    )
