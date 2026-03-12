"""System pack loader and character data model.

Shared infrastructure consumed by multiple engines:
- rules_engine.py (formula evaluation)
- combat_engine.py (action resolution, turn lifecycle)
- encounter.py (zone-based positioning)
- build_engine.py (character construction)

The SystemPack is a parsed representation of a system pack directory
(system.json + supporting files). It holds all system-specific
configuration: formulas, resolution rules, stacking policies, combat
positioning, etc. Individual engines read only the sections they need.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# System pack model
# ---------------------------------------------------------------------------

@dataclass
class SystemPack:
    """Parsed representation of a system pack directory."""

    name: str = ""
    dice: str = ""

    # Default values for optional variables
    defaults: dict[str, Any] = field(default_factory=dict)

    # Derived stat formulas: {"melee_attack": "str_mod + base_attack + ...", ...}
    derived: dict[str, str] = field(default_factory=dict)

    # Lookup tables: {"base_attack_full": [1, 2, 3, ...], ...}
    tables: dict[str, list] = field(default_factory=dict)

    # Constraint expressions: {"name": "expr that should be true", ...}
    constraints: dict[str, str] = field(default_factory=dict)

    # Combat resolution config: {"type": "threshold"|"degree", ...}
    resolution: dict[str, Any] = field(default_factory=dict)

    # Action definitions: {"melee_attack": {"attack_stat": ..., "defense_stat": ..., ...}, ...}
    actions: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Stacking policy: {"group_by": ..., "positive": ..., "negative": ..., ...}
    stacking: dict[str, Any] = field(default_factory=dict)

    # End-of-turn tick config: {"rounds": {"action": "decrement", "remove_at": 0}, ...}
    end_turn: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Combat positioning config: {"zone_scale": 30, "melee_range": 0, "zone_tags": {...}, ...}
    combat: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------

def _load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def load_system_pack(pack_dir: str) -> SystemPack:
    """Load a system pack from a directory of JSON files."""
    system_path = os.path.join(pack_dir, "system.json")
    if not os.path.isfile(system_path):
        raise FileNotFoundError(f"system.json not found in {pack_dir}")

    data = _load_json(system_path)
    pack = SystemPack()

    # Meta
    meta = data.get("meta", {})
    pack.name = meta.get("name", "")
    pack.dice = meta.get("dice", "")

    # Defaults for optional variables
    pack.defaults = dict(data.get("defaults", {}))

    # Derived formulas
    pack.derived = dict(data.get("derived", {}))

    # Tables
    for tbl_name, tbl_data in data.get("tables", {}).items():
        if isinstance(tbl_data, list):
            pack.tables[tbl_name] = tbl_data

    # Constraints
    pack.constraints = dict(data.get("constraints", {}))

    # Combat resolution
    pack.resolution = dict(data.get("resolution", {}))
    pack.actions = dict(data.get("actions", {}))

    # Stacking policy
    pack.stacking = dict(data.get("stacking", {}))

    # End-of-turn tick config
    pack.end_turn = dict(data.get("end_turn", {}))

    # Combat positioning config
    pack.combat = dict(data.get("combat", {}))

    return pack


# ---------------------------------------------------------------------------
# Character data extraction (from DB rows)
# ---------------------------------------------------------------------------

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


def load_character_data(db, character_id: int) -> CharacterData:
    """Load character data from the database."""
    row = db.execute(
        "SELECT id, session_id, name, level, type FROM characters WHERE id = ?",
        (character_id,),
    ).fetchone()
    if row is None:
        from _db import LoreKitError
        raise LoreKitError(f"Character {character_id} not found")

    char = CharacterData(
        character_id=row[0],
        session_id=row[1],
        name=row[2],
        level=row[3],
        char_type=row[4],
    )

    # Load attributes grouped by category
    for cat, key, val in db.execute(
        "SELECT category, key, value FROM character_attributes "
        "WHERE character_id = ? ORDER BY category, key",
        (character_id,),
    ):
        char.attributes.setdefault(cat, {})[key] = val

    # Load abilities
    for name, desc, category, uses in db.execute(
        "SELECT name, description, category, uses FROM character_abilities "
        "WHERE character_id = ?",
        (character_id,),
    ):
        char.abilities.append({"name": name, "description": desc, "category": category, "uses": uses})

    # Load equipped items
    for name, desc, qty, equipped in db.execute(
        "SELECT name, description, quantity, equipped FROM character_inventory "
        "WHERE character_id = ? AND equipped = 1",
        (character_id,),
    ):
        char.items.append({"name": name, "description": desc, "quantity": qty})

    return char
