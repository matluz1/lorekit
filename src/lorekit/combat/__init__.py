"""Combat engine — action resolution and turn lifecycle."""

import importlib

_SUBMODULE_MAP = {
    # conditions.py
    "get_active_conditions": "lorekit.combat.conditions",
    "is_incapacitated": "lorekit.combat.conditions",
    "_check_condition_action_limit": "lorekit.combat.conditions",
    "_increment_turn_actions": "lorekit.combat.conditions",
    "expand_conditions": "lorekit.combat.conditions",
    "sync_condition_modifiers": "lorekit.combat.conditions",
    # helpers.py
    "_get_defender_resolution_effects": "lorekit.combat.helpers",
    "_sync_and_recalc": "lorekit.combat.helpers",
    "_get_derived": "lorekit.combat.helpers",
    "_is_crit": "lorekit.combat.helpers",
    "_get_action_def": "lorekit.combat.helpers",
    "_get_gm_hints": "lorekit.combat.helpers",
    "_get_attr_str": "lorekit.combat.helpers",
    "_write_attr": "lorekit.combat.helpers",
    "_read_resource": "lorekit.combat.helpers",
    "_write_resource": "lorekit.combat.helpers",
    "_ensure_current_hp": "lorekit.combat.helpers",
    "_char_name_from_id": "lorekit.combat.helpers",
    # effects.py
    "_apply_degree_effect": "lorekit.combat.effects",
    "_check_on_hit_resist": "lorekit.combat.effects",
    "_apply_on_hit": "lorekit.combat.effects",
    "_fire_damage_triggers": "lorekit.combat.effects",
    "_check_contagious": "lorekit.combat.effects",
    # options.py
    "_expand_combat_options": "lorekit.combat.options",
    "_apply_trade_modifiers": "lorekit.combat.options",
    "_apply_team_bonus": "lorekit.combat.options",
    "_check_pre_resolution": "lorekit.combat.options",
    # reactions.py
    "_get_reaction_policy": "lorekit.combat.reactions",
    "_check_reactions": "lorekit.combat.reactions",
    # turns.py
    "end_turn": "lorekit.combat.turns",
    "start_turn": "lorekit.combat.turns",
    # powers.py
    "_check_switch_limit": "lorekit.combat.powers",
    "_increment_switches": "lorekit.combat.powers",
    "activate_power": "lorekit.combat.powers",
    "deactivate_power": "lorekit.combat.powers",
    "switch_alternate": "lorekit.combat.powers",
    # area.py
    "resolve_area_action": "lorekit.combat.area",
    # resolve.py
    "_contested_roll": "lorekit.combat.resolve",
    "_resolve_threshold": "lorekit.combat.resolve",
    "_resolve_degree": "lorekit.combat.resolve",
    "resolve_action": "lorekit.combat.resolve",
}


def __getattr__(name):
    module_path = _SUBMODULE_MAP.get(name)
    if module_path is None:
        raise AttributeError(f"module 'lorekit.combat' has no attribute {name!r}")
    mod = importlib.import_module(module_path)
    val = getattr(mod, name)
    globals()[name] = val
    return val
