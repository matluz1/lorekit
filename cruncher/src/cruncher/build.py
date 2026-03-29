"""Data-driven build engine for Crunch.

Reads the "build" section from a system pack's system.json and processes
character selections (ancestry, class, feats, powers, etc.) into flat
character attributes. The rules engine then evaluates derived formulas
against these attributes.

The engine is domain-agnostic: it has no RPG-specific concepts. All system
knowledge lives in the JSON data files. The engine only understands:

  - ranked_purchase: sum listed keys × cost_per_rank
  - source (single): load file, select one entry, apply writes/progressions
  - source (multiple): load file, match abilities, aggregate effects
  - pipeline: parse structured data from abilities, compute costs via formulas
  - array: flat cost for alternate/dynamic entries
  - sub_budget: secondary point pools from computed attributes
  - budget: total point pool from a formula
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BuildResult:
    """Result of processing build rules."""

    attributes: dict[str, Any] = field(default_factory=dict)  # key -> value
    costs: dict[str, float] = field(default_factory=dict)  # category -> cost
    ability_costs: dict[str, dict[str, float]] = field(default_factory=dict)  # category -> {name -> cost}
    warnings: list[str] = field(default_factory=list)
    budget_total: float = 0
    budget_spent: float = 0
    cost_changes: dict[str, tuple[float, float]] = field(default_factory=dict)  # cat -> (old, new)


def _load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _resolve_path(data: dict, dotted_path: str) -> Any:
    """Resolve a dotted path like 'meta.hp_per_level' against a dict."""
    parts = dotted_path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _get_character_value(char_attrs: dict[str, dict[str, str]], key: str) -> str | None:
    """Find a value across all attribute categories."""
    for cat_attrs in char_attrs.values():
        if key in cat_attrs:
            return cat_attrs[key]
    return None


def _parse_number(val: str) -> int | float:
    """Parse a string as a number."""
    try:
        return float(val) if "." in val else int(val)
    except (ValueError, TypeError):
        return 0


def _expand_template(pattern: str, char_attrs: dict[str, dict[str, str]]) -> str | None:
    """Expand {variable} tokens in a source pattern from character attributes.

    Returns None if any variable is missing.
    """
    missing = False

    def replacer(match):
        nonlocal missing
        var_name = match.group(1)
        val = _get_character_value(char_attrs, var_name)
        if val is None:
            missing = True
            return match.group(0)
        return val.lower().replace(" ", "_")

    result = re.sub(r"\{(\w+)\}", replacer, pattern)
    return None if missing else result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def process_build(
    pack_dir: str,
    char_attrs: dict[str, dict[str, str]],
    char_abilities: list[dict[str, str]],
    level: int,
    char_items: list[dict[str, Any]] | None = None,
) -> BuildResult:
    """Process build rules and return computed attributes."""
    system_path = os.path.join(pack_dir, "system.json")
    if not os.path.isfile(system_path):
        return BuildResult()

    system_data = _load_json(system_path)
    build_rules = system_data.get("build", {})

    if not build_rules:
        return BuildResult()

    result = BuildResult()

    # --- Budget setup ---
    budget_rules = build_rules.get("budget")
    if budget_rules:
        _process_budget(budget_rules, char_attrs, system_data, result)

    # --- Process each build category ---
    for category, rules in build_rules.items():
        if not isinstance(rules, dict):
            continue
        if category in ("budget", "array", "sub_budget"):
            continue  # handled separately

        # Dispatch based on rule content, not category name
        if "keys" in rules:
            _process_ranked_purchase(rules, char_attrs, category, result)
        elif rules.get("effect_source") or rules.get("pipeline"):
            _process_pipeline(rules, pack_dir, char_abilities, system_data, result, char_attrs=char_attrs)
        elif "source" in rules:
            _process_source(
                pack_dir,
                rules,
                category,
                char_attrs,
                char_abilities,
                level,
                result,
                char_items=char_items,
            )

    # --- Arrays ---
    array_rules = build_rules.get("array")
    if array_rules:
        _process_arrays(array_rules, char_abilities, result)

    # --- Sub-budgets ---
    sub_budget_rules = build_rules.get("sub_budget")
    if sub_budget_rules:
        _process_sub_budgets(sub_budget_rules, result)

    # --- Sum total budget ---
    if budget_rules:
        result.budget_spent = sum(result.costs.values())

    return result


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def _process_budget(rules: dict, char_attrs: dict[str, dict[str, str]], system_data: dict, result: BuildResult) -> None:
    """Set up point budget by evaluating a formula from the config."""
    from cruncher.formulas import FormulaContext, calc

    total_formula = rules.get("total", "0")
    ctx = FormulaContext()

    # Load defaults and character attributes as variables
    for key, val in system_data.get("defaults", {}).items():
        ctx.values[key] = val
    for cat_attrs in char_attrs.values():
        for key, val in cat_attrs.items():
            ctx.values[key] = _parse_number(val)

    try:
        result.budget_total = calc(total_formula, ctx)
    except Exception as e:
        result.budget_total = 0
        result.warnings.append(f"⚠ BUDGET: formula '{total_formula}' failed — {e}. Defaulting to 0.")


# ---------------------------------------------------------------------------
# Ranked purchase (generic: abilities, defenses, skills, etc.)
# ---------------------------------------------------------------------------


def _process_ranked_purchase(
    rules: dict, char_attrs: dict[str, dict[str, str]], category: str, result: BuildResult
) -> None:
    """Sum values for listed keys × cost_per_rank, track as category cost."""
    keys = rules.get("keys", [])
    cost_per_rank = rules.get("cost_per_rank", 1)
    rounding = rules.get("round", "none")

    total_ranks = 0
    for key in keys:
        val_str = _get_character_value(char_attrs, key)
        if val_str:
            total_ranks += _parse_number(val_str)

    if total_ranks == 0:
        return

    cost = total_ranks * cost_per_rank
    if rounding == "ceil":
        cost = math.ceil(cost)
    elif rounding == "floor":
        cost = math.floor(cost)

    if cost != 0:
        result.costs[category] = cost


# ---------------------------------------------------------------------------
# Pipeline (structured ability costing)
# ---------------------------------------------------------------------------


def _process_pipeline(
    rules: dict,
    pack_dir: str,
    char_abilities: list[dict[str, str]],
    system_data: dict,
    result: BuildResult,
    char_attrs: dict[str, dict[str, str]] | None = None,
) -> None:
    """Process structured abilities: compute costs via pipeline, apply feeds."""
    effect_source = rules.get("effect_source", "")
    modifier_source = rules.get("modifier_source", "")
    ability_category = rules.get("ability_category", "power")

    effects_data = {}
    modifiers_data = {}

    if effect_source:
        path = os.path.join(pack_dir, effect_source)
        if os.path.isfile(path):
            effects_data = _load_json(path)

    if modifier_source:
        path = os.path.join(pack_dir, modifier_source)
        if os.path.isfile(path):
            modifiers_data = _load_json(path)

    pipeline = system_data.get("pipeline", [])
    modifier_groups = rules.get("modifier_groups", [])
    stat_prefix = rules.get("stat_prefix", "")

    # Track stat keys covered by abilities to avoid double-counting with stat_prefix
    covered_stat_keys: set[str] = set()

    total_cost = 0
    for ability in char_abilities:
        if ability.get("category") != ability_category:
            continue

        ability_name = ability.get("name", "")

        power_data = _parse_structured_ability(ability)
        if not power_data:
            # No structured data — explicit cost is metadata only, not budgeted.
            # Cost must come from effect_* attrs (via _tally_stat_costs) or
            # from a structured description with {"effect": ...} or {"cost": ...}.
            explicit_cost = float(ability.get("cost", 0) or 0)
            if explicit_cost:
                result.warnings.append(
                    f"⚠ UNBUDGETED: ability '{ability_name}' (category: {ability_category}) "
                    f"has explicit cost={explicit_cost} but no structured data — "
                    f"cost not counted in budget. Use structured desc or set "
                    f"corresponding {stat_prefix}* attribute."
                )
            continue

        # Skip alternates — their cost is handled by _process_arrays
        if power_data.get("array_of"):
            continue

        if power_data.get("effect"):
            cost = _compute_pipeline_cost(
                power_data,
                effects_data,
                modifiers_data,
                pipeline,
                modifier_groups,
                warnings=result.warnings,
                ability_name=ability_name,
            )
        elif "cost" in power_data:
            cost = power_data["cost"]
        else:
            cost = 0
            result.warnings.append(
                f"⚠ UNCOSTED: ability '{ability_name}' (category: {ability_category}) "
                f"has structured data but no 'effect' or 'cost' field — 0 pts assumed"
            )

        total_cost += cost
        if cost and ability_name:
            powers_map = result.ability_costs.setdefault("powers", {})
            powers_map[ability_name] = powers_map.get(ability_name, 0) + cost

        # Apply feeds (stat contributions) and track covered keys
        if rules.get("feeds"):
            feeds = power_data.get("feeds", {})
            for stat, value in feeds.items():
                result.attributes[stat] = result.attributes.get(stat, 0) + value
                covered_stat_keys.add(stat)

        # Auto-apply per_rank_effects from effect definition
        effect_key = power_data.get("effect", "")
        ranks = int(power_data.get("ranks", 1))
        effect_def = effects_data.get(effect_key, {})
        per_rank = effect_def.get("per_rank_effects", {})
        for stat, spec in per_rank.items():
            if isinstance(spec, dict):
                per = spec.get("per", 1)
                value = spec.get("value", 0)
                bonus = (ranks // per) * value if per > 0 else 0
            else:
                bonus = spec * ranks
            if bonus:
                result.attributes[stat] = result.attributes.get(stat, 0) + bonus
                covered_stat_keys.add(stat)

    # Tally costs from stats set directly (not via abilities)
    if stat_prefix and effects_data and char_attrs:
        stat_cost = _tally_stat_costs(
            effects_data,
            char_attrs,
            stat_prefix,
            1,
            covered_stat_keys,
            "powers",
            result,
            cost_field="cost_per_rank",
        )
        total_cost += stat_cost

    if total_cost > 0:
        result.costs["powers"] = total_cost


def _parse_structured_ability(ability: dict[str, str]) -> dict | None:
    """Parse structured JSON from an ability's description field."""
    desc = ability.get("description", "")
    if not desc or not desc.strip().startswith("{"):
        return None
    try:
        data = json.loads(desc)
    except json.JSONDecodeError:
        return None
    return data if (data.get("effect") or "cost" in data or data.get("array_of")) else None


def _compute_pipeline_cost(
    data: dict,
    effects_data: dict,
    modifiers_data: dict,
    pipeline: list[dict],
    modifier_groups: list[dict],
    warnings: list[str] | None = None,
    ability_name: str = "",
) -> float:
    """Compute cost using pipeline stages.

    modifier_groups defines how to collect modifier costs from the modifiers
    data file into pipeline variables.  Each entry maps:
      source_key   – top-level key in the modifiers file (e.g. "extras")
      ability_key  – key in the ability's structured data (e.g. "extras")
      pipeline_var – variable name exposed to pipeline formulas (e.g. "sum_extras")
      default_cost – fallback cost when a modifier lacks an explicit cost
    Multiple groups may contribute to the same pipeline_var (values are summed).
    """
    if not pipeline:
        return 0

    # Look up base effect cost
    effect_key = data.get("effect", "")
    effect_def = effects_data.get(effect_key, {})
    if not isinstance(effect_def, dict):
        return 0

    base_cost = effect_def.get("cost_per_rank", 1)
    ranks = data.get("ranks", 0)

    # Collect modifier costs into pipeline variables
    pipeline_vars: dict[str, float] = {}
    for group in modifier_groups:
        source_key = group.get("source_key", "")
        ability_key = group.get("ability_key", "")
        pipeline_var = group.get("pipeline_var", "")
        default_cost = group.get("default_cost", 0)

        source = modifiers_data.get(source_key, {})
        total = sum(source.get(k, {}).get("cost", default_cost) for k in data.get(ability_key, []))
        pipeline_vars[pipeline_var] = pipeline_vars.get(pipeline_var, 0) + total

    return _run_pipeline(
        pipeline,
        base_cost,
        ranks,
        pipeline_vars,
        data.get("removable", 0),
        warnings=warnings,
        ability_name=ability_name,
    )


def _run_pipeline(
    pipeline: list[dict],
    base_cost: float,
    ranks: int,
    pipeline_vars: dict[str, float],
    removable: int,
    warnings: list[str] | None = None,
    ability_name: str = "",
) -> float:
    """Run pipeline stages using the formula evaluator."""
    from cruncher.formulas import FormulaContext, calc

    ctx_values = {
        "base_cost_per_rank": base_cost,
        "ranks": ranks,
        "removable": removable,
        **pipeline_vars,
    }

    prev = 0
    for stage in pipeline:
        formula = stage.get("formula", "0")
        stage_name = stage.get("stage", "?")
        ctx = FormulaContext(values={**ctx_values, "prev": prev})
        try:
            prev = calc(formula, ctx)
        except Exception as e:
            if warnings is not None:
                warnings.append(
                    f"⚠ PIPELINE: stage '{stage_name}' failed for '{ability_name}' — {e}. Using previous value."
                )

    return prev


# ---------------------------------------------------------------------------
# Arrays
# ---------------------------------------------------------------------------


def _process_arrays(rules: dict, char_abilities: list[dict[str, str]], result: BuildResult) -> None:
    """Process arrays — alternates cost flat points on top of the primary."""
    alternate_cost = rules.get("alternate_cost", 1)
    dynamic_cost = rules.get("dynamic_cost", 2)

    total_cost = 0
    for ability in char_abilities:
        data = _parse_structured_ability(ability)
        if not data or not data.get("array_of"):
            continue

        ability_name = ability.get("name", "")
        if data.get("dynamic"):
            cost = dynamic_cost
        else:
            cost = alternate_cost
        total_cost += cost
        if cost and ability_name:
            arrays_map = result.ability_costs.setdefault("arrays", {})
            arrays_map[ability_name] = arrays_map.get(ability_name, 0) + cost

    if total_cost > 0:
        result.costs["arrays"] = total_cost


# ---------------------------------------------------------------------------
# Sub-budgets
# ---------------------------------------------------------------------------


def _process_sub_budgets(rules: dict, result: BuildResult) -> None:
    """Process sub-budgets (a computed attribute grants a secondary pool)."""
    for name, sub_rules in rules.items():
        source_attr = sub_rules.get("source_attribute", "")
        points_per_rank = sub_rules.get("points_per_rank", 5)

        attr_value = result.attributes.get(source_attr, 0)
        if attr_value:
            result.attributes[f"{name}_points_total"] = attr_value * points_per_rank


# ---------------------------------------------------------------------------
# Stat-prefix cost tallying
# ---------------------------------------------------------------------------


def _tally_stat_costs(
    source_data: dict,
    char_attrs: dict[str, dict[str, str]],
    prefix: str,
    default_cost: float,
    covered_keys: set[str],
    category: str,
    result: BuildResult,
    cost_field: str = "cost",
) -> float:
    """Tally costs from character stats whose keys start with *prefix*.

    For each stat key matching ``{prefix}{base_key}``, look up the base_key in
    *source_data* to determine the per-rank cost (via *cost_field*), then
    multiply by the stat value.  Stats whose key is in *covered_keys* (already
    costed through abilities) are skipped to avoid double-counting.

    """
    total = 0.0
    for cat_attrs in char_attrs.values():
        for key, val_str in cat_attrs.items():
            if not key.startswith(prefix):
                continue
            if key in covered_keys:
                continue

            val = _parse_number(val_str)
            if val == 0:
                continue

            base_key = key[len(prefix) :]
            item_def = source_data.get(base_key, {})
            if isinstance(item_def, dict):
                item_cost = item_def.get(cost_field, default_cost)
            else:
                item_cost = default_cost

            cost = val * item_cost
            total += cost

            # Track in ability_costs for budget reporting
            cat_costs = result.ability_costs.setdefault(category, {})
            cat_costs[key] = cat_costs.get(key, 0) + cost

    return total


# ---------------------------------------------------------------------------
# Source-based operations (writes, effects, progressions)
# ---------------------------------------------------------------------------


def _flatten_catalog(data: Any) -> dict[str, dict]:
    """Flatten a JSON subtree into a name-keyed dict.

    Handles:
    - list of dicts with "name" key
    - dict of dicts (key becomes name)
    - nested dicts of lists (recursively flattens all sublists)
    """
    result: dict[str, dict] = {}

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "name" in item:
                result[item["name"].lower()] = item
    elif isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list):
                # Nested subcategory (e.g., weapons.simple_melee)
                for item in value:
                    if isinstance(item, dict) and "name" in item:
                        result[item["name"].lower()] = item
            elif isinstance(value, dict) and "name" in value:
                result[value["name"].lower()] = value
            elif isinstance(value, dict):
                # Could be a name-keyed dict
                result[key.lower()] = value

    return result


def _process_source(
    pack_dir: str,
    rules: dict,
    category: str,
    char_attrs: dict[str, dict[str, str]],
    char_abilities: list[dict[str, str]],
    level: int,
    result: BuildResult,
    char_items: list[dict[str, Any]] | None = None,
) -> None:
    """Process a source-based build category."""
    source_pattern = rules["source"]
    has_writes = "writes" in rules
    has_effects = rules.get("effects", False)
    has_progressions = "progressions" in rules
    cost_per_rank = rules.get("cost_per_rank", 0)

    # Template expansion for patterns like "classes/{class}.json"
    if "{" in source_pattern:
        expanded = _expand_template(source_pattern, char_attrs)
        if not expanded:
            return
        full_path = os.path.join(pack_dir, expanded)
        if not os.path.isfile(full_path):
            result.warnings.append(f"Source not found: {expanded}")
            return

        source_data = _load_json(full_path)
        if has_writes:
            _apply_writes(rules["writes"], source_data, result)
        if has_progressions:
            _apply_progressions(rules["progressions"], source_data, level, result)
        return

    # Regular sources
    full_path = os.path.join(pack_dir, source_pattern)
    if not os.path.isfile(full_path):
        result.warnings.append(f"⚠ SOURCE: file '{source_pattern}' not found for category '{category}'")
        return

    source_data = _load_json(full_path)
    select_mode = rules.get("select", "single")

    if select_mode == "single":
        selected_key = _get_character_value(char_attrs, category)
        if not selected_key:
            return
        selected_key = selected_key.lower().replace(" ", "_")
        item = source_data.get(selected_key)
        if not item:
            result.warnings.append(
                f"⚠ SOURCE: '{selected_key}' not found in '{source_pattern}' for category '{category}'"
            )
            return
        if has_writes:
            _apply_writes(rules["writes"], item, result)
        if has_effects:
            for key, value in item.get("effects", {}).items():
                if isinstance(value, (int, float)):
                    result.attributes[key] = result.attributes.get(key, 0) + value

    elif select_mode == "multiple":
        if has_effects:
            ability_category = rules.get("ability_category", "")
            effect_cost, covered_stats = _apply_effects(
                source_data,
                char_abilities,
                result,
                cost_per_rank,
                category=ability_category,
                char_attrs=char_attrs,
                level=level,
            )
            if effect_cost > 0:
                result.costs[category] = result.costs.get(category, 0) + effect_cost

            # Tally costs from stats set directly (not via abilities)
            stat_prefix = rules.get("stat_prefix", "")
            if stat_prefix and cost_per_rank > 0:
                stat_cost = _tally_stat_costs(
                    source_data, char_attrs, stat_prefix, cost_per_rank, covered_stats, category, result
                )
                if stat_cost > 0:
                    result.costs[category] = result.costs.get(category, 0) + stat_cost

    elif select_mode == "equipped":
        items = char_items or []
        if not items or not has_writes:
            return

        # Scope to catalog subtree if specified
        catalog_data = source_data
        catalog_path = rules.get("catalog_path")
        if catalog_path:
            catalog_data = _resolve_path(source_data, catalog_path)
            if catalog_data is None:
                return

        catalog = _flatten_catalog(catalog_data)

        for inv_item in items:
            item_name = inv_item.get("name", "").lower()
            matched = catalog.get(item_name)
            if matched:
                _apply_writes(rules["writes"], matched, result)


def _apply_writes(write_map: dict[str, str], source_data: dict, result: BuildResult) -> None:
    """Copy fields from source data to result attributes."""
    for attr_name, source_field in write_map.items():
        value = _resolve_path(source_data, source_field)
        if value is not None:
            result.attributes[attr_name] = value


def _apply_progressions(progressions_path: str, source_data: dict, level: int, result: BuildResult) -> None:
    """Look up progression tables at the current level."""
    prog_map = _resolve_path(source_data, progressions_path)
    if not isinstance(prog_map, dict):
        return

    tables = source_data.get("tables", {})
    for var_name, table_key in prog_map.items():
        table = tables.get(table_key)
        if not table or not isinstance(table, list):
            result.warnings.append(f"⚠ PROGRESSION: table '{table_key}' not found for '{var_name}'")
            continue
        if level > len(table):
            result.warnings.append(
                f"⚠ PROGRESSION: level {level} exceeds table '{table_key}' (max {len(table)}) for '{var_name}'"
            )
            continue
        result.attributes[var_name] = table[level - 1]


def _check_prereqs(
    prereqs: dict,
    char_attrs: dict[str, dict[str, str]],
    char_abilities: list[dict[str, str]],
    level: int,
    feat_name: str,
    result: BuildResult,
) -> None:
    """Check feat prerequisites against character state. Adds warnings for failures."""
    for key, required in prereqs.items():
        # Special case: level is on CharacterData, not in attributes
        if key == "level":
            if level < required:
                result.warnings.append(
                    f"\u26a0 PREREQ: '{feat_name}' requires level >= {required} (character is level {level})"
                )
            continue

        # Boolean prereq: check if character has a feat/ability with that name
        if required is True:
            ability_names = {a["name"].lower().replace(" ", "_").replace("-", "_") for a in char_abilities}
            if key not in ability_names:
                result.warnings.append(f"\u26a0 PREREQ: '{feat_name}' requires feat '{key}'")
            continue

        # Generic attribute lookup: search across all categories
        found_value = None
        for cat_attrs in char_attrs.values():
            if key in cat_attrs:
                found_value = cat_attrs[key]
                break

        if found_value is None:
            # Attribute not found — can't validate, skip silently
            continue

        # Numeric comparison
        if isinstance(required, (int, float)):
            try:
                actual = float(found_value)
            except (ValueError, TypeError):
                continue
            if actual < required:
                result.warnings.append(f"\u26a0 PREREQ: '{feat_name}' requires {key} >= {required} (has {int(actual)})")
        # String equality
        elif isinstance(required, str):
            if str(found_value).lower() != required.lower():
                result.warnings.append(
                    f"\u26a0 PREREQ: '{feat_name}' requires {key} == '{required}' (has '{found_value}')"
                )


def _apply_effects(
    source_data: dict,
    char_abilities: list[dict[str, str]],
    result: BuildResult,
    cost_per_rank: float = 0,
    category: str = "",
    char_attrs: dict[str, dict[str, str]] | None = None,
    level: int = 0,
) -> tuple[float, set[str]]:
    """Aggregate effects from character abilities into result attributes.

    Effect keys from the data file are used as-is — the engine does not
    interpret or prefix them.

    Returns (total_cost, covered_stat_keys) where covered_stat_keys is the
    set of stat keys written as bonuses (used by stat_prefix to avoid
    double-counting).
    """
    bonuses: dict[str, float] = {}
    total_cost = 0.0

    for ability in char_abilities:
        # Filter by category if specified
        if category and ability.get("category") != category:
            continue

        ability_key = ability["name"].lower().replace(" ", "_").replace("-", "_")
        item_def = source_data.get(ability_key)

        # Try stripping parenthesized parameter (e.g. "Skill Mastery (Deception)" → "skill_mastery")
        if not item_def or not isinstance(item_def, dict):
            base_key = re.sub(r"_?\([^)]*\)", "", ability_key).rstrip("_")
            if base_key != ability_key:
                item_def = source_data.get(base_key)

        # Try stripping trailing number for ranked advantages (e.g. "Close Attack 6" → "close_attack")
        if (not item_def or not isinstance(item_def, dict)) and ability_key[-1:].isdigit():
            base_key = ability_key.rstrip("0123456789").rstrip("_")
            item_def = source_data.get(base_key)

        if not item_def or not isinstance(item_def, dict):
            # Not in source data — use explicit cost field from the ability
            if cost_per_rank > 0:
                explicit_cost = float(ability.get("cost", 0) or 0)
                if explicit_cost:
                    total_cost += explicit_cost
            continue

        # Check prerequisites
        prereqs = item_def.get("prereqs")
        if prereqs and char_attrs is not None:
            _check_prereqs(prereqs, char_attrs, char_abilities, level, ability_key, result)

        # Extract rank from ability name suffix (e.g. "Close Attack 6" → 6)
        rank = 1
        if item_def.get("ranked", False):
            rank_match = re.search(r"\s(\d+)$", ability["name"])
            if rank_match:
                rank = int(rank_match.group(1))

        # Parameterized effects (e.g. Skill Mastery (Deception) → floor_skill_deception: 10)
        param_effects = item_def.get("parameterized_effects")
        if param_effects:
            param_match = re.search(r"\(([^)]+)\)", ability["name"])
            if param_match:
                param_val = param_match.group(1).lower().replace(" ", "_").replace("-", "_")
                for stat_template, value in param_effects.items():
                    stat = stat_template.replace("{param}", param_val)
                    bonuses[stat] = value

        effects = item_def.get("effects", {})
        per_rank = item_def.get("per_rank_effects", {})
        if not effects and not per_rank and not param_effects:
            # No effects to apply (includes combat options with empty effects)
            if cost_per_rank > 0:
                item_cost = item_def.get("cost", cost_per_rank)
                total_cost += item_cost * rank
            continue
        elif not effects and not per_rank:
            # Has parameterized effects but no regular effects — still count cost
            if cost_per_rank > 0:
                item_cost = item_def.get("cost", cost_per_rank)
                total_cost += item_cost * rank
            continue

        if item_def.get("ranked", False):
            effects = item_def.get("effects_per_rank", effects)

        # Merge per_rank_effects into effects (per_rank_effects take precedence)
        if per_rank:
            effects = {**effects, **per_rank}

        for stat, effect_val in effects.items():
            if isinstance(effect_val, dict):
                bonus = effect_val.get("value", 0)
                per = effect_val.get("per")
                if per and per > 0:
                    # per_rank_effects: floor(rank / per) * value
                    bonuses[stat] = bonuses.get(stat, 0) + (rank // per) * bonus
                    continue
            else:
                bonus = effect_val
            bonuses[stat] = bonuses.get(stat, 0) + bonus * rank

        if cost_per_rank > 0:
            item_cost = item_def.get("cost", cost_per_rank)
            total_cost += item_cost * rank

    # Write aggregated values — keys used as-is from the data
    for stat, total in bonuses.items():
        result.attributes[stat] = result.attributes.get(stat, 0) + total

    return total_cost, set(bonuses.keys())
