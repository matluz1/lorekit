"""Crunch rules engine — loads system packs, resolves dependency graphs,
computes derived stats, and validates constraints.

A system pack is a directory of JSON files describing a rule system.
The engine is generic; rules are pure data.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from rules_formulas import (
    FormulaContext,
    FormulaError,
    calc,
    extract_deps,
    parse,
)


# ---------------------------------------------------------------------------
# System pack model
# ---------------------------------------------------------------------------

@dataclass
class SystemPack:
    """Parsed representation of a system pack directory."""

    name: str = ""
    dice: str = ""

    # Abilities
    ability_list: list[str] = field(default_factory=list)
    ability_mod_formula: str = ""
    ability_cost_per_rank: int = 0

    # Short name mapping: {"str": "Strength", "dex": "Dexterity", ...}
    ability_short_names: dict[str, str] = field(default_factory=dict)
    # Reverse: {"Strength": "str", ...}
    ability_to_short: dict[str, str] = field(default_factory=dict)

    # Derived stat formulas: {"melee_attack": "proficiency + mod(str) + ...", ...}
    derived: dict[str, str] = field(default_factory=dict)

    # Lookup tables: {"proficiency": [2, 2, 2, 2, 3, ...], ...}
    tables: dict[str, list] = field(default_factory=dict)

    # Constraint expressions: {"name": "expr that should be true", ...}
    constraints: dict[str, str] = field(default_factory=dict)

    # Iterative attack rules (optional)
    iterative_threshold: int = 0
    iterative_penalty: int = 0

    # Class definitions: {"fighter": ClassDef, ...}
    classes: dict[str, ClassDef] = field(default_factory=dict)

    # Feats / advantages: {"power_attack": FeatDef, ...}
    feats: dict[str, FeatDef] = field(default_factory=dict)

    # Scales: {"duration": ["instant", "concentration", ...], ...}
    scales: dict[str, list[str]] = field(default_factory=dict)

    # Pipeline stages (optional, for power costing)
    pipeline: list[PipelineStage] = field(default_factory=list)


@dataclass
class ClassDef:
    name: str = ""
    hit_die: str = ""
    progressions: dict[str, str] = field(default_factory=dict)  # variable -> table key
    saves: dict[str, str] = field(default_factory=dict)
    levels: dict[int, LevelEntry] = field(default_factory=dict)


@dataclass
class LevelEntry:
    features: list[str] = field(default_factory=list)
    choices: list[dict] = field(default_factory=list)


@dataclass
class FeatDef:
    name: str = ""
    category: str = ""
    prereqs: dict[str, Any] = field(default_factory=dict)
    combat_option: bool = False
    ranked: bool = False
    param: str = ""
    effects: dict[str, float] = field(default_factory=dict)
    effects_per_rank: dict[str, float] = field(default_factory=dict)


@dataclass
class PipelineStage:
    stage: str = ""
    formula: str = ""


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------

def _load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _gen_short_names(abilities: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Generate short name mappings for ability scores.

    Uses the first 3 lowercase chars of each ability name. If there are
    collisions, falls back to the full lowercase name.
    """
    short_to_full: dict[str, str] = {}
    full_to_short: dict[str, str] = {}

    for name in abilities:
        short = name[:3].lower()
        if short in short_to_full:
            # Collision — use full lowercase for both
            prev_full = short_to_full.pop(short)
            prev_key = prev_full.lower()
            short_to_full[prev_key] = prev_full
            full_to_short[prev_full] = prev_key
            new_key = name.lower()
            short_to_full[new_key] = name
            full_to_short[name] = new_key
        else:
            short_to_full[short] = name
            full_to_short[name] = short

    # Also add full lowercase as an alias
    for name in abilities:
        lower = name.lower()
        if lower not in short_to_full:
            short_to_full[lower] = name
            full_to_short.setdefault(name, lower)

    return short_to_full, full_to_short


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

    # Abilities
    abilities = data.get("ability_scores", {})
    pack.ability_list = abilities.get("list", [])
    pack.ability_mod_formula = abilities.get("modifier", "")
    pack.ability_cost_per_rank = abilities.get("cost_per_rank", 0)
    pack.ability_short_names, pack.ability_to_short = _gen_short_names(pack.ability_list)

    # Derived formulas
    pack.derived = dict(data.get("derived", {}))

    # Tables
    for tbl_name, tbl_data in data.get("tables", {}).items():
        if isinstance(tbl_data, list):
            pack.tables[tbl_name] = tbl_data

    # Constraints
    pack.constraints = dict(data.get("constraints", {}))

    # Iterative attacks
    iterative = data.get("iterative_attacks", {})
    pack.iterative_threshold = iterative.get("threshold", 0)
    pack.iterative_penalty = iterative.get("penalty", 0)

    # Scales
    pack.scales = dict(data.get("scales", {}))

    # Pipeline
    for stage_data in data.get("pipeline", []):
        pack.pipeline.append(PipelineStage(
            stage=stage_data.get("stage", ""),
            formula=stage_data.get("formula", ""),
        ))

    # Load classes
    classes_dir = os.path.join(pack_dir, "classes")
    if os.path.isdir(classes_dir):
        for fname in os.listdir(classes_dir):
            if fname.endswith(".json"):
                cls_data = _load_json(os.path.join(classes_dir, fname))
                cls_key = fname[:-5]  # strip .json
                cls = ClassDef()
                cls_meta = cls_data.get("meta", {})
                cls.name = cls_meta.get("name", cls_key)
                cls.hit_die = cls_meta.get("hit_die", "")
                cls.progressions = dict(cls_meta.get("progressions", {}))
                cls.saves = dict(cls_meta.get("saves", {}))
                # Levels: {"level": {"1": {...}, "2": {...}}}
                level_section = cls_data.get("level", {})
                if isinstance(level_section, dict):
                    for lvl_str, lvl_data in level_section.items():
                        try:
                            lvl_num = int(lvl_str)
                        except ValueError:
                            continue
                        entry = LevelEntry(
                            features=lvl_data.get("features", []),
                            choices=lvl_data.get("choices", []),
                        )
                        cls.levels[lvl_num] = entry
                pack.classes[cls_key] = cls

    # Load feats
    feats_path = os.path.join(pack_dir, "feats.json")
    if os.path.isfile(feats_path):
        feats_data = _load_json(feats_path)
        for feat_key, feat_data in feats_data.items():
            if not isinstance(feat_data, dict):
                continue
            feat = FeatDef(
                name=feat_data.get("name", feat_key),
                category=feat_data.get("category", ""),
                prereqs=dict(feat_data.get("prereqs", {})),
                combat_option=feat_data.get("combat_option", False),
                ranked=feat_data.get("ranked", False),
                param=feat_data.get("param", ""),
                effects=dict(feat_data.get("effects", {})),
                effects_per_rank=dict(feat_data.get("effects_per_rank", {})),
            )
            pack.feats[feat_key] = feat

    # Also load advantages.json (point-buy systems)
    advantages_path = os.path.join(pack_dir, "advantages.json")
    if os.path.isfile(advantages_path):
        adv_data = _load_json(advantages_path)
        for adv_key, adv_info in adv_data.items():
            if not isinstance(adv_info, dict):
                continue
            feat = FeatDef(
                name=adv_info.get("name", adv_key),
                category=adv_info.get("category", ""),
                prereqs=dict(adv_info.get("prereqs", {})),
                ranked=adv_info.get("ranked", False),
                effects=dict(adv_info.get("effects", {})),
                effects_per_rank=dict(adv_info.get("effects_per_rank", {})),
            )
            pack.feats[adv_key] = feat

    return pack


# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------

def _build_dep_graph(derived: dict[str, str]) -> dict[str, set[str]]:
    """Build a dependency graph: stat -> set of stats it depends on."""
    graph: dict[str, set[str]] = {}
    for stat, formula in derived.items():
        ast = parse(formula)
        deps = extract_deps(ast)
        # Only keep deps that are themselves derived stats
        graph[stat] = deps & set(derived.keys())
    return graph


def _topo_sort(graph: dict[str, set[str]]) -> list[str]:
    """Topological sort via Kahn's algorithm. Raises on cycles."""
    in_degree: dict[str, int] = {node: 0 for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            if dep in graph:
                in_degree.setdefault(dep, 0)

    # Build reverse adjacency: dep -> set of nodes that depend on it
    reverse: dict[str, set[str]] = defaultdict(set)
    for node, deps in graph.items():
        for dep in deps:
            if dep in graph:
                reverse[dep].add(node)
                in_degree[node] = in_degree.get(node, 0)

    # Recount in-degrees properly
    in_degree = {node: 0 for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            if dep in in_degree:
                pass  # dep exists in graph
        in_degree[node] = len(deps & set(graph.keys()))

    queue = [node for node, deg in in_degree.items() if deg == 0]
    result = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        for dependent in reverse.get(node, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(graph):
        missing = set(graph.keys()) - set(result)
        raise FormulaError(f"Circular dependency detected among: {missing}")

    return result


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


# ---------------------------------------------------------------------------
# Recalculation engine
# ---------------------------------------------------------------------------

@dataclass
class CalcResult:
    """Result of a rules recalculation."""
    derived: dict[str, Any] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)  # stat -> (old, new)


def _build_context(pack: SystemPack, char: CharacterData) -> FormulaContext:
    """Build a FormulaContext from a system pack and character data."""
    ctx = FormulaContext()
    ctx.ability_mod_formula = pack.ability_mod_formula
    ctx.tables = dict(pack.tables)

    # Base values from character
    ctx.values["level"] = char.level

    # Ability scores: store both short name and as ability score
    ability_cat = None
    for cat in ("ability", "stat", "abilities", "stats"):
        if cat in char.attributes:
            ability_cat = cat
            break

    if ability_cat:
        for key, val in char.attributes[ability_cat].items():
            try:
                num_val = float(val) if "." in val else int(val)
            except ValueError:
                continue
            # Store in values under the key name
            ctx.values[key] = num_val
            # Also register as ability score for mod()
            ctx.ability_scores[key] = num_val
            # If this key matches a short name, also store under the full name
            if key in pack.ability_short_names:
                full = pack.ability_short_names[key]
                ctx.ability_scores[full] = num_val
            # If this key is a full ability name, also store under short name
            if key in pack.ability_to_short:
                short = pack.ability_to_short[key]
                ctx.values[short] = num_val
                ctx.ability_scores[short] = num_val

    # All other attribute categories as values
    for cat, attrs in char.attributes.items():
        if cat == ability_cat:
            continue
        for key, val in attrs.items():
            try:
                num_val = float(val) if "." in val else int(val)
                ctx.values[f"{cat}.{key}"] = num_val
                ctx.values[key] = num_val
            except ValueError:
                ctx.values[f"{cat}.{key}"] = val
                ctx.values[key] = val

    # Class-derived values (if character has a class)
    class_name = ctx.values.get("class", "")
    if isinstance(class_name, str) and class_name:
        cls_key = class_name.lower().replace(" ", "_")
        cls = pack.classes.get(cls_key)
        if cls:
            # Class progressions (table-backed variables)
            for var_name, table_key in cls.progressions.items():
                if table_key in pack.tables:
                    tbl = pack.tables[table_key]
                    if char.level <= len(tbl):
                        ctx.values[var_name] = tbl[char.level - 1]

            # Saves from class progression
            for save_name, prog_type in cls.saves.items():
                table_key = f"{save_name}_{prog_type}"
                if table_key in pack.tables:
                    save_table = pack.tables[table_key]
                    if char.level <= len(save_table):
                        ctx.values[f"{save_name}_base"] = save_table[char.level - 1]

            # Hit die
            if cls.hit_die:
                # Extract numeric part: "d10" -> 10
                die_str = cls.hit_die.lstrip("d")
                try:
                    die_val = int(die_str)
                    ctx.values["hit_die"] = die_val
                    ctx.values["hit_die_avg"] = math.ceil(die_val / 2) + 1
                except ValueError:
                    pass

    # Aggregate bonuses from feats/abilities on the character
    bonuses: dict[str, list[float]] = defaultdict(list)
    for ability in char.abilities:
        ability_key = ability["name"].lower().replace(" ", "_")
        feat = pack.feats.get(ability_key)
        if feat:
            if feat.ranked:
                # Try to find rank from ability description or a stored attribute
                rank = 1  # default rank
                # Check if there's a rank stored as attribute
                rank_val = char.attributes.get("feat_rank", {}).get(ability_key, "1")
                try:
                    rank = int(rank_val)
                except ValueError:
                    rank = 1
                for stat, bonus in feat.effects_per_rank.items():
                    bonuses[stat].append(bonus * rank)
            elif not feat.combat_option:
                # Always-on effects
                for stat, bonus in feat.effects.items():
                    bonuses[stat].append(bonus)

    ctx.bonuses = dict(bonuses)
    return ctx


def recalculate(pack: SystemPack, char: CharacterData) -> CalcResult:
    """Recalculate all derived stats for a character.

    Returns a CalcResult with computed values, constraint violations,
    and a diff of what changed.
    """
    result = CalcResult()

    if not pack.derived:
        return result

    # Build evaluation context
    ctx = _build_context(pack, char)

    # Load previous derived values for diffing
    old_derived: dict[str, str] = {}
    if "derived" in char.attributes:
        old_derived = dict(char.attributes["derived"])

    # Topological sort of derived stats
    dep_graph = _build_dep_graph(pack.derived)
    eval_order = _topo_sort(dep_graph)

    # Evaluate each derived stat in order
    for stat in eval_order:
        formula = pack.derived[stat]
        try:
            value = calc(formula, ctx)
            # Ensure numeric results are clean ints where possible
            if isinstance(value, float) and value == int(value):
                value = int(value)
            result.derived[stat] = value
            # Feed back into context for downstream stats
            ctx.values[stat] = value
        except FormulaError as e:
            result.derived[stat] = f"ERROR: {e}"

    # Validate constraints
    for name, expr in pack.constraints.items():
        try:
            passed = calc(expr, ctx)
            if not passed:
                result.violations.append(f"{name}: {expr}")
        except FormulaError:
            result.violations.append(f"{name}: could not evaluate ({expr})")

    # Compute diff
    for stat, value in result.derived.items():
        old_val = old_derived.get(stat)
        if old_val is None:
            result.changes[stat] = (None, value)
        elif str(value) != old_val:
            result.changes[stat] = (old_val, value)

    return result


# ---------------------------------------------------------------------------
# Write results back to DB
# ---------------------------------------------------------------------------

def write_derived(db, character_id: int, derived: dict[str, Any]) -> int:
    """Write derived stats to character_attributes with category='derived'.

    Returns the number of attributes written.
    """
    count = 0
    for key, value in derived.items():
        if isinstance(value, str) and value.startswith("ERROR:"):
            continue  # Skip errored stats
        db.execute(
            "INSERT INTO character_attributes (character_id, category, key, value) "
            "VALUES (?, 'derived', ?, ?) "
            "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
            (character_id, key, str(value)),
        )
        count += 1
    db.commit()
    return count


# ---------------------------------------------------------------------------
# Top-level: full recalc from DB
# ---------------------------------------------------------------------------

def rules_calc(db, character_id: int, pack_dir: str) -> str:
    """Full recalculation pipeline: load data, compute, write back, return summary."""
    pack = load_system_pack(pack_dir)
    char = load_character_data(db, character_id)
    result = recalculate(pack, char)

    if not result.derived:
        return f"RULES_CALC: {char.name} — no derived stats defined in system pack"

    written = write_derived(db, character_id, result.derived)

    lines = [f"RULES_CALC: {char.name} — {written} stats computed"]

    if result.changes:
        lines.append("CHANGES:")
        for stat, (old, new) in result.changes.items():
            if old is None:
                lines.append(f"  {stat}: → {new}")
            else:
                lines.append(f"  {stat}: {old} → {new}")

    if result.violations:
        lines.append("VIOLATIONS:")
        for v in result.violations:
            lines.append(f"  ⚠ {v}")

    return "\n".join(lines)
