"""Shared data types for the cruncher package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CharacterData:
    """Raw character data extracted from the database."""

    character_id: int = 0
    session_id: int = 0
    name: str = ""
    level: int = 1
    char_type: str = "pc"

    # category -> key -> value (all strings from DB)
    attributes: dict[str, dict[str, str]] = field(default_factory=dict)

    # Abilities on the character (feats, powers, etc.)
    abilities: list[dict[str, str]] = field(default_factory=list)

    # Equipped items
    items: list[dict[str, Any]] = field(default_factory=list)
