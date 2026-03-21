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

    # NPC combat intent schema
    pack.intent = dict(data.get("intent", {}))

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


# ---------------------------------------------------------------------------
# System info — human-readable summary of what a pack provides
# ---------------------------------------------------------------------------


def _group_by_prefix(names: dict | list, min_group: int = 2) -> list[tuple[str, list[str]]]:
    """Group variable names by detected prefix for readable display.

    Discovers prefixes from the data itself — no hardcoded system knowledge.
    A prefix is the part before the last underscore (e.g. 'bonus_dodge' →
    'bonus'). Prefixes with fewer than `min_group` members are merged into
    a catch-all group.
    """
    keys = sorted(names if isinstance(names, list) else names.keys())

    groups: dict[str, list[str]] = {}
    for key in keys:
        if "_" in key:
            prefix = key[: key.index("_")]
        else:
            prefix = ""
        groups.setdefault(prefix, []).append(key)

    # Split into real groups vs ungrouped
    result: list[tuple[str, list[str]]] = []
    ungrouped: list[str] = []
    for prefix in sorted(groups):
        members = groups[prefix]
        if prefix and len(members) >= min_group:
            # Capitalize prefix for display: "bonus" → "bonus_*"
            result.append((f"{prefix}_*", members))
        else:
            ungrouped.extend(members)

    if ungrouped:
        result.append(("other", ungrouped))

    return result


def _summarize_on_hit(on_hit: dict) -> str:
    """One-line summary of an on_hit block."""
    parts = []
    if on_hit.get("damage_roll") and on_hit.get("subtract_from"):
        parts.append(f"damage → {on_hit['subtract_from']}")
    if on_hit.get("apply_modifiers"):
        mods = on_hit["apply_modifiers"]
        targets = [m["target_stat"] for m in mods]
        parts.append(f"modifiers({', '.join(targets)})")
    if on_hit.get("push"):
        direction = on_hit.get("push_direction", "away")
        parts.append(f"push {on_hit['push']} {direction}")
    if on_hit.get("damage_rank_stat"):
        parts.append(f"damage_rank={on_hit['damage_rank_stat']}")
    return ", ".join(parts) if parts else "none"


def system_info(pack_dir: str, section: str = "all") -> str:
    """Return a human-readable summary of what a system pack provides."""
    system_path = os.path.join(pack_dir, "system.json")
    if not os.path.isfile(system_path):
        raise FileNotFoundError(f"system.json not found in {pack_dir}")

    data = _load_json(system_path)
    meta = data.get("meta", {})
    pack_name = meta.get("name", os.path.basename(pack_dir))
    dice = meta.get("dice", "")

    valid_sections = {"actions", "defaults", "derived", "build", "constraints", "resolution", "combat", "all"}
    if section not in valid_sections:
        return f"ERROR: Unknown section '{section}'. Valid: {', '.join(sorted(valid_sections))}"

    sections: list[str] = []

    # Header
    header_parts = [f"SYSTEM: {pack_name}"]
    if dice:
        header_parts.append(f"Dice: {dice}")
    sections.append("\n".join(header_parts))

    # Actions
    if section in ("all", "actions"):
        actions = data.get("actions", {})
        if actions:
            lines = ["", "ACTIONS:"]
            for name, adef in actions.items():
                atk = adef.get("attack_stat", "?")
                dfn = adef.get("defense_stat", "?")
                rng = adef.get("range", "?")
                contested = " (contested)" if adef.get("contested") else ""

                # Summarize effect
                effect_parts = []
                if adef.get("damage_rank_stat"):
                    effect_parts.append(f"damage_rank={adef['damage_rank_stat']}")
                on_hit = adef.get("on_hit")
                if on_hit:
                    effect_parts.append(_summarize_on_hit(on_hit))
                effect = f"  effect: {', '.join(effect_parts)}" if effect_parts else ""

                lines.append(f"  {name}: {atk} vs {dfn}, range={rng}{contested}")
                if effect:
                    lines.append(f"    {effect}")
            sections.append("\n".join(lines))

    # Defaults
    if section in ("all", "defaults"):
        defaults = data.get("defaults", {})
        if defaults:
            lines = ["", "DEFAULTS (settable attributes):"]
            for label, keys in _group_by_prefix(defaults):
                lines.append(f"  {label}: {', '.join(keys)}")
            sections.append("\n".join(lines))

    # Derived
    if section in ("all", "derived"):
        derived = data.get("derived", {})
        if derived:
            lines = ["", "DERIVED (computed stats):"]
            for label, keys in _group_by_prefix(derived):
                lines.append(f"  {label}: {', '.join(keys)}")

            if section == "derived":
                # When requesting just derived, show formulas too
                lines.append("")
                lines.append("FORMULAS:")
                for key in sorted(derived):
                    lines.append(f"  {key} = {derived[key]}")
            sections.append("\n".join(lines))

    # Build
    if section in ("all", "build"):
        build = data.get("build", {})
        if build:
            lines = ["", "BUILD (character construction):"]
            budget = build.get("budget")
            if budget:
                lines.append(f"  budget: {budget.get('total', '?')}")
            for cat, cfg in build.items():
                if cat == "budget":
                    continue
                if not isinstance(cfg, dict):
                    continue
                parts = []
                if "keys" in cfg:
                    parts.append(f"keys=[{', '.join(cfg['keys'])}]")
                if "source" in cfg:
                    parts.append(f"source={cfg['source']}")
                if "cost_per_rank" in cfg:
                    parts.append(f"cost={cfg['cost_per_rank']}/rank")
                if "writes" in cfg:
                    writes = cfg["writes"]
                    parts.append(f"writes=[{', '.join(writes.keys())}]")
                if cfg.get("pipeline"):
                    parts.append("pipeline")
                if cfg.get("feeds"):
                    parts.append("feeds")
                if cfg.get("effects"):
                    parts.append("effects")
                lines.append(f"  {cat}: {', '.join(parts)}")
            sections.append("\n".join(lines))

    # Constraints
    if section in ("all", "constraints"):
        constraints = data.get("constraints", {})
        if constraints:
            lines = ["", "CONSTRAINTS:"]
            for name, expr in constraints.items():
                lines.append(f"  {name}: {expr}")
            sections.append("\n".join(lines))

    # Resolution
    if section in ("all", "resolution"):
        res = data.get("resolution", {})
        if res:
            lines = ["", "RESOLUTION:"]
            res_type = res.get("type", "?")
            parts = [f"type={res_type}"]
            if "defense_dc_offset" in res:
                parts.append(f"dc_offset={res['defense_dc_offset']}")
            if "resistance_stat" in res:
                parts.append(f"resistance={res['resistance_stat']}")
            if "dc_base" in res:
                parts.append(f"dc_base={res['dc_base']}")
            lines.append(f"  {', '.join(parts)}")

            on_failure = res.get("on_failure", {})
            if on_failure:
                for degree, effect in sorted(on_failure.items()):
                    label = effect.get("label", "")
                    inc = effect.get("increment", {})
                    desc_parts = []
                    if inc:
                        desc_parts.append("+".join(f"{k}={v}" for k, v in inc.items()))
                    if label:
                        desc_parts.append(label)
                    lines.append(f"  degree {degree}: {', '.join(desc_parts)}")
            sections.append("\n".join(lines))

    # Combat positioning
    if section in ("all", "combat"):
        combat = data.get("combat", {})
        if combat:
            lines = ["", "COMBAT (positioning):"]
            lines.append(
                f"  zone_scale={combat.get('zone_scale', 1)}, "
                f"unit={combat.get('movement_unit', 'zone')}, "
                f"melee_range={combat.get('melee_range', 0)}"
            )
            zone_tags = combat.get("zone_tags", {})
            if zone_tags:
                lines.append("  Zone tags:")
                for tag, cfg in zone_tags.items():
                    parts = []
                    if "target_stat" in cfg:
                        parts.append(f"{cfg['target_stat']} {cfg.get('value', 0):+d}")
                    if "movement_multiplier" in cfg:
                        parts.append(f"movement x{cfg['movement_multiplier']}")
                    if "miss_chance" in cfg:
                        parts.append(f"miss {int(cfg['miss_chance'] * 100)}%")
                    lines.append(f"    {tag}: {', '.join(parts)}")
            sections.append("\n".join(lines))

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Character data extraction (from DB rows)
# ---------------------------------------------------------------------------


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
        "SELECT category, key, value FROM character_attributes WHERE character_id = ? ORDER BY category, key",
        (character_id,),
    ):
        char.attributes.setdefault(cat, {})[key] = val

    # Load abilities
    for name, desc, category, uses, cost in db.execute(
        "SELECT name, description, category, uses, cost FROM character_abilities WHERE character_id = ?",
        (character_id,),
    ):
        char.abilities.append({"name": name, "description": desc, "category": category, "uses": uses, "cost": cost})

    # Load equipped items
    for name, desc, qty, equipped in db.execute(
        "SELECT name, description, quantity, equipped FROM character_inventory WHERE character_id = ? AND equipped = 1",
        (character_id,),
    ):
        char.items.append({"name": name, "description": desc, "quantity": qty})

    return char
