"""System pack loader.

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
    pack_dir: str = ""

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

    # Start-of-turn tick config: {"until_next_turn": {"action": "remove"}, ...}
    start_turn: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Combat positioning config: {"zone_scale": 30, "melee_range": 0, "zone_tags": {...}, ...}
    combat: dict[str, Any] = field(default_factory=dict)

    # Named combat options: {"power_attack": {"trade": {...}, "max": 5}, ...}
    combat_options: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Named outcome tables for effect resolution: {"damage_degrees": {...}, ...}
    outcome_tables: dict[str, dict[str, Any]] = field(default_factory=dict)

    # NPC combat intent schema: {"steps": {...}, "default_sequence": [...], "sequence_rules": {...}, ...}
    intent: dict[str, Any] = field(default_factory=dict)


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
    pack.pack_dir = pack_dir

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

    # Start-of-turn tick config
    pack.start_turn = dict(data.get("start_turn", {}))

    # Combat positioning config
    pack.combat = dict(data.get("combat", {}))

    # Named combat options
    pack.combat_options = dict(data.get("combat_options", {}))

    # Outcome tables for effect resolution
    pack.outcome_tables = dict(data.get("outcome_tables", {}))

    # NPC combat intent schema
    pack.intent = dict(data.get("intent", {}))

    return pack
