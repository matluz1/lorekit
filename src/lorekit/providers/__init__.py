"""Provider abstraction for LoreKit agent integration."""

from lorekit.providers.base import AgentProcess, AgentProvider, GameEvent, StreamChunk

__all__ = ["AgentProcess", "AgentProvider", "GameEvent", "StreamChunk", "load_provider"]


def load_provider(name: str) -> AgentProvider:
    """Load a provider by name. Providers are internal modules."""
    if name == "claude":
        from lorekit.providers.claude import ClaudeCLI

        return ClaudeCLI()
    raise ValueError(f"Unknown provider '{name}'. Available: claude")
