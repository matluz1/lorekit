#!/usr/bin/env python3
"""LoreKit MCP server -- long-lived process with cached embedding model."""

import importlib
import sys

import lorekit.tools
from lorekit._mcp_app import mcp

_EXPORTS = {
    # tools/_helpers.py
    "_resolve_character": "lorekit.tools._helpers",
    "_run_with_db": "lorekit.tools._helpers",
    "_session_for_character": "lorekit.tools._helpers",
    "_timeskip_hours": "lorekit.tools._helpers",
    "_embed_ability_metadata": "lorekit.tools._helpers",
    "_auto_register_reactions": "lorekit.tools._helpers",
    "_resolve_system_path_for_session": "lorekit.tools._helpers",
    "_resolve_system_path_for_character": "lorekit.tools._helpers",
    "_sync_condition_modifiers_for": "lorekit.tools._helpers",
    "_load_combat_cfg": "lorekit.tools._helpers",
    # tools/session.py
    "init_db": "lorekit.tools.session",
    "session_create": "lorekit.tools.session",
    "session_view": "lorekit.tools.session",
    "session_list": "lorekit.tools.session",
    "session_update": "lorekit.tools.session",
    "session_meta_set": "lorekit.tools.session",
    "session_meta_get": "lorekit.tools.session",
    "session_setup": "lorekit.tools.session",
    "session_resume": "lorekit.tools.session",
    # tools/story.py
    "story": "lorekit.tools.story",
    "story_set": "lorekit.tools.story",
    "story_view": "lorekit.tools.story",
    "story_add_act": "lorekit.tools.story",
    "story_view_act": "lorekit.tools.story",
    "story_update_act": "lorekit.tools.story",
    "story_advance": "lorekit.tools.story",
    # tools/character.py
    "character_create": "lorekit.tools.character",
    "character_view": "lorekit.tools.character",
    "character_list": "lorekit.tools.character",
    "character_update": "lorekit.tools.character",
    "character_set_attr": "lorekit.tools.character",
    "character_get_attr": "lorekit.tools.character",
    "character_set_item": "lorekit.tools.character",
    "character_get_items": "lorekit.tools.character",
    "character_remove_item": "lorekit.tools.character",
    "character_set_ability": "lorekit.tools.character",
    "character_get_abilities": "lorekit.tools.character",
    "character_build": "lorekit.tools.character",
    "ability_from_template": "lorekit.tools.character",
    "character_sheet_update": "lorekit.tools.character",
    # tools/narrative.py
    "region": "lorekit.tools.narrative",
    "region_create": "lorekit.tools.narrative",
    "region_list": "lorekit.tools.narrative",
    "region_view": "lorekit.tools.narrative",
    "region_update": "lorekit.tools.narrative",
    "timeline_add": "lorekit.tools.narrative",
    "timeline_list": "lorekit.tools.narrative",
    "timeline_search": "lorekit.tools.narrative",
    "timeline_set_summary": "lorekit.tools.narrative",
    "turn_revert": "lorekit.tools.narrative",
    "turn_advance": "lorekit.tools.narrative",
    "turn_save": "lorekit.tools.narrative",
    "journal_add": "lorekit.tools.narrative",
    "journal_list": "lorekit.tools.narrative",
    "journal_search": "lorekit.tools.narrative",
    "time_get": "lorekit.tools.narrative",
    "time_set": "lorekit.tools.narrative",
    "time_advance": "lorekit.tools.narrative",
    # tools/utility.py
    "roll_dice": "lorekit.tools.utility",
    "recall_search": "lorekit.tools.utility",
    "recall_reindex": "lorekit.tools.utility",
    "export_dump": "lorekit.tools.utility",
    "export_clean": "lorekit.tools.utility",
    "rest": "lorekit.tools.utility",
    # tools/rules.py
    "system_info": "lorekit.tools.rules",
    "rules_check": "lorekit.tools.rules",
    "rules_resolve": "lorekit.tools.rules",
    "rules_calc": "lorekit.tools.rules",
    "end_turn": "lorekit.tools.rules",
    "combat_modifier": "lorekit.tools.rules",
    "rules_modifiers": "lorekit.tools.rules",
    # tools/npc.py
    "_NPC_ALLOWED_TOOLS": "lorekit.tools.npc",
    "_MCP_PREFIX": "lorekit.tools.npc",
    "_NPC_ALLOWED_SET": "lorekit.tools.npc",
    "_get_npc_disallowed_tools": "lorekit.tools.npc",
    "_load_npc_guides": "lorekit.tools.npc",
    "_build_npc_prompt": "lorekit.tools.npc",
    "_npc_log": "lorekit.tools.npc",
    "_parse_npc_stream": "lorekit.tools.npc",
    "_is_npc_http_server_running": "lorekit.tools.npc",
    "npc_interact": "lorekit.tools.npc",
    "npc_memory_add": "lorekit.tools.npc",
    "npc_reflect": "lorekit.tools.npc",
    "entry_untag": "lorekit.tools.npc",
    "npc_combat_turn": "lorekit.tools.npc",
    # tools/encounter.py
    "encounter_start": "lorekit.tools.encounter",
    "encounter_status": "lorekit.tools.encounter",
    "encounter_move": "lorekit.tools.encounter",
    "encounter_advance_turn": "lorekit.tools.encounter",
    "encounter_ready": "lorekit.tools.encounter",
    "encounter_execute_ready": "lorekit.tools.encounter",
    "encounter_delay": "lorekit.tools.encounter",
    "encounter_undelay": "lorekit.tools.encounter",
    "encounter_end": "lorekit.tools.encounter",
    "encounter_join": "lorekit.tools.encounter",
    "encounter_leave": "lorekit.tools.encounter",
    "encounter_zone_update": "lorekit.tools.encounter",
    "encounter_zone_add": "lorekit.tools.encounter",
    "encounter_zone_remove": "lorekit.tools.encounter",
    # _mcp_app.py
    "NPC_MCP_PORT": "lorekit._mcp_app",
}


def __getattr__(name):
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module 'lorekit.server' has no attribute {name!r}")
    mod = importlib.import_module(module_path)
    val = getattr(mod, name)
    globals()[name] = val
    return val


if __name__ == "__main__":
    from lorekit.support.vectordb import _get_model

    _get_model()

    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
